"""Images reach a product by URL, by existing Shopify file, or uploaded from an artifact."""

import json

import pytest
from conftest import (
    MEDIA_A,
    PRODUCT_A,
    FakeHttp,
    FakeResponse,
    action_payload,
    connection,
    graphql_response,
    product_node,
    run_action,
    variant_node,
)
from test_bulk_products import accepted, invoke, staged

from runtime.operations import handle_runtime
from runtime.transport import ShopifyGraphQLTransport

MEDIA = [
    {"source_url": "https://cdn.example.com/boots.jpg?version=2", "alt": "Зимние ботинки"},
    {"source_url": "https://cdn.example.com/back.png"},
]
PRODUCT = {"title": "Boots", "handle": "boots", "media": MEDIA}
FILES = [
    {"originalSource": item["source_url"], **({"alt": item["alt"]} if "alt" in item else {})}
    for item in MEDIA
]

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
STORAGE = "https://shopify-staged-uploads.storage.googleapis.com/"


def _created():
    return graphql_response(
        {
            "productSet": {
                "product": product_node(variants=connection([variant_node()])),
                "userErrors": [],
            }
        }
    )


def _staged_body(count: int = 1) -> dict:
    return {
        "data": {
            "stagedUploadsCreate": {
                "stagedTargets": [
                    {
                        "url": STORAGE,
                        "resourceUrl": f"{STORAGE}tmp/1/products/{index}/boots.png",
                        "parameters": [
                            {"name": "key", "value": f"tmp/1/products/{index}/boots.png"},
                            {"name": "Content-Type", "value": "image/png"},
                        ],
                    }
                    for index in range(count)
                ],
                "userErrors": [],
            }
        }
    }


def _staged(count: int = 1) -> FakeResponse:
    return FakeResponse(200, json.dumps(_staged_body(count)).encode())


def _run(operation_id, operation_input, http, storage, reader):
    return handle_runtime(
        action_payload(operation_id, operation_input),
        transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
        artifact_reader=reader,
        storage_opener=storage,
    )


def test_single_create_attaches_media_as_product_files(http):
    http.queue(_created())

    result = run_action("create_product", PRODUCT, http)

    assert result["ok"] is True, result
    assert http.variables()["input"]["files"] == FILES
    assert "media" not in http.variables()["input"]


def test_an_existing_shopify_file_can_be_attached_by_id(http):
    http.queue(_created())

    result = run_action(
        "create_product",
        {"title": "Boots", "handle": "boots", "media": [{"file_id": MEDIA_A}]},
        http,
    )

    assert result["ok"] is True, result
    assert http.variables()["input"]["files"] == [{"id": MEDIA_A}]


def test_an_artifact_image_is_staged_uploaded_then_attached(http):
    storage = FakeHttp()
    storage.queue(FakeResponse(204, b""))
    http.queue(_staged(), _created())
    reads: list[str] = []

    def reader(payload, *, artifact_id):
        reads.append(artifact_id)
        return PNG

    result = _run(
        "create_product",
        {
            "title": "Boots",
            "handle": "boots",
            "image_files": [{"artifact_handle": "artifact:img-1", "alt": "Front"}],
        },
        http,
        storage,
        reader,
    )

    assert result["ok"] is True, result
    assert reads == ["artifact:img-1"]
    staging = http.variables(0)["input"][0]
    assert staging["resource"] == "IMAGE"
    assert staging["mimeType"] == "image/png"
    assert staging["fileSize"] == str(len(PNG))
    assert staging["filename"] == "image-1.png"
    assert storage.last["url"] == STORAGE
    assert PNG in storage.last["body"]
    assert http.variables(1)["input"]["files"] == [
        {
            "originalSource": f"{STORAGE}tmp/1/products/0/boots.png",
            "contentType": "IMAGE",
            "alt": "Front",
            "filename": "image-1.png",
        }
    ]


def test_update_product_attaches_new_images_from_artifacts(http):
    storage = FakeHttp()
    storage.queue(FakeResponse(201, b""))
    http.queue(
        _staged(),
        graphql_response({"productUpdate": {"product": product_node(), "userErrors": []}}),
    )

    result = _run(
        "update_product",
        {
            "product_id": PRODUCT_A,
            "image_files": [{"artifact_handle": "artifact:img-1", "filename": "front shot.png"}],
        },
        http,
        storage,
        lambda payload, *, artifact_id: PNG,
    )

    assert result["ok"] is True, result
    assert http.variables(1)["media"] == [
        {"originalSource": f"{STORAGE}tmp/1/products/0/boots.png", "mediaContentType": "IMAGE"}
    ]
    assert http.variables(0)["input"][0]["filename"] == "front-shot.png"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"GIF89a" + b"\x00" * 10, None),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 10, None),
        (b"%PDF-1.7 not an image", "not a JPEG, PNG, GIF or WEBP image"),
        (b"", "is empty"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * (20 * 1024 * 1024), "20 MB"),
    ],
)
def test_an_artifact_that_is_not_a_usable_image_is_refused_before_staging(http, body, message):
    storage = FakeHttp()
    storage.queue(FakeResponse(204, b""))
    http.queue(_staged(), _created())

    result = _run(
        "create_product",
        {"title": "Boots", "handle": "boots", "image_files": [{"artifact_handle": "a:1"}]},
        http,
        storage,
        lambda payload, *, artifact_id: body,
    )

    if message is None:
        assert result["ok"] is True, result
        return
    assert result["error_code"] == "invalid_payload"
    assert message in result["error"]
    assert http.requests == [] and storage.requests == []


def test_a_staging_target_on_another_host_is_refused(http):
    storage = FakeHttp()
    bad = _staged_body()
    bad["data"]["stagedUploadsCreate"]["stagedTargets"][0]["url"] = "https://evil.example/"
    http.queue(FakeResponse(200, json.dumps(bad).encode()))

    result = _run(
        "create_product",
        {"title": "Boots", "handle": "boots", "image_files": [{"artifact_handle": "a:1"}]},
        http,
        storage,
        lambda payload, *, artifact_id: PNG,
    )

    assert result["ok"] is False
    assert storage.requests == []
    assert len(http.requests) == 1  # the product mutation was never sent


def test_test_mode_never_reads_or_stages_an_artifact(http):
    storage = FakeHttp()

    def reader(payload, *, artifact_id):
        raise AssertionError("a rehearsal read an artifact")

    result = handle_runtime(
        action_payload(
            "create_product",
            {"title": "Boots", "handle": "boots", "image_files": [{"artifact_handle": "a:1"}]},
            test_mode=True,
        ),
        transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
        artifact_reader=reader,
        storage_opener=storage,
    )

    assert result["external_effect_status"] == "suppressed"
    assert http.requests == [] and storage.requests == []


@pytest.mark.parametrize("artifact", [False, True])
def test_bulk_rows_carry_their_media_as_product_set_files(http, artifact):
    storage = FakeHttp()
    storage.queue(FakeResponse(201, b""))
    http.queue(staged(), accepted())
    inputs = {"artifact_handle": "artifact:input"} if artifact else {"products": [PRODUCT]}
    result = invoke(
        http,
        inputs,
        storage_opener=storage,
        artifact_reader=lambda *args, **kwargs: json.dumps(PRODUCT).encode(),
    )
    assert result["ok"] is True, result
    files = json.dumps(FILES, ensure_ascii=False, separators=(",", ":")).encode()
    assert b'"files":' + files in storage.last["body"]
    assert "productSet(input: $input)" in http.variables(1)["mutation"]


@pytest.mark.parametrize(
    "media",
    [
        [{"source_url": "file:///tmp/picture.jpg"}],
        [{"source_url": "http://example.com/a.jpg"}],
        [{"source_url": "https:///a.jpg"}],
        [{"source_url": "https://user:secret@example.com/a.jpg"}],
        [{"source_url": "https://example.com/a\n.jpg"}],
        [{"alt": "No source"}],
        [{"source_url": "https://example.com/a.jpg", "file_id": MEDIA_A}],
        [{"source_url": "https://example.com/a.jpg", "unknown": True}],
        MEDIA * 126,
    ],
)
@pytest.mark.parametrize("bulk", [False, True])
def test_invalid_media_rejected_before_io(http, media, bulk):
    product = {**PRODUCT, "media": media}
    result = (
        invoke(http, {"products": [product]})
        if bulk
        else run_action("create_product", product, http)
    )
    assert result["ok"] is False
    assert result["error_code"] == "invalid_payload"
    assert not http.requests


def test_bad_media_in_last_artifact_row_prevents_entire_batch_upload(http):
    bad = {**PRODUCT, "handle": "bad", "media": [{"source_url": "file:///tmp/a.jpg"}]}
    source = b"\n".join(json.dumps(row).encode() for row in [PRODUCT, bad])
    storage = FakeHttp()
    result = invoke(
        http,
        {"artifact_handle": "artifact:input"},
        storage_opener=storage,
        artifact_reader=lambda *args, **kwargs: source,
    )
    assert result["error_code"] == "invalid_payload"
    assert not http.requests and not storage.requests
