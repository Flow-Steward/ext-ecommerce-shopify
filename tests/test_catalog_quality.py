"""export_products can return only the products whose catalog data needs attention."""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import FakeHttp, connection, connection_payload, graphql_response, product_node

from runtime import catalog_quality
from runtime.catalog import SHOPIFY_RECOMMENDED_IMAGE_SIZE
from runtime.catalog_export import export_products
from runtime.transport import ShopifyGraphQLTransport

PRODUCT_A = "gid://shopify/Product/3001"
PRODUCT_B = "gid://shopify/Product/3002"


def _export(http: FakeHttp, quality: dict[str, Any], **options: Any) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def writer(payload, chunks, **kwargs):
        body = b"".join(chunks)
        captured["rows"] = [json.loads(line) for line in body.splitlines()]
        return {"artifact_handle": "artifact:export", "size_bytes": len(body), "sha256": "a" * 64}

    raw = {"connection_ref": "conn-1", "quality_filter": quality, **options}
    result = export_products(
        connection_payload("export_products", raw),
        raw,
        transport_factory=lambda conn: ShopifyGraphQLTransport(conn, opener=http),
        artifact_writer=writer,
    )
    return {**result, "rows": captured["rows"]}


def _images(http: FakeHttp, by_product: dict[str, list[dict[str, Any]]]) -> None:
    http.queue(
        graphql_response(
            {
                "nodes": [
                    {"id": product_id, "media": connection(rows)}
                    for product_id, rows in by_product.items()
                ]
            }
        )
    )


def _image(width: int | None, height: int | None, alt: str | None = "Front") -> dict[str, Any]:
    return {"id": "gid://shopify/MediaImage/1", "alt": alt, "image": {
        "url": "https://cdn.example/a.jpg", "width": width, "height": height}}  # fmt: skip


def test_only_products_with_images_below_shopifys_recommendation_are_exported(http) -> None:
    http.queue(
        graphql_response({"products": connection([product_node(), product_node(PRODUCT_B)])})
    )
    _images(
        http,
        {
            PRODUCT_A: [_image(800, 800)],
            PRODUCT_B: [_image(SHOPIFY_RECOMMENDED_IMAGE_SIZE, SHOPIFY_RECOMMENDED_IMAGE_SIZE)],
        },
    )

    result = _export(http, {"below_recommended_image_size": True})

    assert [row["id"] for row in result["rows"]] == [PRODUCT_A]
    assert result["rows"][0]["quality_issues"] == ["image_too_small"]
    assert result["rows"][0]["images"][0]["width"] == 800
    assert result["item_count"] == 1
    assert result["scanned_count"] == 2


def test_a_custom_minimum_size_is_respected(http) -> None:
    http.queue(
        graphql_response({"products": connection([product_node(), product_node(PRODUCT_B)])})
    )
    _images(http, {PRODUCT_A: [_image(1024, 1024)], PRODUCT_B: [_image(511, 2000)]})

    result = _export(http, {"min_image_width": 512, "min_image_height": 512})

    assert [row["id"] for row in result["rows"]] == [PRODUCT_B]


def test_products_without_images_are_found(http) -> None:
    http.queue(
        graphql_response({"products": connection([product_node(), product_node(PRODUCT_B)])})
    )
    _images(http, {PRODUCT_A: [], PRODUCT_B: [_image(4000, 4000)]})

    result = _export(http, {"missing_images": True})

    assert [row["id"] for row in result["rows"]] == [PRODUCT_A]
    assert result["rows"][0]["quality_issues"] == ["missing_images"]


def test_images_without_alt_text_are_found(http) -> None:
    http.queue(graphql_response({"products": connection([product_node()])}))
    _images(http, {PRODUCT_A: [_image(4000, 4000, alt="")]})

    result = _export(http, {"missing_image_alt_text": True})

    assert result["rows"][0]["quality_issues"] == ["image_missing_alt_text"]


def test_short_and_empty_descriptions_are_found_by_plain_text_length(http) -> None:
    http.queue(
        graphql_response(
            {
                "products": connection(
                    [
                        product_node(descriptionHtml="<p><strong>Boots</strong>&nbsp;</p>"),
                        product_node(PRODUCT_B, descriptionHtml="<p>" + "x" * 300 + "</p>"),
                        product_node("gid://shopify/Product/3003", descriptionHtml=""),
                    ]
                )
            }
        )
    )

    result = _export(http, {"min_description_length": 100, "missing_description": True})

    assert [(row["id"], row["quality_issues"]) for row in result["rows"]] == [
        (PRODUCT_A, ["description_too_short"]),
        ("gid://shopify/Product/3003", ["missing_description"]),
    ]


def test_empty_product_and_variant_fields_are_found(http) -> None:
    http.queue(
        graphql_response({"products": connection([product_node(vendor="", seo={"title": None})])})
    )
    http.queue(
        graphql_response(
            {
                "nodes": [
                    {
                        "id": PRODUCT_A,
                        "variants": connection(
                            [{"id": "v1", "sku": "", "barcode": "1", "price": "0.00"}]
                        ),
                    }
                ]
            }
        )
    )

    result = _export(
        http, {"missing_fields": ["vendor", "seo_title", "sku", "barcode", "price", "weight"]}
    )

    assert result["rows"][0]["quality_issues"] == [
        "missing_vendor",
        "missing_seo_title",
        "missing_sku",
        "missing_price",
        "missing_weight",
    ]


def test_match_all_needs_every_checked_problem(http) -> None:
    http.queue(
        graphql_response({"products": connection([product_node(), product_node(PRODUCT_B)])})
    )
    _images(http, {PRODUCT_A: [], PRODUCT_B: [_image(4000, 4000)]})

    result = _export(http, {"match": "all", "missing_images": True, "missing_fields": ["vendor"]})

    assert result["rows"] == []
    assert result["scanned_count"] == 2


def test_without_a_quality_filter_nothing_is_filtered_or_annotated(http) -> None:
    http.queue(graphql_response({"products": connection([product_node()])}))
    captured: dict[str, Any] = {}

    def writer(payload, chunks, **kwargs):
        body = b"".join(chunks)
        captured["rows"] = [json.loads(line) for line in body.splitlines()]
        return {"artifact_handle": "artifact:export", "size_bytes": len(body), "sha256": "a" * 64}

    export_products(
        connection_payload("export_products", {}),
        {"connection_ref": "conn-1"},
        transport_factory=lambda conn: ShopifyGraphQLTransport(conn, opener=http),
        artifact_writer=writer,
    )

    assert "quality_issues" not in captured["rows"][0]
    assert len(http.requests) == 1


@pytest.mark.parametrize(
    ("html", "length"),
    [("", 0), (None, 0), ("<p>a  b</p>", 3), ("<br/>&amp;", 1), ("<p>\n x \n</p>", 1)],
)
def test_plain_text_length(html: Any, length: int) -> None:
    assert catalog_quality.plain_text_length(html) == length


def test_a_quality_filter_with_an_unknown_check_is_refused(http) -> None:
    from runtime.errors import ExtensionError

    with pytest.raises(ExtensionError):
        _export(http, {"missing_fields": ["colour"]})
    assert http.requests == []
