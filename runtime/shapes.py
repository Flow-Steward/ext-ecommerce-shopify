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

from . import records

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


# -- Records ---------------------------------------------------------------
#
# Every record is shaped from its table in :mod:`runtime.records`; these names
# remain so each call site reads as the record it produces.


def shop(node: Any) -> dict[str, Any]:
    return records.shape("Shop", node)


def location(node: Any) -> dict[str, Any]:
    return records.shape("Location", node)


def inventory_item(node: Any) -> dict[str, Any]:
    return records.shape("InventoryItem", node)


def adjustment_group(node: Any) -> dict[str, Any]:
    return records.shape("InventoryAdjustmentGroup", node)


def product(node: Any) -> dict[str, Any]:
    return records.shape("Product", node)


def product_variant(node: Any) -> dict[str, Any]:
    return records.shape("ProductVariant", node)


def metafield(node: Any, *, owner_id: str | None) -> dict[str, Any]:
    """One metafield. ``owner_id`` is supplied by the caller of the shaper.

    A metafield's owner is not read back out of the response: for a list it is
    the record that was queried, and for a set it is the tuple the entry was
    correlated by. Either way it is already known, and asking Shopify for it
    again would only add a way for the two to disagree.
    """
    return records.shape("Metafield", node, owner_id=owner_id)


def product_media(node: Any) -> dict[str, Any]:
    return records.shape("Media", node)


def media_file(node: Any) -> dict[str, Any]:
    return records.shape("File", node)


def order(node: Any) -> dict[str, Any]:
    return records.shape("Order", node)


def order_line_item(node: Any) -> dict[str, Any]:
    return records.shape("LineItem", node)


def fulfillment_order(node: Any) -> dict[str, Any]:
    return records.shape("FulfillmentOrder", node)


def fulfillment(node: Any) -> dict[str, Any]:
    return records.shape("Fulfillment", node)


def _objects(value: Any, *, limit: int = MAX_NESTED_ITEMS) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [entry for entry in value[:limit] if isinstance(entry, Mapping)]


__all__ = [
    "MAX_NESTED_ITEMS",
    "adjustment_group",
    "fulfillment",
    "fulfillment_order",
    "inventory_item",
    "location",
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
    "page_info",
    "product",
    "product_media",
    "product_variant",
    "shop",
    "string_list",
    "text",
]
