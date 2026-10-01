"""The record shapes this extension publishes, written once and shared.

Every operation returns a fixed, closed selection. These are the schemas the
manifest publishes and the schemas the runtime is checked against, so a field
cannot appear in a result without appearing here first.

What is deliberately absent matters as much as what is present. No order shape
carries a customer, an email address, a phone number, a billing or shipping
address, a payment method, a transaction or an IP address — those are neither
queried nor shaped, so a workflow cannot move them out of the shop by accident.
Free-text fields that remain (notes, custom attributes, tags, metafield values,
tracking numbers) can still hold whatever a merchant typed, which is why no
result, input or variable set is ever logged whole.
"""

from __future__ import annotations

from typing import Any


def _obj(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _nullable_obj(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": ["object", "null"],
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


TEXT: dict[str, Any] = {"type": "string"}
OPTIONAL_TEXT: dict[str, Any] = {"type": ["string", "null"]}
OPTIONAL_BOOL: dict[str, Any] = {"type": ["boolean", "null"]}
OPTIONAL_INT: dict[str, Any] = {"type": ["integer", "null"]}

PAGE_INFO: dict[str, Any] = _obj(
    ["has_next_page", "end_cursor"],
    {"has_next_page": {"type": "boolean"}, "end_cursor": OPTIONAL_TEXT},
)

#: Money is carried as the decimal string Shopify sends. Parsing it into a
#: binary float here would silently round a price the merchant set.
MONEY: dict[str, Any] = _nullable_obj(
    ["amount", "currency_code"], {"amount": OPTIONAL_TEXT, "currency_code": OPTIONAL_TEXT}
)

SEO: dict[str, Any] = _nullable_obj(
    ["title", "description"], {"title": OPTIONAL_TEXT, "description": OPTIONAL_TEXT}
)

PRODUCT_OPTION: dict[str, Any] = _obj(
    ["id", "name", "position"],
    {"id": TEXT, "name": OPTIONAL_TEXT, "position": OPTIONAL_INT},
)

PRODUCT: dict[str, Any] = _obj(
    [
        "id",
        "title",
        "handle",
        "description_html",
        "vendor",
        "product_type",
        "status",
        "tags",
        "category_id",
        "seo",
        "created_at",
        "updated_at",
        "options",
    ],
    {
        "id": TEXT,
        "title": OPTIONAL_TEXT,
        "handle": OPTIONAL_TEXT,
        "description_html": OPTIONAL_TEXT,
        "vendor": OPTIONAL_TEXT,
        "product_type": OPTIONAL_TEXT,
        "status": OPTIONAL_TEXT,
        "tags": {"type": "array", "items": TEXT},
        "category_id": OPTIONAL_TEXT,
        "seo": SEO,
        "created_at": OPTIONAL_TEXT,
        "updated_at": OPTIONAL_TEXT,
        "options": {"type": "array", "items": PRODUCT_OPTION},
    },
)

NULLABLE_PRODUCT: dict[str, Any] = {**PRODUCT, "type": ["object", "null"]}

SELECTED_OPTION: dict[str, Any] = _obj(
    ["name", "value"], {"name": OPTIONAL_TEXT, "value": OPTIONAL_TEXT}
)

VARIANT_INVENTORY_ITEM: dict[str, Any] = _nullable_obj(
    ["id", "sku", "tracked", "requires_shipping"],
    {
        "id": OPTIONAL_TEXT,
        "sku": OPTIONAL_TEXT,
        "tracked": OPTIONAL_BOOL,
        "requires_shipping": OPTIONAL_BOOL,
    },
)

PRODUCT_VARIANT: dict[str, Any] = _obj(
    [
        "id",
        "product_id",
        "title",
        "barcode",
        "price",
        "compare_at_price",
        "inventory_policy",
        "taxable",
        "created_at",
        "updated_at",
        "selected_options",
        "inventory_item",
    ],
    {
        "id": TEXT,
        "product_id": OPTIONAL_TEXT,
        "title": OPTIONAL_TEXT,
        "barcode": OPTIONAL_TEXT,
        "price": OPTIONAL_TEXT,
        "compare_at_price": OPTIONAL_TEXT,
        "inventory_policy": OPTIONAL_TEXT,
        "taxable": OPTIONAL_BOOL,
        "created_at": OPTIONAL_TEXT,
        "updated_at": OPTIONAL_TEXT,
        "selected_options": {"type": "array", "items": SELECTED_OPTION},
        "inventory_item": VARIANT_INVENTORY_ITEM,
    },
)

NULLABLE_PRODUCT_VARIANT: dict[str, Any] = {**PRODUCT_VARIANT, "type": ["object", "null"]}

# A successful productCreate result must carry enough identity for the next
# workflow steps to update the standalone variant and set its stock. General
# variant reads remain tolerant of a missing inventory item, but this one is a
# post-mutation confirmation contract and therefore requires both ids.
INITIAL_VARIANT_INVENTORY_ITEM: dict[str, Any] = _obj(
    ["id", "sku", "tracked", "requires_shipping"],
    {
        "id": TEXT,
        "sku": OPTIONAL_TEXT,
        "tracked": OPTIONAL_BOOL,
        "requires_shipping": OPTIONAL_BOOL,
    },
)

INITIAL_PRODUCT_VARIANT: dict[str, Any] = {
    **PRODUCT_VARIANT,
    "properties": {
        **PRODUCT_VARIANT["properties"],
        "product_id": TEXT,
        "inventory_item": INITIAL_VARIANT_INVENTORY_ITEM,
    },
}

METAFIELD: dict[str, Any] = _obj(
    [
        "id",
        "owner_id",
        "namespace",
        "key",
        "type",
        "value",
        "compare_digest",
        "created_at",
        "updated_at",
    ],
    {
        "id": TEXT,
        "owner_id": OPTIONAL_TEXT,
        "namespace": OPTIONAL_TEXT,
        "key": OPTIONAL_TEXT,
        "type": OPTIONAL_TEXT,
        "value": OPTIONAL_TEXT,
        "compare_digest": OPTIONAL_TEXT,
        "created_at": OPTIONAL_TEXT,
        "updated_at": OPTIONAL_TEXT,
    },
)

MEDIA_PREVIEW: dict[str, Any] = _nullable_obj(
    ["status", "width", "height"],
    {"status": OPTIONAL_TEXT, "width": OPTIONAL_INT, "height": OPTIONAL_INT},
)

PRODUCT_MEDIA: dict[str, Any] = _obj(
    ["id", "media_content_type", "alt", "status", "preview"],
    {
        "id": TEXT,
        "media_content_type": OPTIONAL_TEXT,
        "alt": OPTIONAL_TEXT,
        "status": OPTIONAL_TEXT,
        "preview": MEDIA_PREVIEW,
    },
)

MEDIA_FILE: dict[str, Any] = _obj(
    ["id", "alt", "file_status", "created_at", "updated_at"],
    {
        "id": TEXT,
        "alt": OPTIONAL_TEXT,
        "file_status": OPTIONAL_TEXT,
        "created_at": OPTIONAL_TEXT,
        "updated_at": OPTIONAL_TEXT,
    },
)

CUSTOM_ATTRIBUTE: dict[str, Any] = _obj(
    ["key", "value"], {"key": OPTIONAL_TEXT, "value": OPTIONAL_TEXT}
)

ORDER: dict[str, Any] = _obj(
    [
        "id",
        "name",
        "created_at",
        "updated_at",
        "processed_at",
        "cancelled_at",
        "closed_at",
        "display_financial_status",
        "display_fulfillment_status",
        "currency_code",
        "tags",
        "note",
        "po_number",
        "custom_attributes",
        "total_price",
        "subtotal_price",
        "total_tax",
        "total_shipping_price",
        "total_discounts",
    ],
    {
        "id": TEXT,
        "name": OPTIONAL_TEXT,
        "created_at": OPTIONAL_TEXT,
        "updated_at": OPTIONAL_TEXT,
        "processed_at": OPTIONAL_TEXT,
        "cancelled_at": OPTIONAL_TEXT,
        "closed_at": OPTIONAL_TEXT,
        "display_financial_status": OPTIONAL_TEXT,
        "display_fulfillment_status": OPTIONAL_TEXT,
        "currency_code": OPTIONAL_TEXT,
        "tags": {"type": "array", "items": TEXT},
        "note": OPTIONAL_TEXT,
        "po_number": OPTIONAL_TEXT,
        "custom_attributes": {"type": "array", "items": CUSTOM_ATTRIBUTE},
        "total_price": MONEY,
        "subtotal_price": MONEY,
        "total_tax": MONEY,
        "total_shipping_price": MONEY,
        "total_discounts": MONEY,
    },
)

NULLABLE_ORDER: dict[str, Any] = {**ORDER, "type": ["object", "null"]}

#: The subset of an order `update_order_metadata` confirms. The mutation may
#: only touch these fields, so echoing the whole order would suggest it had
#: looked at more than it changed.
ORDER_METADATA: dict[str, Any] = _obj(
    ["id", "name", "updated_at", "tags", "note", "po_number", "custom_attributes"],
    {
        "id": TEXT,
        "name": OPTIONAL_TEXT,
        "updated_at": OPTIONAL_TEXT,
        "tags": {"type": "array", "items": TEXT},
        "note": OPTIONAL_TEXT,
        "po_number": OPTIONAL_TEXT,
        "custom_attributes": {"type": "array", "items": CUSTOM_ATTRIBUTE},
    },
)

ORDER_LINE_ITEM: dict[str, Any] = _obj(
    [
        "id",
        "product_id",
        "variant_id",
        "title",
        "name",
        "sku",
        "quantity",
        "current_quantity",
        "refundable_quantity",
        "unfulfilled_quantity",
        "requires_shipping",
        "original_unit_price",
        "discounted_unit_price",
        "original_total",
        "discounted_total",
    ],
    {
        "id": TEXT,
        "product_id": OPTIONAL_TEXT,
        "variant_id": OPTIONAL_TEXT,
        "title": OPTIONAL_TEXT,
        "name": OPTIONAL_TEXT,
        "sku": OPTIONAL_TEXT,
        "quantity": OPTIONAL_INT,
        "current_quantity": OPTIONAL_INT,
        "refundable_quantity": OPTIONAL_INT,
        "unfulfilled_quantity": OPTIONAL_INT,
        "requires_shipping": OPTIONAL_BOOL,
        "original_unit_price": MONEY,
        "discounted_unit_price": MONEY,
        "original_total": MONEY,
        "discounted_total": MONEY,
    },
)

FULFILLMENT_ORDER_LINE_ITEM: dict[str, Any] = _obj(
    ["id", "line_item_id", "total_quantity", "remaining_quantity"],
    {
        "id": TEXT,
        "line_item_id": OPTIONAL_TEXT,
        "total_quantity": OPTIONAL_INT,
        "remaining_quantity": OPTIONAL_INT,
    },
)

FULFILLMENT_ORDER: dict[str, Any] = _obj(
    [
        "id",
        "status",
        "request_status",
        "assigned_location_id",
        "assigned_location_name",
        "created_at",
        "updated_at",
        "line_items",
        "line_items_page_info",
    ],
    {
        "id": TEXT,
        "status": OPTIONAL_TEXT,
        "request_status": OPTIONAL_TEXT,
        "assigned_location_id": OPTIONAL_TEXT,
        "assigned_location_name": OPTIONAL_TEXT,
        "created_at": OPTIONAL_TEXT,
        "updated_at": OPTIONAL_TEXT,
        "line_items": {"type": "array", "items": FULFILLMENT_ORDER_LINE_ITEM},
        "line_items_page_info": PAGE_INFO,
    },
)

NULLABLE_FULFILLMENT_ORDER: dict[str, Any] = {**FULFILLMENT_ORDER, "type": ["object", "null"]}

TRACKING_INFO: dict[str, Any] = _obj(
    ["company", "number", "url"],
    {"company": OPTIONAL_TEXT, "number": OPTIONAL_TEXT, "url": OPTIONAL_TEXT},
)

FULFILLMENT: dict[str, Any] = _obj(
    ["id", "status", "created_at", "updated_at", "tracking_info"],
    {
        "id": TEXT,
        "status": OPTIONAL_TEXT,
        "created_at": OPTIONAL_TEXT,
        "updated_at": OPTIONAL_TEXT,
        "tracking_info": {"type": "array", "items": TRACKING_INFO},
    },
)

NULLABLE_FULFILLMENT: dict[str, Any] = {**FULFILLMENT, "type": ["object", "null"]}
NULLABLE_MEDIA_FILE: dict[str, Any] = {**MEDIA_FILE, "type": ["object", "null"]}
NULLABLE_ORDER_METADATA: dict[str, Any] = {**ORDER_METADATA, "type": ["object", "null"]}

#: Fields present on a mutation result that Shopify never confirmed, so the
#: host can tell a suppressed rehearsal from a real write.
EXTERNAL_EFFECT_STATUS: dict[str, Any] = {"type": "string"}
DEFINITELY_NO_EXTERNAL_EFFECT: dict[str, Any] = {"type": "boolean"}


__all__ = [
    "CUSTOM_ATTRIBUTE",
    "DEFINITELY_NO_EXTERNAL_EFFECT",
    "EXTERNAL_EFFECT_STATUS",
    "FULFILLMENT",
    "FULFILLMENT_ORDER",
    "FULFILLMENT_ORDER_LINE_ITEM",
    "MEDIA_FILE",
    "METAFIELD",
    "MONEY",
    "NULLABLE_FULFILLMENT",
    "NULLABLE_FULFILLMENT_ORDER",
    "NULLABLE_MEDIA_FILE",
    "NULLABLE_ORDER",
    "NULLABLE_ORDER_METADATA",
    "NULLABLE_PRODUCT",
    "NULLABLE_PRODUCT_VARIANT",
    "ORDER",
    "ORDER_LINE_ITEM",
    "ORDER_METADATA",
    "PAGE_INFO",
    "PRODUCT",
    "PRODUCT_MEDIA",
    "PRODUCT_OPTION",
    "PRODUCT_VARIANT",
    "SELECTED_OPTION",
    "SEO",
    "TRACKING_INFO",
]
