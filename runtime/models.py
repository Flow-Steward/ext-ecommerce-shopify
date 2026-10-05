"""The published result schemas, derived from the record tables.

Every record shape lives in :mod:`runtime.records` as one table of Shopify
fields; this module only names the schemas the registry publishes, so a field
cannot appear in a result without appearing in a table first.

What is deliberately absent is listed with its reason in :mod:`runtime.coverage`.
No order record carries a customer, an email address, a phone number, a billing
or shipping address or an IP address: those are Shopify's protected customer
data and are neither queried nor shaped. Free-text fields that remain (notes,
custom attributes, tags, metafield values, tracking numbers) can still hold
whatever a merchant typed, which is why no result, input or variable set is
ever logged whole.
"""

from __future__ import annotations

from typing import Any

from .records import MONEY_SCHEMA, schema

PAGE_INFO: dict[str, Any] = schema("PageInfo")
MONEY: dict[str, Any] = MONEY_SCHEMA

SHOP: dict[str, Any] = schema("Shop")
LOCATION: dict[str, Any] = schema("Location")
INVENTORY_ITEM: dict[str, Any] = schema("InventoryItem")
INVENTORY_ADJUSTMENT_GROUP: dict[str, Any] = schema("InventoryAdjustmentGroup", nullable=True)

PRODUCT: dict[str, Any] = schema("Product")
NULLABLE_PRODUCT: dict[str, Any] = schema("Product", nullable=True)
PRODUCT_VARIANT: dict[str, Any] = schema("ProductVariant")
NULLABLE_PRODUCT_VARIANT: dict[str, Any] = schema("ProductVariant", nullable=True)

#: A variant confirmed by product creation must carry enough identity for the
#: next workflow steps: its product and its inventory item, never ``null``.
INITIAL_PRODUCT_VARIANT: dict[str, Any] = {
    **PRODUCT_VARIANT,
    "properties": {
        **PRODUCT_VARIANT["properties"],
        "product_id": {"type": "string"},
        "inventory_item": schema("InventoryItem"),
    },
}

METAFIELD: dict[str, Any] = {
    **schema("Metafield"),
    "required": [*schema("Metafield")["required"], "owner_id"],
    "properties": {**schema("Metafield")["properties"], "owner_id": {"type": ["string", "null"]}},
}
PRODUCT_MEDIA: dict[str, Any] = schema("Media")
FILE: dict[str, Any] = schema("File")
NULLABLE_FILE: dict[str, Any] = schema("File", nullable=True)

ORDER: dict[str, Any] = schema("Order")
NULLABLE_ORDER: dict[str, Any] = schema("Order", nullable=True)
ORDER_LINE_ITEM: dict[str, Any] = schema("LineItem")
FULFILLMENT_ORDER: dict[str, Any] = schema("FulfillmentOrder")
FULFILLMENT: dict[str, Any] = schema("Fulfillment")
NULLABLE_FULFILLMENT: dict[str, Any] = schema("Fulfillment", nullable=True)

__all__ = [
    "FILE",
    "FULFILLMENT",
    "FULFILLMENT_ORDER",
    "INITIAL_PRODUCT_VARIANT",
    "INVENTORY_ADJUSTMENT_GROUP",
    "INVENTORY_ITEM",
    "LOCATION",
    "METAFIELD",
    "MONEY",
    "NULLABLE_FILE",
    "NULLABLE_FULFILLMENT",
    "NULLABLE_ORDER",
    "NULLABLE_PRODUCT",
    "NULLABLE_PRODUCT_VARIANT",
    "ORDER",
    "ORDER_LINE_ITEM",
    "PAGE_INFO",
    "PRODUCT",
    "PRODUCT_MEDIA",
    "PRODUCT_VARIANT",
    "SHOP",
]
