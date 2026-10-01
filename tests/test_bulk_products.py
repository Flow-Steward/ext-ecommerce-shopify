"""Bulk product import submits once and reports completion separately."""

from __future__ import annotations

import pytest
from conftest import (
    EXTERNAL_EFFECT_ID,
    FakeHttp,
    FakeResponse,
    connection_payload,
    graphql_response,
)
from runtime.operations import handle_runtime
from runtime.transport import ShopifyGraphQLTransport

BULK_ID = "gid://shopify/BulkOperation/9001"
PRODUCTS = [{"title": "Boots", "handle": "boots", "description_html": "<p>Warm</p>"}]


def staged():
    return graphql_response(
        {
            "stagedUploadsCreate": {
                "userErrors": [],
                "stagedTargets": [
                    {
                        "url": "https://shopify-staged-uploads.storage.googleapis.com/",
                        "parameters": [
                            {"name": "key", "value": "tmp/1/bulk/test/products.jsonl"},
                            {"name": "policy", "value": "signed-policy"},
                        ],
                    }
                ],
            }
        }
    )


def accepted():
    return graphql_response(
        {
            "bulkOperationRunMutation": {
                "userErrors": [],
                "bulkOperation": {
                    "id": BULK_ID,
                    "status": "CREATED",
                    "type": "MUTATION",
                },
            }
        }
    )


def invoke(http, inputs, *, name="create_products_bulk", **kwargs):
    payload = connection_payload(
        name, inputs, runtime_context={"external_effect_id": EXTERNAL_EFFECT_ID}
    )
    return handle_runtime(
        payload, transport_factory=lambda conn: ShopifyGraphQLTransport(conn, opener=http), **kwargs
    )


def test_bulk_uploads_one_jsonl_file_and_returns_submission_not_created_products(http):
    storage = FakeHttp()
    storage.queue(FakeResponse(201, b""))
    http.queue(staged(), accepted())
    result = invoke(http, {"products": PRODUCTS}, storage_opener=storage)
    assert result["ok"] is True
    assert result["result"]["bulk_operation"]["id"] == BULK_ID
    assert result["result"]["bulk_operation"]["status"] == "CREATED"
    assert result["result"]["item_count"] == 1
    assert "products" not in result["result"]
    assert len(http.requests) == 2 and len(storage.requests) == 1
    body = storage.last["body"]
    assert b'"status":"DRAFT"' in body and b'"handle":"boots"' in body
    assert b'"descriptionHtml":"<p>Warm</p>"' in body
    assert b"shpat_" not in body and "x-shopify-access-token" not in storage.last["headers"]
    assert http.variables(1)["path"] == "tmp/1/bulk/test/products.jsonl"
    assert http.variables(1)["clientIdentifier"] == "fs-product-create:" + EXTERNAL_EFFECT_ID


@pytest.mark.parametrize(
    "inputs",
    [
        {},
        {"products": []},
        {"products": PRODUCTS, "artifact_handle": "artifact:x"},
        {"products": [{"title": "No handle"}]},
        {"products": PRODUCTS * 2},
        {"products": [{"title": "X", "handle": "x", "status": "ACTIVE"}]},
    ],
)
def test_invalid_batches_fail_before_shopify_io(http, inputs):
    result = invoke(http, inputs)
    assert result["ok"] is False
    assert result["error_code"] == "invalid_payload"
    assert not http.requests


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_jsonl_preserves_unicode_inside_descriptions(http, separator):
    import json

    storage = FakeHttp()
    storage.queue(FakeResponse(201, b""))
    http.queue(staged(), accepted())
    source = (
        json.dumps(
            {"title": "Boots", "handle": "boots", "description_html": "A" + separator + "B"},
            ensure_ascii=False,
        ).encode()
        + b"\n"
    )
    result = invoke(
        http,
        {"artifact_handle": "artifact:input"},
        storage_opener=storage,
        artifact_reader=lambda payload, **kwargs: source,
    )
    assert result["ok"] is True
    assert ("A" + separator + "B").encode() in storage.last["body"]


def test_artifact_rehearsal_suppresses_before_storage_read_or_connection(http):
    def forbidden(*args, **kwargs):
        raise AssertionError("Rehearsal attempted I/O")

    payload = connection_payload(
        "create_products_bulk",
        {"artifact_handle": "artifact:input"},
        runtime_context={"test_mode": True},
    )
    result = handle_runtime(
        payload, artifact_reader=forbidden, storage_opener=forbidden, transport_factory=forbidden
    )
    assert result["external_effect_status"] == "suppressed"
    assert result["definitely_no_external_effect"] is True


def test_missing_effect_id_rejects_before_artifact_read(http):
    calls = []
    payload = connection_payload("create_products_bulk", {"artifact_handle": "artifact:input"})
    result = handle_runtime(payload, artifact_reader=lambda *args, **kwargs: calls.append(True))
    assert result["error_code"] == "missing_idempotency_key"
    assert calls == []


def test_submission_timeout_is_unknown_and_is_never_retried(http):
    storage = FakeHttp()
    storage.queue(FakeResponse(201, b""))
    http.queue(staged(), TimeoutError("test"))
    result = invoke(http, {"products": PRODUCTS}, storage_opener=storage)
    assert result["error_code"] == "timeout_unknown"
    assert result["retryable"] is False
    assert result["definitely_no_external_effect"] is False
    assert result["external_effect_status"] == "timeout_unknown"
    assert len(http.requests) == 2


def test_five_thousand_products_use_one_submission(http):
    storage = FakeHttp()
    storage.queue(FakeResponse(201, b""))
    http.queue(staged(), accepted())
    products = [{"title": f"Product {i}", "handle": f"product-{i}"} for i in range(5000)]
    result = invoke(http, {"products": products}, storage_opener=storage)
    assert result["result"]["item_count"] == 5000
    assert storage.last["body"].count(b'"status":"DRAFT"') == 5000
    assert len(http.requests) == 2


@pytest.mark.parametrize(
    "url",
    [
        "http://shopify-staged-uploads.storage.googleapis.com/",
        "https://example.com/upload",
        "https://shopify-staged-uploads.storage.googleapis.com@localhost/",
    ],
)
def test_unexpected_staged_url_is_rejected_before_upload(http, url):
    response = staged()
    import json

    data = json.loads(response._buffer)
    data["data"]["stagedUploadsCreate"]["stagedTargets"][0]["url"] = url
    http.queue(FakeResponse(200, json.dumps(data).encode()))
    storage = FakeHttp()
    result = invoke(http, {"products": PRODUCTS}, storage_opener=storage)
    assert result["ok"] is False
    assert storage.requests == [] and len(http.requests) == 1


@pytest.mark.parametrize(
    "node", [None, {"id": "gid://shopify/Product/1", "status": "CREATED", "type": "MUTATION"}]
)
def test_missing_submission_identity_is_unknown_not_safe_to_retry(http, node):
    storage = FakeHttp()
    storage.queue(FakeResponse(201, b""))
    http.queue(
        staged(),
        graphql_response({"bulkOperationRunMutation": {"userErrors": [], "bulkOperation": node}}),
    )
    result = invoke(http, {"products": PRODUCTS}, storage_opener=storage)
    assert result["error_code"] == "timeout_unknown"
    assert result["retryable"] is False
    assert result["definitely_no_external_effect"] is False
    assert result["external_effect_status"] == "timeout_unknown"
