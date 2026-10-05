"""Input schema fragments that mirror Shopify's own input objects field by field.

Each fragment here corresponds to one Shopify Admin GraphQL input type,
pinned to the version in :mod:`runtime.documents`, and names every field that type accepts, in snake_case. The mapping back to
Shopify's camelCase lives in :mod:`runtime.product_input`; which Shopify fields
are deliberately not reachable, and why, lives in :mod:`runtime.coverage`. The
coverage tests compare all three against the pinned official schema, so a field
Shopify adds or this extension forgets is a failing test rather than a gap a
user discovers.

Only the keyword subset the host executes is used (see :mod:`runtime.schema`).
"""

from __future__ import annotations

from typing import Any

from .gids import MAX_GID_LENGTH

MAX_TEXT_LENGTH = 255
MAX_URL_LENGTH = 2048
MAX_DECIMAL_LENGTH = 32
MAX_METAFIELD_VALUE_LENGTH = 512 * 1024
MAX_PRODUCT_OPTIONS = 3
MAX_OPTION_VALUES = 100
MAX_MEDIA_ITEMS = 250
MAX_IMAGE_FILES = 20
MAX_METAFIELDS_PER_RECORD = 250
MAX_COLLECTIONS = 250
MAX_INVENTORY_LOCATIONS = 250
MAX_CODES = 250

PRODUCT_STATUSES: tuple[str, ...] = ("ACTIVE", "ARCHIVED", "DRAFT", "UNLISTED")
COMBINED_LISTING_ROLES: tuple[str, ...] = ("PARENT", "CHILD")
MEDIA_CONTENT_TYPES: tuple[str, ...] = ("IMAGE", "VIDEO", "EXTERNAL_VIDEO", "MODEL_3D")
DUPLICATE_RESOLUTION_MODES: tuple[str, ...] = ("APPEND_UUID", "RAISE_ERROR", "REPLACE")
INVENTORY_POLICIES: tuple[str, ...] = ("DENY", "CONTINUE")
WEIGHT_UNITS: tuple[str, ...] = ("KILOGRAMS", "GRAMS", "POUNDS", "OUNCES")
UNIT_PRICE_UNITS: tuple[str, ...] = (
    "ML", "CL", "L", "M3", "FLOZ", "PT", "QT", "GAL", "MG", "G", "KG", "OZ", "LB",
    "MM", "CM", "M", "IN", "FT", "YD", "M2", "FT2", "ITEM", "UNKNOWN",
)  # fmt: skip
#: The two quantity names Shopify lets a product write set.
SET_QUANTITY_NAMES: tuple[str, ...] = ("available", "on_hand")


def text(maximum: int = MAX_TEXT_LENGTH, *, minimum: int = 0, **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"type": "string", "maxLength": maximum, **extra}
    if minimum:
        entry["minLength"] = minimum
    return entry


def gid_text(**extra: Any) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": MAX_GID_LENGTH, **extra}


def decimal(**extra: Any) -> dict[str, Any]:
    return {
        "type": "string",
        "description": 'A decimal amount as a string, for example "19.99".',
        "minLength": 1,
        "maxLength": MAX_DECIMAL_LENGTH,
        **extra,
    }


def enum(values: tuple[str, ...], **extra: Any) -> dict[str, Any]:
    return {"type": "string", "enum": list(values), **extra}


def obj(properties: dict[str, Any], *, required: tuple[str, ...] = (), **extra: Any):
    entry: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        **extra,
    }
    if required:
        entry["required"] = list(required)
    return entry


def array(items: dict[str, Any], maximum: int, *, minimum: int = 0, **extra: Any):
    entry: dict[str, Any] = {"type": "array", "maxItems": maximum, "items": items, **extra}
    if minimum:
        entry["minItems"] = minimum
    return entry


# -- Metafields ------------------------------------------------------------

#: Shopify ``MetafieldInput`` as used inside product, variant and order writes.
#: ``id`` addresses an existing metafield; without it namespace and key do.
METAFIELD_INPUT = obj(
    {
        "id": gid_text(description="An existing gid://shopify/Metafield/... id to update."),
        "namespace": text(minimum=3),
        "key": text(64, minimum=2),
        "type": text(64, minimum=1),
        "value": text(MAX_METAFIELD_VALUE_LENGTH),
    }
)
#: The same, for a record that does not exist yet and so has no metafield ids.
NEW_METAFIELD_INPUT = obj(
    {
        "namespace": text(minimum=3),
        "key": text(64, minimum=2),
        "type": text(64, minimum=1),
        "value": text(MAX_METAFIELD_VALUE_LENGTH),
    },
    required=("namespace", "key", "type", "value"),
)


def metafields(item: dict[str, Any], description: str) -> dict[str, Any]:
    return array(item, MAX_METAFIELDS_PER_RECORD, title="Metafields", description=description)


# -- Media -----------------------------------------------------------------

#: One media item supplied by URL or by an existing Shopify file id. Shopify
#: downloads a URL asynchronously; ``list_product_media`` reports when it is READY.
MEDIA_ITEM = obj(
    {
        "source_url": text(
            MAX_URL_LENGTH,
            minimum=9,
            title="Source URL",
            description=(
                "A public https:// URL Shopify downloads. For EXTERNAL_VIDEO, a YouTube or "
                "Vimeo URL."
            ),
        ),
        "file_id": gid_text(
            title="Existing file id",
            description="A file already in Shopify Files: MediaImage, Video, Model3d, "
            "ExternalVideo or GenericFile id.",
        ),
        "content_type": enum(MEDIA_CONTENT_TYPES, title="Content type", default="IMAGE"),
        "alt": text(512, title="Alt text"),
        "filename": text(title="Filename"),
        "duplicate_resolution_mode": enum(
            DUPLICATE_RESOLUTION_MODES,
            title="If the filename already exists",
            description="APPEND_UUID (Shopify's default), RAISE_ERROR or REPLACE.",
        ),
    }
)


def media(description: str) -> dict[str, Any]:
    return array(MEDIA_ITEM, MAX_MEDIA_ITEMS, title="Media", description=description)


#: An image held by Flow Steward — a workflow artifact — rather than at a URL.
#: The extension uploads it to Shopify's staged storage first.
IMAGE_FILE_ITEM = obj(
    {
        "artifact_handle": text(
            512,
            minimum=1,
            title="Image artifact",
            description="The artifact handle of a JPEG, PNG, GIF or WEBP file, up to 20 MB.",
        ),
        "alt": text(512, title="Alt text"),
        "filename": text(
            title="Filename",
            description="The name Shopify stores. Defaults to the artifact's own name.",
        ),
    },
    required=("artifact_handle",),
)

IMAGE_FILES = array(
    IMAGE_FILE_ITEM,
    MAX_IMAGE_FILES,
    title="Image files",
    description=(
        "Images stored in Flow Steward (workflow artifacts) to upload and attach. Each file "
        "goes through Shopify's staged upload first; up to 20 per call."
    ),
)


# -- Variants --------------------------------------------------------------

OPTION_VALUE_INPUT = obj(
    {
        "option_name": text(minimum=1),
        "value": text(minimum=1),
        "linked_metafield_value": text(
            description="For an option linked to a metafield, the metafield value to use.",
        ),
    },
    required=("option_name",),
)

WEIGHT_INPUT = obj(
    {"value": {"type": "number", "minimum": 0}, "unit": enum(WEIGHT_UNITS)},
    required=("value", "unit"),
)

INVENTORY_ITEM_INPUT = obj(
    {
        "sku": text(minimum=1),
        "cost": decimal(),
        "tracked": {"type": "boolean"},
        "requires_shipping": {"type": "boolean"},
        "country_code_of_origin": text(2, minimum=2, description="ISO 3166-1 alpha-2."),
        "province_code_of_origin": text(8, minimum=1),
        "harmonized_system_code": text(14, minimum=6),
        "country_harmonized_system_codes": array(
            obj(
                {"harmonized_system_code": text(14, minimum=6), "country_code": text(2, minimum=2)},
                required=("harmonized_system_code",),
            ),
            MAX_CODES,
        ),
        "measurement": obj(
            {"weight": WEIGHT_INPUT, "shipping_package_id": gid_text()},
        ),
    }
)

UNIT_PRICE_MEASUREMENT_INPUT = obj(
    {
        "quantity_value": {"type": "number", "minimum": 0},
        "quantity_unit": enum(UNIT_PRICE_UNITS),
        "reference_value": {"type": "integer", "minimum": 1, "maximum": 1000000},
        "reference_unit": enum(UNIT_PRICE_UNITS),
    }
)

#: Fields every variant write shares, whichever Shopify mutation carries them.
VARIANT_COMMON_FIELDS: dict[str, Any] = {
    "price": decimal(),
    "compare_at_price": decimal(),
    "barcode": text(),
    "inventory_policy": enum(INVENTORY_POLICIES),
    "taxable": {"type": "boolean"},
    "tax_code": text(),
    "requires_components": {"type": "boolean"},
    "published": {"type": "boolean"},
    "show_unit_price": {"type": "boolean"},
    "unit_price_measurement": UNIT_PRICE_MEASUREMENT_INPUT,
    "inventory_item": INVENTORY_ITEM_INPUT,
}

#: ``ProductVariantsBulkInput`` extras: product-media references and stock.
VARIANT_BULK_FIELDS: dict[str, Any] = {
    "media_src": array(
        text(MAX_URL_LENGTH, minimum=1),
        10,
        description="Source URLs of media in this call's media list to attach to the variant.",
    ),
    "media_id": gid_text(description="An existing product media id to attach to the variant."),
    "inventory_quantities": array(
        obj(
            {
                "location_id": gid_text(),
                "available_quantity": {"type": "integer", "minimum": 0, "maximum": 2147483647},
            },
            required=("location_id", "available_quantity"),
        ),
        MAX_INVENTORY_LOCATIONS,
        description="Starting available stock per location. Requires write_inventory.",
    ),
    "quantity_adjustments": array(
        obj(
            {
                "location_id": gid_text(),
                "adjustment": {"type": ["integer", "null"]},
                "change_from_quantity": {"type": ["integer", "null"]},
            },
            required=("location_id", "change_from_quantity"),
        ),
        MAX_INVENTORY_LOCATIONS,
        description=(
            "Relative stock changes per location. change_from_quantity is required and may be "
            "null. Requires write_inventory."
        ),
    ),
    "metafields": metafields(METAFIELD_INPUT, "Metafields to set on the variant."),
}

#: ``ProductVariantSetInput`` extras used when a product is created whole.
VARIANT_SET_FIELDS: dict[str, Any] = {
    "sku": text(minimum=1),
    "position": {"type": "integer", "minimum": 1, "maximum": 2048},
    "image": obj(
        {
            "source_url": MEDIA_ITEM["properties"]["source_url"],
            "file_id": MEDIA_ITEM["properties"]["file_id"],
            "alt": text(512),
            "filename": text(),
            "duplicate_resolution_mode": enum(DUPLICATE_RESOLUTION_MODES),
        },
        title="Variant image",
    ),
    "inventory_quantities": array(
        obj(
            {
                "location_id": gid_text(),
                "name": enum(SET_QUANTITY_NAMES),
                "quantity": {"type": "integer", "minimum": 0, "maximum": 2147483647},
            },
            required=("location_id", "name", "quantity"),
        ),
        MAX_INVENTORY_LOCATIONS,
        description="Starting stock per location (available or on_hand). Requires write_inventory.",
    ),
    "metafields": metafields(NEW_METAFIELD_INPUT, "Metafields to set on the new variant."),
}


OPTION_VALUES = array(OPTION_VALUE_INPUT, MAX_PRODUCT_OPTIONS, minimum=1)


# -- Products --------------------------------------------------------------

PRODUCT_OPTIONS = array(
    obj(
        {
            "name": text(minimum=1),
            "position": {"type": "integer", "minimum": 1, "maximum": MAX_PRODUCT_OPTIONS},
            "values": array(text(minimum=1), MAX_OPTION_VALUES, minimum=1),
            "linked_metafield": obj(
                {
                    "namespace": text(minimum=1),
                    "key": text(minimum=1),
                    "values": array(text(minimum=1), MAX_OPTION_VALUES),
                },
                required=("namespace", "key"),
            ),
        },
        required=("name",),
    ),
    MAX_PRODUCT_OPTIONS,
    title="Options",
    description=(
        "Up to three options. Give values, or link the option to a metafield. Without "
        "variants, Shopify builds the initial variant from the first value of each."
    ),
)

COLLECTION_IDS = array(gid_text(), MAX_COLLECTIONS, description="gid://shopify/Collection/... ids.")

#: Product fields shared by creation and update, beyond title and handle.
PRODUCT_COMMON_FIELDS: dict[str, Any] = {
    "description_html": text(65535, title="Description HTML"),
    "vendor": text(title="Vendor"),
    "product_type": text(title="Product type"),
    "category_id": gid_text(
        title="Category id", description="A gid://shopify/TaxonomyCategory/... id."
    ),
    "seo_title": text(title="SEO title"),
    "seo_description": text(1024, title="SEO description"),
    "template_suffix": text(title="Theme template suffix"),
    "gift_card_template_suffix": text(title="Gift card template suffix"),
    "requires_selling_plan": {"type": "boolean", "title": "Sold only by subscription"},
}

__all__ = [
    "COLLECTION_IDS",
    "COMBINED_LISTING_ROLES",
    "IMAGE_FILES",
    "MEDIA_CONTENT_TYPES",
    "METAFIELD_INPUT",
    "NEW_METAFIELD_INPUT",
    "OPTION_VALUES",
    "PRODUCT_COMMON_FIELDS",
    "PRODUCT_OPTIONS",
    "PRODUCT_STATUSES",
    "VARIANT_BULK_FIELDS",
    "VARIANT_COMMON_FIELDS",
    "VARIANT_SET_FIELDS",
    "array",
    "decimal",
    "enum",
    "gid_text",
    "media",
    "metafields",
    "obj",
    "text",
]
