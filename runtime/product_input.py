"""Shared validated product field mapping for single and bulk creation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def product_input(operation_input: Mapping[str, Any]) -> dict[str, Any]:
    """The Shopify product input, built field by field from what was supplied.

    Only keys the caller actually sent are added, so an omitted field is left
    alone rather than overwritten with an empty value.
    """
    built: dict[str, Any] = {}
    for source, target in (
        ("title", "title"),
        ("description_html", "descriptionHtml"),
        ("vendor", "vendor"),
        ("product_type", "productType"),
        ("handle", "handle"),
    ):
        if source in operation_input:
            built[target] = operation_input[source]
    if "category_id" in operation_input:
        built["category"] = operation_input["category_id"]
    seo = {}
    if "seo_title" in operation_input:
        seo["title"] = operation_input["seo_title"]
    if "seo_description" in operation_input:
        seo["description"] = operation_input["seo_description"]
    if seo:
        built["seo"] = seo
    return built


def draft_product_input(operation_input: Mapping[str, Any]) -> dict[str, Any]:
    """Build the existing draft creation contract without adding permissions."""
    product = product_input(operation_input)
    product["status"] = "DRAFT"
    if "tags" in operation_input:
        product["tags"] = list(operation_input["tags"])
    if "options" in operation_input:
        product["productOptions"] = [
            {"name": option["name"], "values": [{"name": value} for value in option["values"]]}
            for option in operation_input["options"]
        ]
    return product


def create_product_variables(operation_input: Mapping[str, Any]) -> dict[str, Any]:
    """Keep image sources alongside ProductCreateInput in both creation paths."""
    variables: dict[str, Any] = {"product": draft_product_input(operation_input)}
    if operation_input.get("images"):
        variables["media"] = [
            {
                "mediaContentType": "IMAGE",
                "originalSource": image["url"],
                **({"alt": image["alt"]} if "alt" in image else {}),
            }
            for image in operation_input["images"]
        ]
    return variables
