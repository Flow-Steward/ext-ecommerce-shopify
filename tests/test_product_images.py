"""Images travel with creation requests, including each bulk JSONL row."""

import json

import pytest
from conftest import (
    FakeHttp,
    FakeResponse,
    connection,
    graphql_response,
    product_node,
    run_action,
    variant_node,
)
from test_bulk_products import accepted, invoke, staged

IMAGES = [
    {"url": "https://cdn.example.com/boots.jpg?version=2", "alt": "Зимние ботинки"},
    {"url": "https://cdn.example.com/back.png"},
]
PRODUCT = {"title": "Boots", "handle": "boots", "images": IMAGES}
MEDIA = [
    {
        "mediaContentType": "IMAGE",
        "originalSource": item["url"],
        **({"alt": item["alt"]} if "alt" in item else {}),
    }
    for item in IMAGES
]


def test_single_create_submits_images_alongside_product(http):
    http.queue(
        graphql_response(
            {
                "productCreate": {
                    "product": product_node(variants=connection([variant_node()])),
                    "userErrors": [],
                }
            }
        )
    )
    result = run_action("create_product", PRODUCT, http)
    assert result["ok"] is True, result
    assert http.variables()["media"] == MEDIA
    assert "images" not in http.variables()["product"]
    assert "media: $media" in http.document()


@pytest.mark.parametrize("artifact", [False, True])
def test_bulk_submits_images_in_each_rows_media_variable(http, artifact):
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
    assert (
        json.dumps(MEDIA, ensure_ascii=False, separators=(",", ":")).encode()
        in storage.last["body"]
    )
    assert "media: $media" in http.variables(1)["mutation"]


@pytest.mark.parametrize(
    "images",
    [
        [{"url": "file:///tmp/picture.jpg"}],
        [{"url": "http://example.com/a.jpg"}],
        [{"url": "https:///a.jpg"}],
        [{"url": "https://user:secret@example.com/a.jpg"}],
        [{"url": "https://example.com/a\n.jpg"}],
        [{"alt": "No URL"}],
        [{"url": "https://example.com/a.jpg", "unknown": True}],
        IMAGES * 126,
    ],
)
@pytest.mark.parametrize("bulk", [False, True])
def test_invalid_images_rejected_before_io(http, images, bulk):
    product = {**PRODUCT, "images": images}
    result = (
        invoke(http, {"products": [product]})
        if bulk
        else run_action("create_product", product, http)
    )
    assert result["ok"] is False
    assert result["error_code"] == "invalid_payload"
    assert not http.requests


@pytest.mark.parametrize("images", [None, []])
def test_creating_without_images_keeps_media_variable_absent(http, images):
    http.queue(
        graphql_response(
            {
                "productCreate": {
                    "product": product_node(variants=connection([variant_node()])),
                    "userErrors": [],
                }
            }
        )
    )
    product = {"title": "Boots", "handle": "boots"}
    if images is not None:
        product["images"] = images
    result = run_action("create_product", product, http)
    assert result["ok"] is True
    assert "media" not in http.variables()


def test_bad_image_in_last_artifact_row_prevents_entire_batch_upload(http):
    bad = {**PRODUCT, "handle": "bad", "images": [{"url": "file:///tmp/a.jpg"}]}
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
