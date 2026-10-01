"""Optional export data is complete and distinguishable from unrequested data."""

from __future__ import annotations

import json

import pytest
from conftest import FakeHttp, connection, connection_payload, graphql_response, product_node
from runtime.catalog_export import export_products
from runtime.errors import ExtensionError
from runtime.transport import ShopifyGraphQLTransport

PRODUCT = "gid://shopify/Product/3001"
ITEM = "gid://shopify/InventoryItem/1001"


def export(http, **options):
    captured = {}

    def writer(payload, chunks, **kwargs):
        body = b"".join(chunks)
        captured["rows"] = [json.loads(line) for line in body.splitlines()]
        return {"artifact_handle": "artifact:export", "size_bytes": len(body), "sha256": "a" * 64}

    raw = {"connection_ref": "conn-1", **options}
    export_products(
        connection_payload("export_products", options),
        raw,
        transport_factory=lambda conn: ShopifyGraphQLTransport(conn, opener=http),
        artifact_writer=writer,
    )
    return captured["rows"]


def base(http):
    http.queue(graphql_response({"products": connection([product_node()])}))


def parents(http, field, rows, *, parent=PRODUCT, has_next=False, cursor="end"):
    http.queue(
        graphql_response(
            {"nodes": [{"id": parent, field: connection(rows, has_next=has_next, cursor=cursor)}]}
        )
    )


def test_images_include_all_pages_and_keep_processing_image(http: FakeHttp):
    base(http)
    parents(
        http,
        "media",
        [{"id": "image-1", "alt": "Front", "image": {"url": "https://cdn.example/front.jpg"}}],
        has_next=True,
        cursor="next",
    )
    parents(http, "media", [{"id": "image-2", "alt": "Back", "image": None}])
    row = export(http, include_images=True)[0]
    assert row["image_count"] == 2
    assert row["images"] == [
        {"id": "image-1", "alt": "Front", "url": "https://cdn.example/front.jpg"},
        {"id": "image-2", "alt": "Back", "url": None},
    ]
    assert http.variables(2)["after"] == "next"
    assert "variants" not in row


@pytest.mark.parametrize(
    "options,expected",
    [({}, False), ({"include_images": False}, False), ({"include_images": True}, True)],
)
def test_unrequested_images_are_distinct_from_no_images(http, options, expected):
    base(http)
    if expected:
        parents(http, "media", [])
    row = export(http, **options)[0]
    assert ("images" in row) == expected
    assert ("image_count" in row) == expected
    if expected:
        assert row["images"] == [] and row["image_count"] == 0
    assert len(http.requests) == (2 if expected else 1)


def test_inventory_implies_variants_and_reads_all_locations(http):
    base(http)
    parents(
        http,
        "variants",
        [
            {
                "id": "variant-1",
                "sku": "SKU-1",
                "price": "19.99",
                "compareAtPrice": None,
                "selectedOptions": [{"name": "Size", "value": "M"}],
                "inventoryItem": {"id": ITEM, "tracked": True},
            }
        ],
    )
    parents(
        http,
        "inventoryLevels",
        [
            {
                "id": "level-1",
                "location": {"id": "loc-1", "name": "Main"},
                "quantities": [{"name": "available", "quantity": 0}],
            }
        ],
        parent=ITEM,
        has_next=True,
        cursor="loc-next",
    )
    parents(
        http,
        "inventoryLevels",
        [
            {
                "id": "level-2",
                "location": {"id": "loc-2", "name": "Other"},
                "quantities": [{"name": "available", "quantity": 7}],
            }
        ],
        parent=ITEM,
    )
    variant = export(http, include_inventory=True, include_variants=False)[0]["variants"][0]
    assert variant["sku"] == "SKU-1" and variant["price"] == "19.99"
    assert variant["selected_options"] == [{"name": "Size", "value": "M"}]
    assert variant["inventory_item"]["tracked"] is True
    assert [x["quantities"]["available"] for x in variant["inventory_item"]["levels"]] == [0, 7]
    assert http.variables(3)["after"] == "loc-next"


def test_variants_paginate_without_fetching_inventory(http):
    base(http)
    parents(
        http,
        "variants",
        [{"id": "v1", "sku": "A", "price": "1.00"}],
        has_next=True,
        cursor="v-next",
    )
    parents(http, "variants", [{"id": "v2", "sku": "B", "price": "2.00"}])
    variants = export(http, include_variants=True)[0]["variants"]
    assert [v["sku"] for v in variants] == ["A", "B"]
    assert all("inventory_item" not in v for v in variants)
    assert len(http.requests) == 3


@pytest.mark.parametrize("option", ["include_images", "include_variants", "include_inventory"])
def test_include_flags_reject_strings_before_io(http, option):
    with pytest.raises(ExtensionError):
        export(http, **{option: "true"})
    assert not http.requests


@pytest.mark.parametrize("failure", ["missing_parent", "missing_connection", "cycle"])
def test_incomplete_related_data_fails_instead_of_looking_empty(http, failure):
    base(http)
    if failure == "missing_parent":
        http.queue(graphql_response({"nodes": [None]}))
    elif failure == "missing_connection":
        http.queue(graphql_response({"nodes": [{"id": PRODUCT}]}))
    else:
        parents(http, "media", [], has_next=True, cursor="loop")
        parents(http, "media", [], has_next=True, cursor="loop")
    with pytest.raises(ExtensionError) as exc:
        export(http, include_images=True)
    assert exc.value.code == "upstream_failure"


def test_throttled_detail_read_retries_same_cursor(http, monkeypatch):
    from runtime import export_details

    waits = []
    monkeypatch.setattr(export_details, "sleep", waits.append, raising=False)
    base(http)
    http.queue(
        graphql_response({}, errors=[{"message": "Throttled", "extensions": {"code": "THROTTLED"}}])
    )
    parents(http, "media", [])
    assert export(http, include_images=True)[0]["image_count"] == 0
    assert waits == [1.0]
    assert http.variables(1) == http.variables(2)


def test_related_batches_keep_independent_cursors_and_more_than_250_images(http):
    products = [product_node(f"gid://shopify/Product/{3001 + i}") for i in range(6)]
    http.queue(graphql_response({"products": connection(products)}))
    http.queue(
        graphql_response(
            {
                "nodes": [
                    {"id": p["id"], "media": connection([], has_next=i < 2, cursor=f"cursor-{i}")}
                    for i, p in enumerate(products[:5])
                ]
            }
        )
    )
    parents(http, "media", [{"id": "second", "image": None}], parent=products[1]["id"])
    for page in range(6):
        count = 50 if page < 5 else 1
        parents(
            http,
            "media",
            [{"id": f"image-{page}-{i}", "image": None} for i in range(count)],
            parent=products[0]["id"],
            has_next=page < 5,
            cursor=f"page-{page}",
        )
    parents(http, "media", [], parent=products[5]["id"])
    rows = export(http, include_images=True)
    assert [r["image_count"] for r in rows] == [251, 1, 0, 0, 0, 0]
    assert http.variables(1)["ids"] == [p["id"] for p in products[:5]]
    assert http.variables(2)["after"] == "cursor-1"
    assert http.variables(3)["after"] == "cursor-0"
    assert http.variables(9)["ids"] == [products[5]["id"]]


@pytest.mark.parametrize("code,retries", [("THROTTLED", 6), ("ACCESS_DENIED", 1)])
def test_export_read_retries_are_bounded_and_do_not_hide_denials(http, monkeypatch, code, retries):
    from runtime import export_details

    waits = []
    monkeypatch.setattr(export_details, "sleep", waits.append)
    base(http)
    for _ in range(retries):
        http.queue(graphql_response({}, errors=[{"extensions": {"code": code}}]))
    with pytest.raises(ExtensionError) as exc:
        export(http, include_images=True)
    assert exc.value.code == ("rate_limited" if code == "THROTTLED" else "authorization_failed")
    assert len(http.requests) == 1 + retries
    assert len(waits) == retries - 1


@pytest.mark.parametrize("images", [False, True])
@pytest.mark.parametrize("variants", [False, True])
@pytest.mark.parametrize("inventory", [False, True])
def test_option_combinations_preserve_absence_and_empty_lists(http, images, variants, inventory):
    base(http)
    if images:
        parents(http, "media", [])
    if variants or inventory:
        parents(http, "variants", [])
    row = export(
        http, include_images=images, include_variants=variants, include_inventory=inventory
    )[0]
    assert ("images" in row) == images
    assert ("image_count" in row) == images
    assert ("variants" in row) == (variants or inventory)
    if variants or inventory:
        assert row["variants"] == []
