"""Shopify global id parsing, applied before anything reaches the transport.

Every id a workflow supplies is checked for the *type* the operation expects, so
a Location id cannot be passed where an InventoryItem id belongs. Shopify would
reject the swap too, but only after the request has been sent; refusing it here
means a mistyped batch never touches the store.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from . import errors
from .errors import ExtensionError

INVENTORY_ITEM = "InventoryItem"
LOCATION = "Location"
PRODUCT = "Product"
PRODUCT_VARIANT = "ProductVariant"
TAXONOMY_CATEGORY = "TaxonomyCategory"
MEDIA_IMAGE = "MediaImage"
VIDEO = "Video"
MODEL_3D = "Model3d"
ORDER = "Order"
FULFILLMENT_ORDER = "FulfillmentOrder"
FULFILLMENT_ORDER_LINE_ITEM = "FulfillmentOrderLineItem"
FULFILLMENT = "Fulfillment"
COLLECTION = "Collection"
SAVED_SEARCH = "SavedSearch"
EXTERNAL_VIDEO = "ExternalVideo"
GENERIC_FILE = "GenericFile"
METAFIELD = "Metafield"

#: The id types this extension accepts anywhere. Nothing else is addressable.
SUPPORTED_GID_TYPES: frozenset[str] = frozenset(
    {
        INVENTORY_ITEM,
        LOCATION,
        PRODUCT,
        PRODUCT_VARIANT,
        TAXONOMY_CATEGORY,
        MEDIA_IMAGE,
        VIDEO,
        MODEL_3D,
        ORDER,
        FULFILLMENT_ORDER,
        FULFILLMENT_ORDER_LINE_ITEM,
        FULFILLMENT,
        COLLECTION,
        SAVED_SEARCH,
        EXTERNAL_VIDEO,
        GENERIC_FILE,
        METAFIELD,
    }
)

#: The product media types. Shopify models them as separate types, so the
#: check is a membership test rather than one expected type.
MEDIA_GID_TYPES: tuple[str, ...] = (MEDIA_IMAGE, VIDEO, MODEL_3D, EXTERNAL_VIDEO)

#: Every file type in Shopify Files, product media and generic files alike.
FILE_GID_TYPES: tuple[str, ...] = (*MEDIA_GID_TYPES, GENERIC_FILE)

#: The owner types each metafield operation may address, keyed by the owner type
#: name a caller supplies.
CATALOG_METAFIELD_OWNERS: dict[str, str] = {
    "product": PRODUCT,
    "product_variant": PRODUCT_VARIANT,
}

MAX_GID_LENGTH = 128

#: A Shopify GID. The type may contain digits after the first character —
#: `Model3d` is a real Shopify type, and a letters-only pattern silently
#: rejected every 3D model id. The type still has to match one this extension
#: declares, so allowing digits widens the pattern without widening the surface.
_GID_RE = re.compile(r"^gid://shopify/([A-Za-z][A-Za-z0-9]{0,63})/(.{1,64})$")

#: Almost every Shopify id is a number. Taxonomy categories are the exception:
#: they carry handle-shaped identifiers such as `hb-1-9-6`, so a numeric-only
#: rule made `category_id` impossible to use with a real category while a test
#: written against an invented numeric id went on passing. The pattern is per
#: type rather than one permissive rule for all, because widening it everywhere
#: would let a malformed id through for the types that really are numeric.
_NUMERIC_ID_RE = re.compile(r"^(?a:\d){1,20}$")
_TAXONOMY_ID_RE = re.compile(r"^[a-z]{2,8}(?:-(?a:\d){1,4})*$")

_ID_PATTERNS: dict[str, re.Pattern[str]] = {TAXONOMY_CATEGORY: _TAXONOMY_ID_RE}


def gid(value: Any, *, expected_type: str, field: str) -> str:
    """Return ``value`` when it is a Shopify GID of exactly ``expected_type``."""
    return one_of_gid(value, expected_types=(expected_type,), field=field)


def one_of_gid(value: Any, *, expected_types: Sequence[str], field: str) -> str:
    """Return ``value`` when it is a Shopify GID of one of ``expected_types``.

    Shopify models product media as three unrelated types, so a few fields
    legitimately accept more than one. Everything else names exactly one type
    and goes through :func:`gid`.
    """
    allowed = tuple(expected_types)
    if not allowed or any(name not in SUPPORTED_GID_TYPES for name in allowed):
        raise ExtensionError(  # pragma: no cover - guards the caller
            errors.INTERNAL_ERROR, "The operation could not be completed"
        )
    expected = " or ".join(f"gid://shopify/{name}/..." for name in allowed)
    text = value if isinstance(value, str) else ""
    if not text or len(text) > MAX_GID_LENGTH:
        raise ExtensionError(errors.INVALID_PAYLOAD, f"{field} must be {expected}")
    match = _GID_RE.fullmatch(text)
    if match is None or match.group(1) not in allowed:
        raise ExtensionError(errors.INVALID_PAYLOAD, f"{field} must be {expected}")
    pattern = _ID_PATTERNS.get(match.group(1), _NUMERIC_ID_RE)
    if pattern.fullmatch(match.group(2)) is None:
        raise ExtensionError(errors.INVALID_PAYLOAD, f"{field} must be {expected}")
    return text


def is_gid(value: Any, *, expected_type: str) -> bool:
    """Whether ``value`` is a well-formed GID of ``expected_type``.

    Used on the way back out: Shopify's answer is data, so a node that is not
    what was asked for is reported rather than raised.
    """
    if not isinstance(value, str):
        return False
    match = _GID_RE.fullmatch(value)
    if match is None or match.group(1) != expected_type:
        return False
    pattern = _ID_PATTERNS.get(expected_type, _NUMERIC_ID_RE)
    return pattern.fullmatch(match.group(2)) is not None


__all__ = [
    "CATALOG_METAFIELD_OWNERS",
    "COLLECTION",
    "EXTERNAL_VIDEO",
    "FILE_GID_TYPES",
    "FULFILLMENT",
    "FULFILLMENT_ORDER",
    "FULFILLMENT_ORDER_LINE_ITEM",
    "GENERIC_FILE",
    "INVENTORY_ITEM",
    "LOCATION",
    "MAX_GID_LENGTH",
    "MEDIA_GID_TYPES",
    "MEDIA_IMAGE",
    "METAFIELD",
    "MODEL_3D",
    "ORDER",
    "PRODUCT",
    "PRODUCT_VARIANT",
    "SAVED_SEARCH",
    "SUPPORTED_GID_TYPES",
    "TAXONOMY_CATEGORY",
    "VIDEO",
    "gid",
    "is_gid",
    "one_of_gid",
]
