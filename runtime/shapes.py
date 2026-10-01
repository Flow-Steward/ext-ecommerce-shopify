"""Turn one Shopify node into the fixed record this extension publishes.

Every shaper here is total: it returns the complete declared shape whatever
Shopify sent, filling absent values with ``None`` rather than dropping keys. A
workflow binds to a field name, so a key that appears only when the store
happened to populate it is a binding that breaks on the second order.

Nothing is copied through wholesale. A field reaches a result only because a
function below names it, which is what keeps a customer email or a billing
address out of an order result even if a future document accidentally asked for
one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: A page of nested records is bounded by the page size the caller asked for.
#: This is the ceiling for a sub-selection nobody paginates.
MAX_NESTED_ITEMS = 250


# -- Primitives ------------------------------------------------------------


def text(value: Any) -> str:
    """One string, returned whole.

    Nothing here clips. A product description may legitimately be 65 535
    characters and a metafield value half a mebibyte, and an earlier cut capped
    every string at 8 192 — so a caller reading a result back saw a
    complete-looking record whose description had been cut mid-word, with
    nothing in the response to say so. Size is bounded once, at the transport,
    where exceeding the limit is an error rather than a silent edit.
    """
    return value if isinstance(value, str) else ""


def optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def nodes(connection: Any, *, limit: int = MAX_NESTED_ITEMS) -> list[Mapping[str, Any]]:
    """The ``nodes`` of one GraphQL connection, bounded and free of non-objects."""
    found = mapping(connection).get("nodes")
    if not isinstance(found, list):
        return []
    return [node for node in found[:limit] if isinstance(node, Mapping)]


def page_info(value: Any) -> dict[str, Any]:
    info = mapping(value)
    return {
        "has_next_page": bool(info.get("hasNextPage", False)),
        "end_cursor": optional_text(info.get("endCursor")),
    }


def nested_id(value: Any) -> str | None:
    """The ``id`` of a nested object, or ``None`` when Shopify sent no object."""
    return optional_text(mapping(value).get("id"))


def string_list(value: Any, *, limit: int = MAX_NESTED_ITEMS) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value[:limit] if isinstance(item, str)]


def money(value: Any) -> dict[str, Any] | None:
    """One ``MoneyBag``'s shop money, kept as the decimal string Shopify sent."""
    shop_money = mapping(mapping(value).get("shopMoney"))
    if not shop_money:
        return None
    return {
        "amount": optional_text(shop_money.get("amount")),
        "currency_code": optional_text(shop_money.get("currencyCode")),
    }


# -- Catalog ---------------------------------------------------------------


def product(node: Any) -> dict[str, Any]:
    record = mapping(node)
    seo = mapping(record.get("seo"))
    return {
        "id": text(record.get("id")),
        "title": optional_text(record.get("title")),
        "handle": optional_text(record.get("handle")),
        "description_html": optional_text(record.get("descriptionHtml")),
        "vendor": optional_text(record.get("vendor")),
        "product_type": optional_text(record.get("productType")),
        "status": optional_text(record.get("status")),
        "tags": string_list(record.get("tags")),
        "category_id": nested_id(record.get("category")),
        "seo": (
            None
            if not seo
            else {
                "title": optional_text(seo.get("title")),
                "description": optional_text(seo.get("description")),
            }
        ),
        "created_at": optional_text(record.get("createdAt")),
        "updated_at": optional_text(record.get("updatedAt")),
        "options": [
            {
                "id": text(option.get("id")),
                "name": optional_text(option.get("name")),
                "position": optional_int(option.get("position")),
            }
            for option in _objects(record.get("options"))
        ],
    }


def product_variant(node: Any) -> dict[str, Any]:
    record = mapping(node)
    item = mapping(record.get("inventoryItem"))
    return {
        "id": text(record.get("id")),
        "product_id": nested_id(record.get("product")),
        "title": optional_text(record.get("title")),
        "barcode": optional_text(record.get("barcode")),
        "price": optional_text(record.get("price")),
        "compare_at_price": optional_text(record.get("compareAtPrice")),
        "inventory_policy": optional_text(record.get("inventoryPolicy")),
        "taxable": optional_bool(record.get("taxable")),
        "created_at": optional_text(record.get("createdAt")),
        "updated_at": optional_text(record.get("updatedAt")),
        "selected_options": [
            {"name": optional_text(option.get("name")), "value": optional_text(option.get("value"))}
            for option in _objects(record.get("selectedOptions"))
        ],
        "inventory_item": (
            None
            if not item
            else {
                "id": optional_text(item.get("id")),
                "sku": optional_text(item.get("sku")),
                "tracked": optional_bool(item.get("tracked")),
                "requires_shipping": optional_bool(item.get("requiresShipping")),
            }
        ),
    }


def metafield(node: Any, *, owner_id: str | None) -> dict[str, Any]:
    """One metafield. ``owner_id`` is supplied by the caller of the shaper.

    A metafield's owner is not read back out of the response: for a list it is
    the record that was queried, and for a set it is the tuple the entry was
    correlated by. Either way it is already known, and asking Shopify for it
    again would only add a way for the two to disagree.
    """
    record = mapping(node)
    return {
        "id": text(record.get("id")),
        "owner_id": owner_id,
        "namespace": optional_text(record.get("namespace")),
        "key": optional_text(record.get("key")),
        "type": optional_text(record.get("type")),
        "value": optional_text(record.get("value")),
        "compare_digest": optional_text(record.get("compareDigest")),
        "created_at": optional_text(record.get("createdAt")),
        "updated_at": optional_text(record.get("updatedAt")),
    }


def product_media(node: Any) -> dict[str, Any]:
    record = mapping(node)
    preview = mapping(record.get("preview"))
    image = mapping(preview.get("image"))
    return {
        "id": text(record.get("id")),
        "media_content_type": optional_text(record.get("mediaContentType")),
        "alt": optional_text(record.get("alt")),
        "status": optional_text(record.get("status")),
        "preview": (
            None
            if not preview
            else {
                "status": optional_text(preview.get("status")),
                "width": optional_int(image.get("width")),
                "height": optional_int(image.get("height")),
            }
        ),
    }


def media_file(node: Any) -> dict[str, Any]:
    record = mapping(node)
    return {
        "id": text(record.get("id")),
        "alt": optional_text(record.get("alt")),
        "file_status": optional_text(record.get("fileStatus")),
        "created_at": optional_text(record.get("createdAt")),
        "updated_at": optional_text(record.get("updatedAt")),
    }


# -- Orders ----------------------------------------------------------------


def _custom_attributes(value: Any) -> list[dict[str, Any]]:
    return [
        {"key": optional_text(entry.get("key")), "value": optional_text(entry.get("value"))}
        for entry in _objects(value)
    ]


def order(node: Any) -> dict[str, Any]:
    record = mapping(node)
    return {
        "id": text(record.get("id")),
        "name": optional_text(record.get("name")),
        "created_at": optional_text(record.get("createdAt")),
        "updated_at": optional_text(record.get("updatedAt")),
        "processed_at": optional_text(record.get("processedAt")),
        "cancelled_at": optional_text(record.get("cancelledAt")),
        "closed_at": optional_text(record.get("closedAt")),
        "display_financial_status": optional_text(record.get("displayFinancialStatus")),
        "display_fulfillment_status": optional_text(record.get("displayFulfillmentStatus")),
        "currency_code": optional_text(record.get("currencyCode")),
        "tags": string_list(record.get("tags")),
        "note": optional_text(record.get("note")),
        "po_number": optional_text(record.get("poNumber")),
        "custom_attributes": _custom_attributes(record.get("customAttributes")),
        "total_price": money(record.get("totalPriceSet")),
        "subtotal_price": money(record.get("subtotalPriceSet")),
        "total_tax": money(record.get("totalTaxSet")),
        "total_shipping_price": money(record.get("totalShippingPriceSet")),
        "total_discounts": money(record.get("totalDiscountsSet")),
    }


def order_metadata(node: Any) -> dict[str, Any]:
    record = mapping(node)
    return {
        "id": text(record.get("id")),
        "name": optional_text(record.get("name")),
        "updated_at": optional_text(record.get("updatedAt")),
        "tags": string_list(record.get("tags")),
        "note": optional_text(record.get("note")),
        "po_number": optional_text(record.get("poNumber")),
        "custom_attributes": _custom_attributes(record.get("customAttributes")),
    }


def order_line_item(node: Any) -> dict[str, Any]:
    record = mapping(node)
    return {
        "id": text(record.get("id")),
        "product_id": nested_id(record.get("product")),
        "variant_id": nested_id(record.get("variant")),
        "title": optional_text(record.get("title")),
        "name": optional_text(record.get("name")),
        "sku": optional_text(record.get("sku")),
        "quantity": optional_int(record.get("quantity")),
        "current_quantity": optional_int(record.get("currentQuantity")),
        "refundable_quantity": optional_int(record.get("refundableQuantity")),
        "unfulfilled_quantity": optional_int(record.get("unfulfilledQuantity")),
        "requires_shipping": optional_bool(record.get("requiresShipping")),
        "original_unit_price": money(record.get("originalUnitPriceSet")),
        "discounted_unit_price": money(record.get("discountedUnitPriceSet")),
        "original_total": money(record.get("originalTotalSet")),
        "discounted_total": money(record.get("discountedTotalSet")),
    }


def fulfillment_order(node: Any) -> dict[str, Any]:
    record = mapping(node)
    assigned = mapping(record.get("assignedLocation"))
    line_items = record.get("lineItems")
    return {
        "id": text(record.get("id")),
        "status": optional_text(record.get("status")),
        "request_status": optional_text(record.get("requestStatus")),
        "assigned_location_id": nested_id(assigned.get("location")),
        "assigned_location_name": optional_text(assigned.get("name")),
        "created_at": optional_text(record.get("createdAt")),
        "updated_at": optional_text(record.get("updatedAt")),
        "line_items": [
            {
                "id": text(item.get("id")),
                "line_item_id": nested_id(item.get("lineItem")),
                "total_quantity": optional_int(item.get("totalQuantity")),
                "remaining_quantity": optional_int(item.get("remainingQuantity")),
            }
            for item in nodes(line_items)
        ],
        "line_items_page_info": page_info(mapping(line_items).get("pageInfo")),
    }


def fulfillment(node: Any) -> dict[str, Any]:
    record = mapping(node)
    return {
        "id": text(record.get("id")),
        "status": optional_text(record.get("status")),
        "created_at": optional_text(record.get("createdAt")),
        "updated_at": optional_text(record.get("updatedAt")),
        "tracking_info": [
            {
                "company": optional_text(entry.get("company")),
                "number": optional_text(entry.get("number")),
                "url": optional_text(entry.get("url")),
            }
            for entry in _objects(record.get("trackingInfo"))
        ],
    }


def _objects(value: Any, *, limit: int = MAX_NESTED_ITEMS) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [entry for entry in value[:limit] if isinstance(entry, Mapping)]


__all__ = [
    "MAX_NESTED_ITEMS",
    "fulfillment",
    "fulfillment_order",
    "mapping",
    "media_file",
    "metafield",
    "money",
    "nested_id",
    "nodes",
    "optional_bool",
    "optional_int",
    "optional_text",
    "order",
    "order_line_item",
    "order_metadata",
    "page_info",
    "product",
    "product_media",
    "product_variant",
    "string_list",
    "text",
]
