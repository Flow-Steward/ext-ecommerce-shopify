"""Complete Shopify catalog export owns cursors and streams one artifact."""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import FakeHttp, connection, connection_payload, graphql_response, product_node
from runtime import errors
from runtime.errors import ExtensionError
from runtime.transport import ShopifyGraphQLTransport


def test_export_follows_every_cursor_and_streams_jsonl(http: FakeHttp) -> None:
    from runtime.catalog_export import export_products

    http.queue(
        graphql_response(
            {
                "products": connection(
                    [product_node()],
                    has_next=True,
                    cursor="cursor-1",
                )
            }
        ),
        graphql_response(
            {
                "products": connection(
                    [product_node("gid://shopify/Product/3002", handle="boots-2")],
                    has_next=False,
                    cursor="cursor-2",
                )
            }
        ),
    )
    captured: dict[str, Any] = {}

    def artifact_writer(payload, chunks, **kwargs):
        captured["payload"] = payload
        captured["body"] = b"".join(chunks)
        captured["kwargs"] = kwargs
        return {
            "artifact_handle": "artifact:art_shopify_catalog",
            "size_bytes": len(captured["body"]),
            "sha256": "a" * 64,
        }

    result = export_products(
        connection_payload(
            "export_products",
            {"first": 1, "filter": "status:active"},
        ),
        {"connection_ref": "conn-1", "first": 1, "filter": "status:active"},
        transport_factory=lambda shopify_connection: ShopifyGraphQLTransport(
            shopify_connection, opener=http
        ),
        artifact_writer=artifact_writer,
    )

    assert len(http.requests) == 2
    assert http.variables(0) == {"first": 1, "after": None, "query": "status:active"}
    assert http.variables(1) == {
        "first": 1,
        "after": "cursor-1",
        "query": "status:active",
    }
    records = [json.loads(line) for line in captured["body"].splitlines()]
    assert [record["id"] for record in records] == [
        "gid://shopify/Product/3001",
        "gid://shopify/Product/3002",
    ]
    assert result["item_count"] == 2
    assert result["page_count"] == 2
    assert result["artifact_handle"] == "artifact:art_shopify_catalog"
    assert result["artifacts"]["shopify-products.jsonl"]["sha256"] == "a" * 64


def test_export_refuses_a_partial_start_before_network(http: FakeHttp) -> None:
    from runtime.catalog_export import export_products

    payload = connection_payload("export_products", {"after": "cursor-1"})
    config = {"connection_ref": "conn-1", "after": "cursor-1"}
    with pytest.raises(ExtensionError) as raised:
        export_products(
            payload,
            config,
            transport_factory=lambda _connection: http,
        )

    assert raised.value.code == errors.INVALID_PAYLOAD
    assert http.requests == []


def test_export_rejects_missing_artifact_receipt(http: FakeHttp) -> None:
    from runtime.catalog_export import export_products

    http.queue(graphql_response({"products": connection([])}))
    payload = connection_payload("export_products", {})
    config = {"connection_ref": "conn-1"}

    with pytest.raises(ExtensionError) as raised:
        export_products(
            payload,
            config,
            transport_factory=lambda shopify_connection: ShopifyGraphQLTransport(
                shopify_connection, opener=http
            ),
            artifact_writer=lambda *_args, **_kwargs: {},
        )

    assert raised.value.code == errors.ARTIFACT_OUTPUT_UNAVAILABLE
