"""Editorial guidance for the existing fixed workflow inputs.

The contract generator combines these examples with the canonical schema's
field descriptions. These are hints, never defaults or GraphQL input changes.
"""

from __future__ import annotations

import json
from typing import Any

FIELD_HELP = {
    "title": "Product name shown in the store. Example: Blue ceramic mug.",
    "description_html": "Product description as HTML. Example: <p>Blue ceramic mug, 300 ml.</p>",
    "vendor": "Vendor or brand name saved on the product. Example: Example Ceramics.",
    "product_type": "Merchant-defined product classification. Example: Drinkware.",
    "seo_title": "Search-engine title for the product page. Example: Blue ceramic mug | Example Store.",
    "seo_description": "Search-engine summary for the product page. Example: A glazed blue ceramic mug for everyday use.",
    "template_suffix": "Suffix of an existing product template in the store's theme. Example: preorder for product.preorder.",
    "gift_card_template_suffix": "Suffix of an existing gift card template in the store's theme.",
    "requires_selling_plan": "Whether customers must purchase this product through a selling plan.",
    "tags": 'Product tags as a JSON array of strings. Example: ["summer", "ceramics"].',
    "gift_card": "Whether this new product is a gift card.",
    "combined_listing_role": "Role of this product in a combined listing. Choose a value from the declared schema; Shopify determines whether the store is eligible.",
    "status": "Product publication status. Choose a value from the declared schema; omitted fields retain the action's native behavior.",
    "sort_key": "Sort field for this list or export. Choose a value supported by this action; reverse controls its direction.",
    "filename": "Replacement filename for the media file, including its extension. Example: blue-mug.jpg.",
    "add_to_product_ids": 'Existing product GIDs to associate with this file, as a JSON array. Example: ["gid://shopify/Product/1042"].',
    "remove_from_product_ids": 'Existing product GIDs to disassociate from this file, as a JSON array. Example: ["gid://shopify/Product/1042"].',
}

FIELD_EXAMPLES: dict[str, Any] = {
    "product_id": "gid://shopify/Product/1042",
    "product_variant_id": "gid://shopify/ProductVariant/2042",
    "inventory_item_id": "gid://shopify/InventoryItem/3042",
    "location_id": "gid://shopify/Location/4042",
    "order_id": "gid://shopify/Order/5042",
    "fulfillment_order_id": "gid://shopify/FulfillmentOrder/6042",
    "fulfillment_id": "gid://shopify/Fulfillment/7042",
    "title": "Blue ceramic mug",
    "description_html": "<p>Blue ceramic mug, 300 ml.</p>",
    "vendor": "Example Ceramics",
    "product_type": "Drinkware",
    "tags": ["summer", "ceramics"],
    "filename": "blue-mug.jpg",
    "namespace": "custom",
    "keys": ["custom.supplier_ref"],
    "sku": "MUG-BLUE-01",
    "first": 10,
    "inventory_item_ids": ["gid://shopify/InventoryItem/3042"],
    "quantities": [
        {
            "inventory_item_id": "gid://shopify/InventoryItem/3042",
            "location_id": "gid://shopify/Location/4042",
            "quantity": 24,
            "change_from_quantity": 18,
        }
    ],
    "media": [
        {
            "source_url": "https://example.com/blue-mug.jpg",
            "content_type": "IMAGE",
            "alt": "Blue ceramic mug",
        }
    ],
}


def field_guidance(name: str, spec: dict[str, Any]) -> dict[str, str]:
    """Project existing schema help plus realistic hints into the step form."""
    result = {}
    help_text = str(spec.get("description") or FIELD_HELP.get(name) or "")
    if help_text:
        result["help_text"] = help_text
    examples = spec.get("examples") or []
    example = examples[0] if examples else FIELD_EXAMPLES.get(name)
    if example is not None:
        result["placeholder"] = example if isinstance(example, str) else json.dumps(example)
    return result
