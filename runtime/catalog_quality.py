"""Find the products whose catalog data needs attention.

Shopify's product search cannot filter on image size, alt text, description
length or empty variant fields, so ``export_products`` reads the matching
catalog and checks each product here. A product that passes is left out of the
export; one that fails carries ``quality_issues``: a list of codes, each naming
one thing to fix.

Issue codes::

    missing_images            the product has no image
    image_too_small           an image is smaller than the requested minimum
    image_missing_alt_text    an image has no alt text
    missing_description       the description is empty
    description_too_short     the plain-text description is shorter than asked
    missing_<field>           vendor, product_type, category, tags, seo_title,
                              seo_description — or, on any variant, sku,
                              barcode, weight or price
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from .catalog import QUALITY_FIELD_CHECKS, SHOPIFY_RECOMMENDED_IMAGE_SIZE

_TAG_RE = re.compile(r"<[^>]*>")
_SPACE_RE = re.compile(r"\s+")

#: The field checks read from variants rather than from the product.
VARIANT_FIELDS = frozenset({"sku", "barcode", "weight", "price"})


def plain_text_length(description_html: Any) -> int:
    """Characters a shopper reads: tags removed, entities decoded, spaces collapsed."""
    if not isinstance(description_html, str):
        return 0
    text = html.unescape(_TAG_RE.sub(" ", description_html))
    return len(_SPACE_RE.sub(" ", text).strip())


def image_minimum(quality: Mapping[str, Any]) -> tuple[int, int] | None:
    """The smallest acceptable image, or ``None`` when size is not checked."""
    width = int(quality.get("min_image_width") or 0)
    height = int(quality.get("min_image_height") or 0)
    if quality.get("below_recommended_image_size"):
        width = max(width, SHOPIFY_RECOMMENDED_IMAGE_SIZE)
        height = max(height, SHOPIFY_RECOMMENDED_IMAGE_SIZE)
    if not width and not height:
        return None
    return width, height


def needs_images(quality: Mapping[str, Any]) -> bool:
    return bool(
        quality.get("missing_images")
        or quality.get("missing_image_alt_text")
        or image_minimum(quality)
    )


def needs_variants(quality: Mapping[str, Any]) -> bool:
    return bool(VARIANT_FIELDS & set(quality.get("missing_fields") or ()))


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Sequence):
        return not value
    return False


def _zero_price(value: Any) -> bool:
    if _blank(value):
        return True
    try:
        return Decimal(str(value)) == 0
    except InvalidOperation:
        return True


def _variant_missing(variant: Mapping[str, Any], name: str) -> bool:
    if name == "sku":
        return _blank(variant.get("sku"))
    if name == "barcode":
        return _blank(variant.get("barcode"))
    if name == "price":
        return _zero_price(variant.get("price"))
    item = variant.get("inventory_item") or {}
    weight = ((item.get("measurement") or {}).get("weight")) or {}
    value = weight.get("value")
    return not isinstance(value, (int, float)) or value <= 0


def _product_missing(product: Mapping[str, Any], name: str) -> bool:
    if name == "category":
        return _blank(product.get("category_id"))
    if name in ("seo_title", "seo_description"):
        return _blank((product.get("seo") or {}).get(name.removeprefix("seo_")))
    return _blank(product.get(name))


def issues(product: Mapping[str, Any], quality: Mapping[str, Any]) -> list[str]:
    """Every checked problem this product has, as issue codes."""
    found: list[str] = []
    images = list(product.get("images") or [])
    if quality.get("missing_images") and not images:
        found.append("missing_images")
    minimum = image_minimum(quality)
    if minimum is not None:
        width, height = minimum
        if any(
            (isinstance(image.get("width"), int) and image["width"] < width)
            or (isinstance(image.get("height"), int) and image["height"] < height)
            for image in images
        ):
            found.append("image_too_small")
    if quality.get("missing_image_alt_text") and any(_blank(image.get("alt")) for image in images):
        found.append("image_missing_alt_text")
    length = plain_text_length(product.get("description_html"))
    if quality.get("missing_description") and length == 0:
        found.append("missing_description")
    minimum_length = quality.get("min_description_length")
    if (
        isinstance(minimum_length, int)
        and length < minimum_length
        and "missing_description" not in found
    ):
        found.append("description_too_short")
    variants = list(product.get("variants") or [])
    for name in quality.get("missing_fields") or ():
        if name not in QUALITY_FIELD_CHECKS:
            continue
        if name in VARIANT_FIELDS:
            missing = not variants or any(_variant_missing(v, name) for v in variants)
        else:
            missing = _product_missing(product, name)
        if missing:
            found.append(f"missing_{name}")
    return found


def checks_requested(quality: Mapping[str, Any]) -> int:
    """How many independent checks the filter asks for, for ``match: all``."""
    count = sum(
        1
        for flag in ("missing_images", "missing_image_alt_text", "missing_description")
        if quality.get(flag)
    )
    count += 1 if image_minimum(quality) is not None else 0
    count += 1 if quality.get("min_description_length") else 0
    count += len(set(quality.get("missing_fields") or ()))
    return count


def matches(found: Sequence[str], quality: Mapping[str, Any]) -> bool:
    if not found:
        return False
    if quality.get("match", "any") == "all":
        return len(set(found)) >= checks_requested(quality)
    return True


__all__ = [
    "checks_requested",
    "image_minimum",
    "issues",
    "matches",
    "needs_images",
    "needs_variants",
    "plain_text_length",
]
