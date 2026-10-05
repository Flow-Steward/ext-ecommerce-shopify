"""The closed operation registry: exactly thirty-three rows, and nothing derives from input.

Every routable operation is a literal row below, carrying its own input schema,
its own output fields, and the fixed GraphQL document it sends. Nothing is
discovered from the store, from an introspection query, or from the caller: an
operation that is not in this table cannot be routed, and a GraphQL document
that is not named by a row here is never sent.

``contracts/operation_manifest.yaml``, ``contracts/step_ui_manifest.yaml`` and
``ui/actions/actions.yaml`` are generated from this table and held in exact
parity by the extension's own tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from . import errors, inputs, models, scopes
from .connection import CONNECTION_TYPE_ID
from .documents import DOCUMENTS, READ_QUANTITY_NAMES
from .gids import MAX_GID_LENGTH

_MESSAGE_THE_END_CURSOR_OF_THE_PREVIOUS_PAGE = "The end_cursor of the previous page."
_MESSAGE_AFTER_CURSOR = "After cursor"
_MESSAGE_PAGE_SIZE = "Page size"
_MESSAGE_PRODUCT_ID = "Product id"
_MESSAGE_ORDER_ID = "Order id"

CATEGORY = "ecommerce"
CHANNEL = "shopify_admin_graphql"

#: Shopify's own ceiling for one page and for one synchronous quantity batch.
MAX_PAGE_SIZE = 250
DEFAULT_PAGE_SIZE = 50
MAX_BATCH_ITEMS = 250
MIN_BATCH_ITEMS = 1

MAX_CONNECTION_REF_LENGTH = 256
MAX_CURSOR_LENGTH = 1024
MAX_SEARCH_QUERY_LENGTH = 4096
MAX_SKU_LENGTH = 255

#: Shopify quantities are GraphQL ``Int``, which is a signed 32-bit value. A
#: quantity may not be negative: this extension sets absolute stock levels.
MAX_QUANTITY = 2_147_483_647

VALIDATE_SETTINGS_OPERATION_ID = "validate_connection_settings"
TEST_CONNECTION_OPERATION_ID = "test_connection"
SET_QUANTITIES_OPERATION_ID = "set_inventory_quantities"

_CONNECTION_REF_SCHEMA: dict[str, Any] = {
    "type": "string",
    "title": "Connection",
    "description": "The Shopify connection this operation runs against.",
    "minLength": 1,
    "maxLength": MAX_CONNECTION_REF_LENGTH,
}

_GID_SCHEMA_BASE: dict[str, Any] = {"type": "string", "minLength": 1, "maxLength": MAX_GID_LENGTH}

_PAGE_INFO_SCHEMA: dict[str, Any] = models.PAGE_INFO

#: Every quantity state an inventory level reports, each under its own key.
_INVENTORY_LEVEL_SCHEMA: dict[str, Any] = {
    "type": ["object", "null"],
    "additionalProperties": False,
    "required": [
        "id",
        "location_id",
        "is_active",
        "level_is_active",
        "can_deactivate",
        "deactivation_alert",
        "created_at",
        "updated_at",
        *READ_QUANTITY_NAMES,
    ],
    "properties": {
        "id": {"type": "string"},
        "location_id": {"type": ["string", "null"]},
        "is_active": {
            "type": ["boolean", "null"],
            "description": "Whether the location is active.",
        },
        "level_is_active": {
            "type": ["boolean", "null"],
            "description": "Whether the item is still stocked at this location.",
        },
        "can_deactivate": {"type": ["boolean", "null"]},
        "deactivation_alert": {"type": ["string", "null"]},
        "created_at": {"type": ["string", "null"]},
        "updated_at": {"type": ["string", "null"]},
        **{name: {"type": ["integer", "null"]} for name in READ_QUANTITY_NAMES},
    },
}

_INVENTORY_LEVEL_ROW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["inventory_item_id", "found", "sku", "tracked", "level"],
    "properties": {
        "inventory_item_id": {"type": "string"},
        "found": {"type": "boolean"},
        "sku": {"type": ["string", "null"]},
        "tracked": {"type": ["boolean", "null"]},
        "level": _INVENTORY_LEVEL_SCHEMA,
    },
}


MAX_TITLE_LENGTH = 255
MAX_HANDLE_LENGTH = 255
MAX_DESCRIPTION_LENGTH = 65535
MAX_SEO_DESCRIPTION_LENGTH = 1024
MAX_TAGS = 250
MAX_TAG_LENGTH = 255
MAX_PRODUCT_OPTIONS = 3
MAX_OPTION_VALUES = 100
MAX_ALT_LENGTH = 1024
MAX_BARCODE_LENGTH = 255

#: Prices and costs travel as decimal strings, exactly as Shopify sends and
#: accepts them. Parsing one into a binary float here would round a price the
#: merchant set; the format itself is checked in `runtime/validation.py`,
#: because the executable schema subset has no pattern keyword.
MAX_DECIMAL_LENGTH = 32

#: Shopify caps one `metafieldsSet` call at 25 entries.
MAX_METAFIELDS_PER_CALL = 25
MAX_METAFIELD_NAMESPACE_LENGTH = 255
MAX_METAFIELD_KEY_LENGTH = 64
MAX_METAFIELD_TYPE_LENGTH = 64
MAX_METAFIELD_VALUE_LENGTH = 512 * 1024
MAX_COMPARE_DIGEST_LENGTH = 512

#: One fulfillment call may name this many fulfillment orders and line items.
MAX_FULFILLMENT_ORDERS = 50
MAX_FULFILLMENT_LINE_ITEMS = 250
MAX_TRACKING_NUMBERS = 25
MAX_TRACKING_TEXT_LENGTH = 255
MAX_TRACKING_URL_LENGTH = 2048

#: Custom attributes and notes on an order.
MAX_CUSTOM_ATTRIBUTES = 50
MAX_ATTRIBUTE_KEY_LENGTH = 255
MAX_ATTRIBUTE_VALUE_LENGTH = 2048
MAX_NOTE_LENGTH = 5000
MAX_PO_NUMBER_LENGTH = 255

_SHORT_TEXT_SCHEMA: dict[str, Any] = {"type": "string", "maxLength": MAX_TITLE_LENGTH}
_TITLE_SCHEMA: dict[str, Any] = {
    "type": "string",
    "minLength": 1,
    "maxLength": MAX_TITLE_LENGTH,
}
_HANDLE_SCHEMA: dict[str, Any] = {
    "type": "string",
    "minLength": 1,
    "maxLength": MAX_HANDLE_LENGTH,
}
_DESCRIPTION_SCHEMA: dict[str, Any] = {
    "type": "string",
    "title": "Description HTML",
    "maxLength": MAX_DESCRIPTION_LENGTH,
}
_SEO_DESCRIPTION_SCHEMA: dict[str, Any] = {
    "type": "string",
    "maxLength": MAX_SEO_DESCRIPTION_LENGTH,
}
_TAGS_SCHEMA: dict[str, Any] = {
    "type": "array",
    "title": "Tags",
    "maxItems": MAX_TAGS,
    "items": {"type": "string", "minLength": 1, "maxLength": MAX_TAG_LENGTH},
}
#: A variant created through ``productVariantsBulkCreate``.
_VARIANT_CREATE_ITEM_SCHEMA: dict[str, Any] = inputs.obj(
    {
        "option_values": inputs.OPTION_VALUES,
        **inputs.VARIANT_COMMON_FIELDS,
        **inputs.VARIANT_BULK_FIELDS,
    },
    required=("option_values",),
)

#: A variant changed through ``productVariantsBulkUpdate``.
_VARIANT_UPDATE_ITEM_SCHEMA: dict[str, Any] = inputs.obj(
    {
        "variant_id": dict(_GID_SCHEMA_BASE),
        "option_values": inputs.OPTION_VALUES,
        **inputs.VARIANT_COMMON_FIELDS,
        **inputs.VARIANT_BULK_FIELDS,
    },
    required=("variant_id",),
)

#: A variant of a product created whole through ``productSet``.
_VARIANT_SET_ITEM_SCHEMA: dict[str, Any] = inputs.obj(
    {
        "option_values": {
            **inputs.OPTION_VALUES,
            "description": "Required when the product has options; omit for a single-variant "
            "product without options.",
        },
        **inputs.VARIANT_COMMON_FIELDS,
        **inputs.VARIANT_SET_FIELDS,
    },
)

#: The most variants one ``create_product`` call creates. Bounded by Shopify's
#: per-query cost limit: every created variant is confirmed in the same answer.
MAX_CREATE_VARIANTS = 100

#: Every field a variant entry may change, other than the id itself. Used to
#: refuse an update entry that names a variant and asks for nothing.
VARIANT_UPDATE_CHANGE_FIELDS: tuple[str, ...] = tuple(
    name for name in _VARIANT_UPDATE_ITEM_SCHEMA["properties"] if name != "variant_id"
)


def _metafield_entry_schema(owner_description: str) -> dict[str, Any]:
    """One metafield to set, including its compare-and-set digest.

    ``compare_digest`` is required and nullable rather than optional. A caller
    that has read the current value passes its digest; a caller that means to
    create the metafield and fail if it already exists passes ``null``. Leaving
    the key out entirely would be a third, silent meaning — "overwrite whatever
    is there" — and that is exactly the outcome compare-and-set exists to
    prevent, so it is refused.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["owner_id", "namespace", "key", "type", "value", "compare_digest"],
        "properties": {
            "owner_id": {**_GID_SCHEMA_BASE, "description": owner_description},
            "namespace": {
                "type": "string",
                "minLength": 3,
                "maxLength": MAX_METAFIELD_NAMESPACE_LENGTH,
            },
            "key": {"type": "string", "minLength": 2, "maxLength": MAX_METAFIELD_KEY_LENGTH},
            "type": {"type": "string", "minLength": 1, "maxLength": MAX_METAFIELD_TYPE_LENGTH},
            "value": {"type": "string", "maxLength": MAX_METAFIELD_VALUE_LENGTH},
            "compare_digest": {
                "type": ["string", "null"],
                "description": (
                    "The compare digest you read with the value, or null to create only."
                ),
                "maxLength": MAX_COMPARE_DIGEST_LENGTH,
            },
        },
    }


def _metafields_schema(owner_description: str) -> dict[str, Any]:
    return {
        "type": "array",
        "title": "Metafields",
        "description": f"Between 1 and {MAX_METAFIELDS_PER_CALL} metafields to set.",
        "minItems": MIN_BATCH_ITEMS,
        "maxItems": MAX_METAFIELDS_PER_CALL,
        "items": _metafield_entry_schema(owner_description),
        "_required": True,
    }


def _catalog_metafields_schema() -> dict[str, Any]:
    return _metafields_schema("A Product or ProductVariant id.")


def _order_metafields_schema() -> dict[str, Any]:
    return _metafields_schema("An Order id.")


_TRACKING_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "Tracking",
    "description": "Carrier and tracking details. At least one field must be present.",
    "additionalProperties": False,
    "properties": {
        "company": {"type": "string", "minLength": 1, "maxLength": MAX_TRACKING_TEXT_LENGTH},
        "numbers": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_TRACKING_NUMBERS,
            "items": {"type": "string", "minLength": 1, "maxLength": MAX_TRACKING_TEXT_LENGTH},
        },
        "urls": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_TRACKING_NUMBERS,
            "items": {"type": "string", "minLength": 1, "maxLength": MAX_TRACKING_URL_LENGTH},
        },
    },
}

#: A tracking object must carry at least one of these.
TRACKING_FIELDS: tuple[str, ...] = ("company", "numbers", "urls")


_CAPABILITY_SCOPE_DETAILS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "scope_eligible",
        "required_oauth_scopes",
        "missing_required_oauth_scopes",
    ],
    "properties": {
        "scope_eligible": {"type": "boolean"},
        "required_oauth_scopes": {"type": "array", "items": {"type": "string"}},
        "missing_required_oauth_scopes": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}

_CAPABILITY_SCOPE_MATRIX_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": _CAPABILITY_SCOPE_DETAILS_SCHEMA,
}


def _first(
    title: str,
    description: str,
    *,
    maximum: int = MAX_PAGE_SIZE,
    default: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """The forward page-size input every paginated source publishes.

    ``maximum`` is per operation: Shopify refuses any single query whose
    requested cost exceeds 1000 points, so a wide record allows fewer per page.
    """
    return {
        "type": "integer",
        "title": title,
        "description": description,
        "minimum": 1,
        "maximum": maximum,
        "default": min(default, maximum),
    }


def _filter(example: str) -> dict[str, Any]:
    return {
        "type": "string",
        "title": "Shopify search query",
        "description": f"An optional Shopify search expression, for example {example}.",
        "minLength": 1,
        "maxLength": MAX_SEARCH_QUERY_LENGTH,
    }


def _sort_key(values: tuple[str, ...], default: str) -> dict[str, Any]:
    return {"type": "string", "title": "Sort by", "enum": list(values), "default": default}


_REVERSE: dict[str, Any] = {
    "type": "boolean",
    "title": "Reverse order",
    "description": "Return the results in reverse order.",
    "default": False,
}

_SAVED_SEARCH: dict[str, Any] = {
    **_GID_SCHEMA_BASE,
    "title": "Saved search id",
    "description": "A gid://shopify/SavedSearch/... id whose query to apply.",
}

_METAFIELD_NAMESPACE_FILTER: dict[str, Any] = {
    "type": "string",
    "title": "Namespace",
    "description": "Only metafields in this namespace.",
    "minLength": 1,
    "maxLength": MAX_METAFIELD_NAMESPACE_LENGTH,
}

_METAFIELD_KEYS_FILTER: dict[str, Any] = {
    "type": "array",
    "title": "Keys",
    "description": 'Only these metafields, each written "namespace.key".',
    "minItems": 1,
    "maxItems": MAX_PAGE_SIZE,
    "items": {"type": "string", "minLength": 3, "maxLength": 320},
}


def _after(description: str = _MESSAGE_THE_END_CURSOR_OF_THE_PREVIOUS_PAGE) -> dict[str, Any]:
    return {
        "type": "string",
        "title": _MESSAGE_AFTER_CURSOR,
        "description": description,
        "minLength": 1,
        "maxLength": MAX_CURSOR_LENGTH,
    }


def _gid(title: str, gid_type: str, *, required: bool = True) -> dict[str, Any]:
    entry: dict[str, Any] = {
        **_GID_SCHEMA_BASE,
        "title": title,
        "description": f"A gid://shopify/{gid_type}/... id.",
    }
    if required:
        entry["_required"] = True
    return entry


@dataclass(frozen=True)
class Output:
    """One published result field."""

    name: str
    value_type: str
    schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class UiField:
    """One step-builder input, derived from the operation's own input schema."""

    name: str
    label: str
    widget_type: str
    required: bool
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class Operation:
    """One typed, statically declared Shopify operation."""

    operation_id: str
    display_name: str
    description: str
    kind: str
    contacts_shopify: bool
    workflow_visible: bool
    input_schema: dict[str, Any]
    outputs: tuple[Output, ...]
    #: What this one call needs from the token. Owned per operation rather than
    #: per connection: a token scoped only for catalog work is a valid
    #: connection that simply cannot set stock.
    required_oauth_scopes: tuple[str, ...] = ()
    #: The host-visible kind of change an action makes. Empty for a source.
    effect_kind: str = ""
    extra_error_codes: tuple[str, ...] = ()

    @property
    def has_external_effect(self) -> bool:
        return self.kind == "action"

    def __post_init__(self) -> None:
        if self.has_external_effect and not self.effect_kind:  # pragma: no cover - packaging
            raise ValueError(f"{self.operation_id}: an action must declare an effect_kind")
        if not self.has_external_effect and self.effect_kind:  # pragma: no cover - packaging
            raise ValueError(f"{self.operation_id}: a source must not declare an effect_kind")

    @property
    def document(self) -> str | None:
        return DOCUMENTS.get(self.operation_id)

    @property
    def input_field_names(self) -> tuple[str, ...]:
        properties = self.input_schema.get("properties") or {}
        return tuple(properties)

    @property
    def required_input_field_names(self) -> tuple[str, ...]:
        return tuple(self.input_schema.get("required") or ())

    @property
    def result_fields(self) -> tuple[str, ...]:
        return tuple(output.name for output in self.outputs)

    @property
    def error_codes(self) -> tuple[str, ...]:
        base = (
            errors.TRANSPORT_ERROR_CODES
            if self.contacts_shopify
            else (
                errors.INVALID_PAYLOAD,
                errors.INVALID_CONFIGURATION,
                errors.UNSUPPORTED_OPERATION,
                errors.INTERNAL_ERROR,
            )
        )
        ordered = list(base)
        for code in self.extra_error_codes:
            if code not in ordered:
                ordered.append(code)
        return tuple(ordered)


def _connection_input(**properties: dict[str, Any]) -> dict[str, Any]:
    """One operation input object that always starts with ``connection_ref``.

    A property marked ``_required`` joins the schema's ``required`` list; the
    marker itself is stripped, so what is published is plain JSON Schema.
    """
    required = ["connection_ref"]
    published: dict[str, Any] = {"connection_ref": dict(_CONNECTION_REF_SCHEMA)}
    for name, spec in properties.items():
        declared = dict(spec)
        if declared.pop("_required", False):
            required.append(name)
        published[name] = declared
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": published,
    }


_EXTERNAL_EFFECT_OUTPUTS: tuple[Output, ...] = (
    Output("external_effect_status", "text", {"type": "string"}),
    Output("definitely_no_external_effect", "boolean", {"type": "boolean"}),
)


#: ``create_product`` mirrors Shopify's ``ProductSetInput`` for a new product.
#: ``status`` defaults to DRAFT: publishing stays a deliberate choice.
_PRODUCT_CREATE_FIELDS: dict[str, Any] = {
    "title": {**_TITLE_SCHEMA, "title": "Title", "_required": True},
    "handle": {
        **_HANDLE_SCHEMA,
        "title": "Handle",
        "description": (
            "The URL handle. Required here so a product is found again by a known handle; "
            "Shopify refuses one that is already taken."
        ),
        "_required": True,
    },
    **inputs.PRODUCT_COMMON_FIELDS,
    "tags": _TAGS_SCHEMA,
    "status": inputs.enum(
        inputs.PRODUCT_STATUSES,
        title="Status",
        description="DRAFT unless you choose otherwise. ACTIVE makes it sellable.",
        default="DRAFT",
    ),
    "gift_card": {"type": "boolean", "title": "Gift card"},
    "collection_ids": {**inputs.COLLECTION_IDS, "title": "Collections"},
    "combined_listing_role": inputs.enum(
        inputs.COMBINED_LISTING_ROLES, title="Combined listing role"
    ),
    "claim_ownership": inputs.obj(
        {"bundles": {"type": "boolean"}},
        title="Claim ownership",
        description="Claim this product for your app's bundles.",
    ),
    "metafields": inputs.metafields(
        inputs.NEW_METAFIELD_INPUT, "Metafields to set on the new product."
    ),
    "options": inputs.PRODUCT_OPTIONS,
    "variants": inputs.array(
        _VARIANT_SET_ITEM_SCHEMA,
        MAX_CREATE_VARIANTS,
        title="Variants",
        description=(
            "The variants to create with the product, each with its own SKU, price, barcode, "
            "weight and stock. Omit to get one variant built from the first value of each "
            "option. Without options, give at most one variant."
        ),
    ),
    "media": inputs.media(
        "Images, videos and 3D models by public URL or existing file id. Shopify processes "
        "them asynchronously; creation success does not mean they are READY."
    ),
    "image_files": inputs.IMAGE_FILES,
}
_CREATE_PRODUCT_INPUT_SCHEMA = _connection_input(**_PRODUCT_CREATE_FIELDS)

#: A row of ``create_products_bulk`` is a ``create_product`` input without the
#: connection and without artifact images, which a bulk row cannot carry.
_BULK_ROW_FIELDS = tuple(name for name in _PRODUCT_CREATE_FIELDS if name not in ("image_files",))

#: Shopify's own ``CreateMediaInput``: a URL, its kind and alt text.
_CREATE_MEDIA_SCHEMA: dict[str, Any] = inputs.array(
    inputs.obj(
        {
            "source_url": inputs.MEDIA_ITEM["properties"]["source_url"],
            "content_type": inputs.MEDIA_ITEM["properties"]["content_type"],
            "alt": inputs.text(512, title="Alt text"),
        },
        required=("source_url",),
    ),
    inputs.MAX_MEDIA_ITEMS,
    title="Media",
    description="Media to create from public URLs and attach. Processed asynchronously.",
)

#: ``update_product`` mirrors Shopify's ``ProductUpdateInput`` plus the media
#: and identifier arguments of ``productUpdate``.
_PRODUCT_UPDATE_FIELDS: dict[str, Any] = {
    "product_id": _gid(_MESSAGE_PRODUCT_ID, "Product", required=False),
    "product_handle": {
        **_HANDLE_SCHEMA,
        "title": "Product handle",
        "description": "Find the product by its handle instead of its id.",
    },
    "product_custom_id": inputs.obj(
        {
            "namespace": inputs.text(minimum=1),
            "key": inputs.text(minimum=1),
            "value": inputs.text(minimum=1),
        },
        required=("key", "value"),
        title="Product custom id",
        description="Find the product by a unique metafield value instead of its id.",
    ),
    "title": {**_TITLE_SCHEMA, "title": "Title"},
    "handle": {**_HANDLE_SCHEMA, "title": "Handle", "description": "A new URL handle."},
    "redirect_new_handle": {
        "type": "boolean",
        "title": "Redirect the old handle",
        "description": "Keep the old URL working when the handle changes. Default true.",
        "default": True,
    },
    **inputs.PRODUCT_COMMON_FIELDS,
    "replace_tags": {
        **_TAGS_SCHEMA,
        "title": "Replace tags",
        "description": "Replaces the product's entire tag list. Send [] to clear every tag.",
    },
    "status": inputs.enum(inputs.PRODUCT_STATUSES, title="Status"),
    "join_collection_ids": {**inputs.COLLECTION_IDS, "title": "Add to collections"},
    "leave_collection_ids": {**inputs.COLLECTION_IDS, "title": "Remove from collections"},
    "delete_conflicting_constrained_metafields": {
        "type": "boolean",
        "title": "Delete metafields the new category does not allow",
        "description": "Only with category_id. Default false: such metafields are kept and "
        "Shopify refuses the change instead.",
        "default": False,
    },
    "metafields": inputs.metafields(
        inputs.METAFIELD_INPUT, "Metafields to create or update on the product."
    ),
    "media": _CREATE_MEDIA_SCHEMA,
    "image_files": inputs.IMAGE_FILES,
}

#: Fields that say which product, or how, rather than what changes.
_PRODUCT_UPDATE_NON_CHANGE_FIELDS = frozenset(
    {
        "product_id",
        "product_handle",
        "product_custom_id",
        "redirect_new_handle",
        "delete_conflicting_constrained_metafields",
    }
)

#: Every field `update_product` may change. One of them must be present.
PRODUCT_UPDATE_CHANGE_FIELDS: tuple[str, ...] = tuple(
    name for name in _PRODUCT_UPDATE_FIELDS if name not in _PRODUCT_UPDATE_NON_CHANGE_FIELDS
)

#: The ways `update_product` can name its product. Exactly one is required.
PRODUCT_IDENTIFIER_FIELDS: tuple[str, ...] = ("product_id", "product_handle", "product_custom_id")

_BULK_PRODUCT_ITEM_SCHEMA = {
    **_CREATE_PRODUCT_INPUT_SCHEMA,
    "properties": {
        key: value
        for key, value in _CREATE_PRODUCT_INPUT_SCHEMA["properties"].items()
        if key in _BULK_ROW_FIELDS
    },
    "required": [
        key for key in _CREATE_PRODUCT_INPUT_SCHEMA["required"] if key != "connection_ref"
    ],
}
_BULK_OPERATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "status", "client_identifier"],
    "properties": {
        key: {"type": "string", "minLength": 1} for key in ["id", "status", "client_identifier"]
    },
}


_NOTIFY_CUSTOMER_SCHEMA: dict[str, Any] = {
    "type": "boolean",
    "title": "Notify the customer",
    "description": "Email the customer about this change. Default false.",
    "default": False,
}

_ADDRESS_INPUT_SCHEMA: dict[str, Any] = inputs.obj(
    {
        "first_name": inputs.text(),
        "last_name": inputs.text(),
        "company": inputs.text(),
        "address1": inputs.text(),
        "address2": inputs.text(),
        "city": inputs.text(),
        "province_code": inputs.text(8),
        "zip": inputs.text(32),
        "country_code": inputs.text(2, minimum=2),
        "phone": inputs.text(32),
    },
    title="Shipping address",
)

#: ``update_order_metadata`` mirrors Shopify's ``OrderInput``.
_ORDER_UPDATE_FIELDS: dict[str, Any] = {
    "order_id": _gid(_MESSAGE_ORDER_ID, "Order"),
    "note": {
        "type": "string",
        "title": "Note",
        "description": "Replaces the order note.",
        "maxLength": MAX_NOTE_LENGTH,
    },
    "po_number": {
        "type": "string",
        "title": "PO number",
        "description": "Replaces the purchase order number.",
        "maxLength": MAX_PO_NUMBER_LENGTH,
    },
    "replace_tags": {
        **_TAGS_SCHEMA,
        "title": "Replace tags",
        "description": "Replaces the order's entire tag list. Send [] to clear every tag.",
    },
    "replace_custom_attributes": {
        "type": "array",
        "title": "Replace custom attributes",
        "description": "Replaces the order's entire custom attribute list.",
        "maxItems": MAX_CUSTOM_ATTRIBUTES,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["key", "value"],
            "properties": {
                "key": {"type": "string", "minLength": 1, "maxLength": MAX_ATTRIBUTE_KEY_LENGTH},
                "value": {"type": "string", "maxLength": MAX_ATTRIBUTE_VALUE_LENGTH},
            },
        },
    },
    "email": {
        "type": "string",
        "title": "Contact email",
        "description": "The order's contact email. Needs Shopify's protected customer data access.",
        "minLength": 3,
        "maxLength": 320,
    },
    "phone": {
        "type": "string",
        "title": "Contact phone",
        "description": "The order's contact phone in E.164 format. Needs Shopify's protected "
        "customer data access.",
        "minLength": 3,
        "maxLength": 32,
    },
    "shipping_address": {
        **_ADDRESS_INPUT_SCHEMA,
        "description": "Replaces the shipping address. Needs Shopify's protected customer "
        "data access.",
    },
    "metafields": inputs.metafields(
        inputs.METAFIELD_INPUT, "Metafields to create or update on the order."
    ),
    "localized_fields": inputs.array(
        inputs.obj(
            {"key": inputs.text(64, minimum=1), "value": inputs.text(minimum=1)},
            required=("key", "value"),
        ),
        50,
        title="Localized fields",
        description="Country-specific fields such as TAX_CREDENTIAL_BR or SHIPPING_CREDENTIAL_MX.",
    ),
}

#: Every field `update_order_metadata` may change. One of them must be present.
ORDER_METADATA_CHANGE_FIELDS: tuple[str, ...] = tuple(
    name for name in _ORDER_UPDATE_FIELDS if name != "order_id"
)


#: Page ceilings that keep each query under Shopify's 1000-point single query
#: cost limit. ``tests/test_admin_api_coverage.py`` recomputes the requested
#: cost of every document at these ceilings and fails if one is exceeded.
MAX_PRODUCTS_PAGE = 200
MAX_INVENTORY_ITEMS_PAGE = 200
MAX_VARIANTS_PAGE = 100
MAX_MEDIA_PAGE = 150
MAX_ORDERS_PAGE = 15
MAX_LINE_ITEMS_PAGE = 40
MAX_FULFILLMENT_ORDERS_PAGE = 50
MAX_FULFILLMENT_ORDER_LINE_ITEMS = 100
MAX_FULFILLMENTS_PAGE = 50

#: Shopify's recommended product image size, in pixels on each side.
SHOPIFY_RECOMMENDED_IMAGE_SIZE = 2048

#: The catalog gaps `export_products` can look for. Each one is a reason a
#: product needs attention, reported by its code in the row's quality_issues.
QUALITY_FIELD_CHECKS: tuple[str, ...] = (
    "vendor",
    "product_type",
    "category",
    "tags",
    "seo_title",
    "seo_description",
    "sku",
    "barcode",
    "weight",
    "price",
)

_QUALITY_FILTER_SCHEMA: dict[str, Any] = inputs.obj(
    {
        "match": inputs.enum(
            ("any", "all"),
            title="Match",
            description="any: a product with at least one of the checked problems. all: only "
            "products with every checked problem.",
            default="any",
        ),
        "missing_images": {"type": "boolean", "title": "No images"},
        "min_image_width": {
            "type": "integer",
            "title": "Minimum image width",
            "description": "Flag any image narrower than this, in pixels. Shopify recommends "
            f"{SHOPIFY_RECOMMENDED_IMAGE_SIZE}.",
            "minimum": 1,
            "maximum": 20000,
        },
        "min_image_height": {
            "type": "integer",
            "title": "Minimum image height",
            "description": "Flag any image shorter than this, in pixels.",
            "minimum": 1,
            "maximum": 20000,
        },
        "below_recommended_image_size": {
            "type": "boolean",
            "title": "Images below Shopify's recommendation",
            "description": f"Flag any image smaller than {SHOPIFY_RECOMMENDED_IMAGE_SIZE} x "
            f"{SHOPIFY_RECOMMENDED_IMAGE_SIZE} px.",
        },
        "missing_image_alt_text": {"type": "boolean", "title": "Images without alt text"},
        "missing_description": {"type": "boolean", "title": "No description"},
        "min_description_length": {
            "type": "integer",
            "title": "Minimum description length",
            "description": "Flag a description shorter than this many characters of plain "
            "text (HTML tags are not counted).",
            "minimum": 1,
            "maximum": 65535,
        },
        "missing_fields": inputs.array(
            inputs.enum(QUALITY_FIELD_CHECKS),
            len(QUALITY_FIELD_CHECKS),
            minimum=1,
            title="Fields that must be filled",
            description="sku, barcode, weight and price are checked on every variant.",
        ),
    },
    title="Only products that need attention",
    description=(
        "Export only the products with catalog gaps — missing or small images, short "
        "descriptions, empty attributes — each with the list of what is wrong. Shopify's "
        "search cannot filter on these, so the whole matching catalog is read and checked."
    ),
)


OPERATIONS: tuple[Operation, ...] = (
    Operation(
        operation_id=VALIDATE_SETTINGS_OPERATION_ID,
        display_name="Check connection settings",
        description=(
            "Normalizes and checks the store address before the connection is saved, "
            "without contacting Shopify."
        ),
        kind="source",
        contacts_shopify=False,
        workflow_visible=False,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["shop_domain"],
            "properties": {
                "shop_domain": {
                    "type": "string",
                    "title": "Store address",
                    "description": "store-name or store-name.myshopify.com.",
                    "minLength": 1,
                    "maxLength": 255,
                }
            },
        },
        outputs=(
            Output("valid", "boolean", {"type": "boolean"}),
            Output("normalized_shop_domain", "text", {"type": "string"}),
        ),
    ),
    Operation(
        operation_id=TEST_CONNECTION_OPERATION_ID,
        display_name="Test the connection",
        description=(
            "Checks that the authorization still works and belongs to the connected store, "
            "then reports which operations its granted scopes allow."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(),
        outputs=(
            Output("shop_id", "text", {"type": ["string", "null"]}),
            Output("shop_name", "text", {"type": ["string", "null"]}),
            Output("myshopify_domain", "text", {"type": ["string", "null"]}),
            Output("api_version", "text", {"type": "string"}),
            Output("granted_scopes", "array", {"type": "array", "items": {"type": "string"}}),
            # A person reads the summary and IDs; a workflow reads the keyed matrix.
            Output("capability_summary", "text", {"type": "string"}),
            Output("capabilities", "array", {"type": "array", "items": {"type": "string"}}),
            Output("capability_scope_matrix", "object", _CAPABILITY_SCOPE_MATRIX_SCHEMA),
        ),
        extra_error_codes=(errors.SHOP_DOMAIN_MISMATCH,),
    ),
    Operation(
        operation_id="get_shop",
        display_name="Get the store",
        description=(
            "Returns the store's settings: identity, currency, timezone, units, tax and "
            "order-number settings."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(),
        outputs=(Output("shop", "object", models.SHOP),),
    ),
    Operation(
        operation_id="list_locations",
        display_name="List locations",
        description=(
            "Returns one cursor-paginated page of inventory locations. "
            "Pass end_cursor back as after to read the next page."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            first=_first(_MESSAGE_PAGE_SIZE, "How many locations to return, 1 to 250."),
            after=_after(),
            include_inactive={
                "type": "boolean",
                "title": "Include deactivated locations",
                "description": "Deactivated locations can no longer stock inventory.",
                "default": False,
            },
            include_legacy={
                "type": "boolean",
                "title": "Include legacy locations",
                "description": "Include locations of legacy fulfillment services.",
                "default": False,
            },
            filter=_filter('name:Warehouse or "active:true"'),
            sort_key=_sort_key(("ID", "NAME", "RELEVANCE"), "NAME"),
            reverse=_REVERSE,
        ),
        outputs=(
            Output("locations", "array", {"type": "array", "items": models.LOCATION}),
            Output("page_info", "object", _PAGE_INFO_SCHEMA),
        ),
        required_oauth_scopes=(scopes.WRITE_INVENTORY, scopes.READ_LOCATIONS),
    ),
    Operation(
        operation_id="list_inventory_items",
        display_name="List inventory items",
        description=(
            "Returns one cursor-paginated page of inventory items, optionally narrowed to "
            "one SKU or a search. Pass end_cursor back as after to read the next page."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            first=_first(
                _MESSAGE_PAGE_SIZE,
                f"How many inventory items to return, 1 to {MAX_INVENTORY_ITEMS_PAGE}.",
                maximum=MAX_INVENTORY_ITEMS_PAGE,
            ),
            after=_after(),
            sku={
                "type": "string",
                "title": "SKU",
                "description": (
                    "Narrow the page to this SKU. The value is sent to Shopify as a quoted "
                    "search term, so matching follows Shopify's own SKU search."
                ),
                "minLength": 1,
                "maxLength": MAX_SKU_LENGTH,
            },
            filter=_filter("tracked:true or updated_at:>2026-01-01"),
            reverse=_REVERSE,
        ),
        outputs=(
            Output("inventory_items", "array", {"type": "array", "items": models.INVENTORY_ITEM}),
            Output("page_info", "object", _PAGE_INFO_SCHEMA),
        ),
        required_oauth_scopes=(scopes.WRITE_INVENTORY,),
    ),
    Operation(
        operation_id="get_inventory_item",
        display_name="Get an inventory item",
        description="Returns one inventory item, found by its Shopify inventory item id.",
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            inventory_item_id={
                **_GID_SCHEMA_BASE,
                "title": "Inventory item id",
                "description": "A gid://shopify/InventoryItem/... id.",
                "_required": True,
            },
        ),
        outputs=(Output("inventory_item", "object", models.INVENTORY_ITEM),),
        required_oauth_scopes=(scopes.WRITE_INVENTORY,),
    ),
    Operation(
        operation_id="get_inventory_levels_batch",
        display_name="Get stock for many items at one location",
        description=(
            "Returns every quantity state — available, on hand, committed, incoming, reserved, "
            "damaged, safety stock and quality control — for up to 250 inventory items at "
            "one location, in the order they were asked for."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            location_id={
                **_GID_SCHEMA_BASE,
                "title": "Location id",
                "description": "A gid://shopify/Location/... id.",
                "_required": True,
            },
            inventory_item_ids={
                "type": "array",
                "title": "Inventory item ids",
                "description": "Between 1 and 250 distinct gid://shopify/InventoryItem/... ids.",
                "minItems": MIN_BATCH_ITEMS,
                "maxItems": MAX_BATCH_ITEMS,
                "items": dict(_GID_SCHEMA_BASE),
                "_required": True,
            },
            include_inactive={
                "type": "boolean",
                "title": "Include a deactivated location",
                "description": (
                    "When false, stock held at a deactivated location is reported as no level."
                ),
                "default": False,
            },
        ),
        outputs=(
            Output("location_id", "text", {"type": "string"}),
            Output("items", "array", {"type": "array", "items": _INVENTORY_LEVEL_ROW_SCHEMA}),
        ),
        # Narrower than the other two inventory reads on purpose: this one
        # selects a nested `InventoryLevel`, which `read_products` does not open.
        required_oauth_scopes=(scopes.WRITE_INVENTORY,),
    ),
    Operation(
        operation_id=SET_QUANTITIES_OPERATION_ID,
        display_name="Set stock quantities",
        description=(
            "Sets absolute available (or on-hand) quantities for 1 to 250 inventory items and "
            "waits for Shopify's answer. This changes what the store has in stock; a quantity "
            "of 0 makes the item out of stock at that location."
        ),
        kind="action",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            quantities={
                "type": "array",
                "title": "Quantities",
                "description": (
                    "Between 1 and 250 absolute quantities. Each entry names one inventory "
                    "item at one location."
                ),
                "minItems": MIN_BATCH_ITEMS,
                "maxItems": MAX_BATCH_ITEMS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "inventory_item_id",
                        "location_id",
                        "quantity",
                        "change_from_quantity",
                    ],
                    "properties": {
                        "inventory_item_id": {
                            **_GID_SCHEMA_BASE,
                            "title": "Inventory item id",
                            "description": "A gid://shopify/InventoryItem/... id.",
                        },
                        "location_id": {
                            **_GID_SCHEMA_BASE,
                            "title": "Location id",
                            "description": "A gid://shopify/Location/... id.",
                        },
                        "quantity": {
                            "type": "integer",
                            "title": "Quantity",
                            "description": (
                                "The absolute quantity to set, not a change. "
                                "0 makes the item out of stock at that location."
                            ),
                            "minimum": 0,
                            "maximum": MAX_QUANTITY,
                        },
                        "change_from_quantity": {
                            "type": ["integer", "null"],
                            "title": "Change from quantity",
                            "description": (
                                "The quantity you last read, so Shopify can refuse the write "
                                "if someone else changed it first. Send null to write "
                                "regardless."
                            ),
                            "minimum": 0,
                            "maximum": MAX_QUANTITY,
                        },
                    },
                },
                "_required": True,
            },
            name={
                "type": "string",
                "title": "Quantity state",
                "description": "available (default) or on_hand.",
                "enum": list(inputs.SET_QUANTITY_NAMES),
                "default": "available",
            },
            reason={
                "type": "string",
                "title": "Reason",
                "description": (
                    "Shopify's reason code, recorded on the adjustment: correction (default), "
                    "cycle_count_available, damaged, movement_created, movement_received, "
                    "movement_updated, movement_canceled, other, promotion, quality_control, "
                    "received, reservation_created, reservation_deleted, reservation_updated, "
                    "restock, safety_stock or shrinkage."
                ),
                "minLength": 1,
                "maxLength": 64,
                "default": "correction",
            },
        ),
        outputs=(
            Output("inventory_adjustment_group", "object", models.INVENTORY_ADJUSTMENT_GROUP),
            *_EXTERNAL_EFFECT_OUTPUTS,
        ),
        extra_error_codes=(errors.MISSING_IDEMPOTENCY_KEY, errors.TIMEOUT_UNKNOWN),
        required_oauth_scopes=(scopes.WRITE_INVENTORY,),
        effect_kind="shopify_inventory_set_quantities",
    ),
    # -- Catalog: products, variants, metafields and media -----------------
    Operation(
        operation_id="list_products",
        display_name="List products",
        description=(
            "Returns one cursor-paginated page of products. "
            "Pass end_cursor back as after to read the next page."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            first=_first(
                _MESSAGE_PAGE_SIZE,
                f"How many products to return, 1 to {MAX_PRODUCTS_PAGE}.",
                maximum=MAX_PRODUCTS_PAGE,
            ),
            after=_after(),
            filter=_filter("status:active, vendor:Acme, tag:summer, or category_id:sg-4-17"),
            sort_key=_sort_key(
                (
                    "CREATED_AT",
                    "ID",
                    "INVENTORY_TOTAL",
                    "PRODUCT_TYPE",
                    "PUBLISHED_AT",
                    "RELEVANCE",
                    "TITLE",
                    "UPDATED_AT",
                    "VENDOR",
                ),
                "ID",
            ),
            reverse=_REVERSE,
            saved_search_id=_SAVED_SEARCH,
        ),
        outputs=(
            Output("products", "array", {"type": "array", "items": models.PRODUCT}),
            Output("page_info", "object", models.PAGE_INFO),
        ),
        required_oauth_scopes=(scopes.WRITE_PRODUCTS,),
    ),
    Operation(
        operation_id="export_products",
        display_name="Export all matching products",
        description=(
            "Follows every Shopify product cursor and streams the complete matching catalog "
            "to a JSONL artifact. Use filter to export a subset, or quality_filter to export "
            "only products with missing or small images, short descriptions or empty fields."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            first=_first(
                "Page size",
                f"How many products to read per request, 1 to {MAX_PRODUCTS_PAGE}.",
                maximum=MAX_PRODUCTS_PAGE,
            ),
            include_images={
                "type": "boolean",
                "default": False,
                "title": "Include images",
                "description": "Export every image with URL, alt text, width and height, plus "
                "image_count. Adds paginated reads.",
            },
            include_variants={
                "type": "boolean",
                "default": False,
                "title": "Include variants",
                "description": "Export every variant record. Adds paginated reads.",
            },
            include_inventory={
                "type": "boolean",
                "default": False,
                "title": "Include inventory",
                "description": "Include variants automatically and export all inventory "
                "locations and quantities. Requires read_inventory or write_inventory, plus "
                "read_locations. Adds paginated reads.",
            },
            filter=_filter("status:active, vendor:Acme, tag:summer, or category_id:sg-4-17"),
            sort_key=_sort_key(
                (
                    "CREATED_AT",
                    "ID",
                    "INVENTORY_TOTAL",
                    "PRODUCT_TYPE",
                    "PUBLISHED_AT",
                    "RELEVANCE",
                    "TITLE",
                    "UPDATED_AT",
                    "VENDOR",
                ),
                "ID",
            ),
            reverse=_REVERSE,
            saved_search_id=_SAVED_SEARCH,
            quality_filter=_QUALITY_FILTER_SCHEMA,
        ),
        outputs=(
            Output("artifact_handle", "artifact_handle"),
            Output("filename", "text", {"type": "string"}),
            Output("content_type", "text", {"type": "string"}),
            Output("item_count", "integer", {"type": "integer", "minimum": 0}),
            Output("scanned_count", "integer", {"type": "integer", "minimum": 0}),
            Output("page_count", "integer", {"type": "integer", "minimum": 1}),
            Output("size_bytes", "integer", {"type": "integer", "minimum": 0}),
            Output("sha256", "text", {"type": "string"}),
            Output("artifacts", "object", {"type": "object"}),
        ),
        required_oauth_scopes=(scopes.WRITE_PRODUCTS,),
        extra_error_codes=(errors.ARTIFACT_OUTPUT_UNAVAILABLE,),
    ),
    Operation(
        operation_id="get_product",
        display_name="Get a product",
        description="Returns one product, found by its Shopify product id.",
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(product_id=_gid(_MESSAGE_PRODUCT_ID, "Product")),
        outputs=(Output("product", "object", models.PRODUCT),),
        required_oauth_scopes=(scopes.WRITE_PRODUCTS,),
    ),
    Operation(
        operation_id="list_product_variants",
        display_name="List product variants",
        description=(
            "Returns one cursor-paginated page of product variants across the store, "
            "optionally narrowed by a search such as product_id:123 or sku:ABC. "
            "Pass end_cursor back as after to read the next page."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            first=_first(
                _MESSAGE_PAGE_SIZE,
                f"How many variants to return, 1 to {MAX_VARIANTS_PAGE}.",
                maximum=MAX_VARIANTS_PAGE,
            ),
            after=_after(),
            filter=_filter("product_id:123, sku:ABC-1 or barcode:4006381333931"),
            sort_key=_sort_key(
                (
                    "FULL_TITLE",
                    "ID",
                    "INVENTORY_LEVELS_AVAILABLE",
                    "INVENTORY_MANAGEMENT",
                    "INVENTORY_POLICY",
                    "INVENTORY_QUANTITY",
                    "NAME",
                    "POPULAR",
                    "POSITION",
                    "RELEVANCE",
                    "SKU",
                    "TITLE",
                ),
                "ID",
            ),
            reverse=_REVERSE,
            saved_search_id=_SAVED_SEARCH,
        ),
        outputs=(
            Output("product_variants", "array", {"type": "array", "items": models.PRODUCT_VARIANT}),
            Output("page_info", "object", models.PAGE_INFO),
        ),
        required_oauth_scopes=(scopes.WRITE_PRODUCTS,),
    ),
    Operation(
        operation_id="get_product_variant",
        display_name="Get a product variant",
        description="Returns one product variant, found by its Shopify variant id.",
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            product_variant_id=_gid("Product variant id", "ProductVariant")
        ),
        outputs=(Output("product_variant", "object", models.PRODUCT_VARIANT),),
        required_oauth_scopes=(scopes.WRITE_PRODUCTS,),
    ),
    Operation(
        operation_id="list_catalog_metafields",
        display_name="List catalog metafields",
        description=(
            "Returns one cursor-paginated page of metafields for one product or one product "
            "variant, optionally narrowed to a namespace or named keys. The owner type must "
            "match the id."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            owner_type={
                "type": "string",
                "title": "Owner type",
                "description": "Which kind of record owns the metafields.",
                "enum": ["product", "product_variant"],
                "_required": True,
            },
            owner_id={
                **_GID_SCHEMA_BASE,
                "title": "Owner id",
                "description": "A Product or ProductVariant id matching the owner type.",
                "_required": True,
            },
            first=_first(_MESSAGE_PAGE_SIZE, "How many metafields to return, 1 to 250."),
            after=_after(),
            namespace=_METAFIELD_NAMESPACE_FILTER,
            keys=_METAFIELD_KEYS_FILTER,
            reverse=_REVERSE,
        ),
        outputs=(
            Output("owner_id", "text", {"type": "string"}),
            Output("owner_type", "text", {"type": "string"}),
            Output("metafields", "array", {"type": "array", "items": models.METAFIELD}),
            Output("page_info", "object", models.PAGE_INFO),
        ),
        required_oauth_scopes=(scopes.WRITE_PRODUCTS,),
    ),
    Operation(
        operation_id="list_product_media",
        display_name="List product media",
        description=(
            "Returns one cursor-paginated page of the media attached to one product: images "
            "with their URL, width and height, videos and 3D models, with processing status "
            "and any processing errors."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            product_id=_gid(_MESSAGE_PRODUCT_ID, "Product"),
            first=_first(
                _MESSAGE_PAGE_SIZE,
                f"How many media items to return, 1 to {MAX_MEDIA_PAGE}.",
                maximum=MAX_MEDIA_PAGE,
            ),
            after=_after(),
            filter=_filter("media_type:IMAGE"),
            sort_key=_sort_key(("ID", "POSITION"), "POSITION"),
            reverse=_REVERSE,
        ),
        outputs=(
            Output("product_id", "text", {"type": "string"}),
            Output("media", "array", {"type": "array", "items": models.PRODUCT_MEDIA}),
            Output("page_info", "object", models.PAGE_INFO),
        ),
        required_oauth_scopes=(scopes.WRITE_PRODUCTS,),
    ),
    Operation(
        operation_id="create_product",
        display_name="Create a product",
        description=(
            "Creates one product with its variants in a single atomic Shopify call: SKU, "
            "price, barcode, weight, starting stock, images and metafields included. The "
            "product is a DRAFT unless status says otherwise. Images come from public URLs, "
            "existing Shopify files or Flow Steward artifacts and are processed "
            "asynchronously. product_variants returns every created variant with its "
            "inventory item."
        ),
        kind="action",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_CREATE_PRODUCT_INPUT_SCHEMA,
        outputs=(
            Output("product", "object", models.NULLABLE_PRODUCT),
            Output(
                "product_variants",
                "array",
                {
                    "type": "array",
                    "maxItems": MAX_CREATE_VARIANTS,
                    "items": models.INITIAL_PRODUCT_VARIANT,
                },
            ),
            *_EXTERNAL_EFFECT_OUTPUTS,
        ),
        required_oauth_scopes=(scopes.WRITE_PRODUCTS,),
        effect_kind="shopify_product_create",
        extra_error_codes=(errors.MISSING_IDEMPOTENCY_KEY, errors.TIMEOUT_UNKNOWN),
    ),
    Operation(
        operation_id="create_products_bulk",
        display_name="Create products in bulk",
        description=(
            "Uploads a batch of new products for asynchronous creation. Each row takes the "
            "same fields as create_product, variants included, except image_files: use media "
            "URLs. Supply either products or a JSONL artifact. Submission success is not "
            "per-row success; Shopify continues processing after this action returns."
        ),
        kind="action",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            products={
                "type": "array",
                "title": "Products",
                "minItems": 1,
                "maxItems": 10000,
                "items": _BULK_PRODUCT_ITEM_SCHEMA,
                "description": "New products using create_product fields, without "
                "connection_ref and image_files. Use a JSONL artifact for large batches.",
            },
            artifact_handle={
                "type": "string",
                "title": "Products JSONL artifact",
                "minLength": 1,
                "maxLength": 512,
                "description": "One product per line using create_product fields. Mutually "
                "exclusive with products. Maximum 10000 products and 100 MB.",
            },
        ),
        outputs=(
            Output(
                "bulk_operation", "object", {**_BULK_OPERATION_SCHEMA, "type": ["object", "null"]}
            ),
            Output("item_count", "integer", {"type": "integer", "minimum": 0}),
            *_EXTERNAL_EFFECT_OUTPUTS,
        ),
        required_oauth_scopes=(scopes.WRITE_PRODUCTS,),
        effect_kind="shopify_product_bulk_create",
        extra_error_codes=(errors.MISSING_IDEMPOTENCY_KEY, errors.TIMEOUT_UNKNOWN),
    ),
    Operation(
        operation_id="update_product",
        display_name="Update a product",
        description=(
            "Changes one product, found by id, handle or a unique metafield. Only the fields "
            "you supply are sent; everything else is left as it is. replace_tags overwrites "
            "the whole tag list. New images can be attached from URLs or Flow Steward "
            "artifacts."
        ),
        kind="action",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(**_PRODUCT_UPDATE_FIELDS),
        outputs=(
            Output("product", "object", models.NULLABLE_PRODUCT),
            *_EXTERNAL_EFFECT_OUTPUTS,
        ),
        required_oauth_scopes=(scopes.WRITE_PRODUCTS,),
        effect_kind="shopify_product_update",
        extra_error_codes=(errors.MISSING_IDEMPOTENCY_KEY, errors.TIMEOUT_UNKNOWN),
    ),
    Operation(
        operation_id="create_product_variants_batch",
        display_name="Create product variants",
        description=(
            "Creates 1 to 250 variants on one product in a single call. The product's options "
            "must already exist. By default the product's standalone variant is preserved."
        ),
        kind="action",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            product_id=_gid(_MESSAGE_PRODUCT_ID, "Product"),
            variants={
                "type": "array",
                "title": "Variants",
                "description": "Between 1 and 250 variants to create.",
                "minItems": MIN_BATCH_ITEMS,
                "maxItems": MAX_BATCH_ITEMS,
                "items": _VARIANT_CREATE_ITEM_SCHEMA,
                "_required": True,
            },
            media=_CREATE_MEDIA_SCHEMA,
            strategy={
                "type": "string",
                "title": "Standalone variant",
                "description": (
                    "PRESERVE_STANDALONE_VARIANT (default) keeps the product's default "
                    "variant; REMOVE_STANDALONE_VARIANT deletes it; DEFAULT follows Shopify."
                ),
                "enum": ["DEFAULT", "REMOVE_STANDALONE_VARIANT", "PRESERVE_STANDALONE_VARIANT"],
                "default": "PRESERVE_STANDALONE_VARIANT",
            },
        ),
        outputs=(
            Output("product_variants", "array", {"type": "array", "items": models.PRODUCT_VARIANT}),
            *_EXTERNAL_EFFECT_OUTPUTS,
        ),
        required_oauth_scopes=(scopes.WRITE_PRODUCTS,),
        effect_kind="shopify_product_variants_create",
        extra_error_codes=(errors.MISSING_IDEMPOTENCY_KEY, errors.TIMEOUT_UNKNOWN),
    ),
    Operation(
        operation_id="update_product_variants_batch",
        display_name="Update product variants",
        description=(
            "Changes 1 to 250 existing variants on one product in a single call. By default "
            "Shopify applies all of them or none. Each entry must name a variant and carry at "
            "least one actual change."
        ),
        kind="action",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            product_id=_gid(_MESSAGE_PRODUCT_ID, "Product"),
            variants={
                "type": "array",
                "title": "Variants",
                "description": "Between 1 and 250 variants to change.",
                "minItems": MIN_BATCH_ITEMS,
                "maxItems": MAX_BATCH_ITEMS,
                "items": _VARIANT_UPDATE_ITEM_SCHEMA,
                "_required": True,
            },
            media=_CREATE_MEDIA_SCHEMA,
            allow_partial_updates={
                "type": "boolean",
                "title": "Allow partial updates",
                "description": "false (default): all variants change or none do.",
                "default": False,
            },
        ),
        outputs=(
            Output("product_variants", "array", {"type": "array", "items": models.PRODUCT_VARIANT}),
            *_EXTERNAL_EFFECT_OUTPUTS,
        ),
        required_oauth_scopes=(scopes.WRITE_PRODUCTS,),
        effect_kind="shopify_product_variants_update",
        extra_error_codes=(errors.MISSING_IDEMPOTENCY_KEY, errors.TIMEOUT_UNKNOWN),
    ),
    Operation(
        operation_id="set_catalog_metafields",
        display_name="Set catalog metafields",
        description=(
            "Creates or updates 1 to 25 metafields on products and product variants in one "
            "atomic call. Every entry carries a compare digest, so a value someone else changed "
            "since you read it is refused rather than overwritten."
        ),
        kind="action",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(metafields=_catalog_metafields_schema()),
        outputs=(
            Output("metafields", "array", {"type": "array", "items": models.METAFIELD}),
            *_EXTERNAL_EFFECT_OUTPUTS,
        ),
        required_oauth_scopes=(scopes.WRITE_PRODUCTS,),
        effect_kind="shopify_catalog_metafields_set",
        extra_error_codes=(errors.MISSING_IDEMPOTENCY_KEY, errors.TIMEOUT_UNKNOWN),
    ),
    Operation(
        operation_id="update_product_media",
        display_name="Update a media file",
        description=(
            "Changes one existing file in Shopify Files: its alt text, its source (replacing "
            "the file), its preview image, its filename, and which products it is attached to."
        ),
        kind="action",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            media_id={
                **_GID_SCHEMA_BASE,
                "title": "Media id",
                "description": "A MediaImage, Video, Model3d, ExternalVideo or GenericFile id.",
                "_required": True,
            },
            alt={
                "type": "string",
                "title": "Alt text",
                "description": "The replacement alt text.",
                "maxLength": MAX_ALT_LENGTH,
            },
            source_url={
                **inputs.MEDIA_ITEM["properties"]["source_url"],
                "title": "Replacement source URL",
                "description": "A public https:// URL to replace the file's content with.",
            },
            preview_image_url={
                **inputs.MEDIA_ITEM["properties"]["source_url"],
                "title": "Preview image URL",
                "description": "A public https:// image URL to use as the file's preview.",
            },
            filename={"type": "string", "title": "Filename", "minLength": 1, "maxLength": 255},
            add_to_product_ids={
                **inputs.array(dict(_GID_SCHEMA_BASE), MAX_BATCH_ITEMS, minimum=1),
                "title": "Attach to products",
            },
            remove_from_product_ids={
                **inputs.array(dict(_GID_SCHEMA_BASE), MAX_BATCH_ITEMS, minimum=1),
                "title": "Detach from products",
            },
        ),
        outputs=(
            Output("file", "object", models.NULLABLE_FILE),
            *_EXTERNAL_EFFECT_OUTPUTS,
        ),
        required_oauth_scopes=(scopes.WRITE_FILES,),
        effect_kind="shopify_product_media_update",
        extra_error_codes=(errors.MISSING_IDEMPOTENCY_KEY, errors.TIMEOUT_UNKNOWN),
    ),
    # -- Orders, fulfillment orders and fulfillments -----------------------
    Operation(
        operation_id="list_orders",
        display_name="List orders",
        description=(
            "Returns one cursor-paginated page of orders, optionally filtered and sorted. "
            "Customer names, emails, phone numbers and addresses are never requested."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            first=_first(
                _MESSAGE_PAGE_SIZE,
                f"How many orders to return, 1 to {MAX_ORDERS_PAGE}.",
                maximum=MAX_ORDERS_PAGE,
            ),
            after=_after(),
            filter=_filter(
                "financial_status:paid, fulfillment_status:unfulfilled, "
                "created_at:>2026-01-01 or tag:wholesale"
            ),
            sort_key=_sort_key(
                (
                    "CREATED_AT",
                    "CURRENT_TOTAL_PRICE",
                    "CUSTOMER_NAME",
                    "DESTINATION",
                    "FINANCIAL_STATUS",
                    "FULFILLMENT_STATUS",
                    "ID",
                    "ORDER_NUMBER",
                    "PO_NUMBER",
                    "PROCESSED_AT",
                    "RELEVANCE",
                    "TOTAL_ITEMS_QUANTITY",
                    "TOTAL_PRICE",
                    "UPDATED_AT",
                ),
                "ID",
            ),
            reverse=_REVERSE,
            saved_search_id=_SAVED_SEARCH,
        ),
        outputs=(
            Output("orders", "array", {"type": "array", "items": models.ORDER}),
            Output("page_info", "object", models.PAGE_INFO),
        ),
        required_oauth_scopes=(scopes.WRITE_ORDERS,),
    ),
    Operation(
        operation_id="get_order",
        display_name="Get an order",
        description=(
            "Returns one order, found by its Shopify order id. Customer names, emails, phone "
            "numbers and addresses are never requested."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(order_id=_gid(_MESSAGE_ORDER_ID, "Order")),
        outputs=(Output("order", "object", models.ORDER),),
        required_oauth_scopes=(scopes.WRITE_ORDERS,),
    ),
    Operation(
        operation_id="list_order_line_items",
        display_name="List order line items",
        description="Returns one cursor-paginated page of the line items on one order.",
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            order_id=_gid(_MESSAGE_ORDER_ID, "Order"),
            first=_first(
                _MESSAGE_PAGE_SIZE,
                f"How many line items to return, 1 to {MAX_LINE_ITEMS_PAGE}.",
                maximum=MAX_LINE_ITEMS_PAGE,
            ),
            after=_after(),
            reverse=_REVERSE,
        ),
        outputs=(
            Output("order_id", "text", {"type": "string"}),
            Output("line_items", "array", {"type": "array", "items": models.ORDER_LINE_ITEM}),
            Output("page_info", "object", models.PAGE_INFO),
        ),
        required_oauth_scopes=(scopes.WRITE_ORDERS,),
    ),
    Operation(
        operation_id="list_order_metafields",
        display_name="List order metafields",
        description=(
            "Returns one cursor-paginated page of the metafields on one order, optionally "
            "narrowed to a namespace or named keys."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            order_id=_gid(_MESSAGE_ORDER_ID, "Order"),
            first=_first(_MESSAGE_PAGE_SIZE, "How many metafields to return, 1 to 250."),
            after=_after(),
            namespace=_METAFIELD_NAMESPACE_FILTER,
            keys=_METAFIELD_KEYS_FILTER,
            reverse=_REVERSE,
        ),
        outputs=(
            Output("order_id", "text", {"type": "string"}),
            Output("metafields", "array", {"type": "array", "items": models.METAFIELD}),
            Output("page_info", "object", models.PAGE_INFO),
        ),
        required_oauth_scopes=(scopes.WRITE_ORDERS,),
    ),
    Operation(
        operation_id="list_order_fulfillment_orders",
        display_name="List fulfillment orders",
        description=(
            "Returns one cursor-paginated page of the fulfillment orders on one order, each "
            "with an explicitly sized page of its own line items. first multiplied by "
            "line_items_first is bounded so the request stays within Shopify's cost limit."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            order_id=_gid(_MESSAGE_ORDER_ID, "Order"),
            first=_first(
                _MESSAGE_PAGE_SIZE,
                f"How many fulfillment orders to return, 1 to {MAX_FULFILLMENT_ORDERS_PAGE}.",
                maximum=MAX_FULFILLMENT_ORDERS_PAGE,
                default=10,
            ),
            after=_after(),
            line_items_first=_first(
                "Line items per fulfillment order",
                "How many line items to return inside each fulfillment order, 1 to "
                f"{MAX_FULFILLMENT_ORDER_LINE_ITEMS}.",
                maximum=MAX_FULFILLMENT_ORDER_LINE_ITEMS,
                default=20,
            ),
            reverse=_REVERSE,
            displayable={
                "type": "boolean",
                "title": "Only displayable",
                "description": "Only fulfillment orders a merchant can see and act on.",
                "default": False,
            },
            filter=_filter("status:open or assigned_location_id:123"),
        ),
        outputs=(
            Output("order_id", "text", {"type": "string"}),
            Output(
                "fulfillment_orders", "array", {"type": "array", "items": models.FULFILLMENT_ORDER}
            ),
            Output("page_info", "object", models.PAGE_INFO),
        ),
        required_oauth_scopes=(
            scopes.WRITE_ORDERS,
            *scopes.FULFILLMENT_ORDER_WRITE_SCOPES,
        ),
    ),
    Operation(
        operation_id="get_fulfillment_order",
        display_name="Get a fulfillment order",
        description=(
            "Returns one fulfillment order with an explicitly paginated page of its line items."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            fulfillment_order_id=_gid("Fulfillment order id", "FulfillmentOrder"),
            line_items_first=_first(
                "Line items page size", "How many line items to return, 1 to 250."
            ),
            line_items_after=_after("The line_items_page_info end_cursor of the previous page."),
        ),
        outputs=(Output("fulfillment_order", "object", models.FULFILLMENT_ORDER),),
        required_oauth_scopes=(
            scopes.WRITE_ORDERS,
            *scopes.FULFILLMENT_ORDER_WRITE_SCOPES,
        ),
    ),
    Operation(
        operation_id="list_order_fulfillments",
        display_name="List order fulfillments",
        description=(
            f"Returns up to {MAX_FULFILLMENTS_PAGE} of an order's fulfillments plus the "
            "store's own total, so a caller can tell a complete answer from a partial one."
        ),
        kind="source",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            order_id=_gid(_MESSAGE_ORDER_ID, "Order"),
            first=_first(
                _MESSAGE_PAGE_SIZE,
                f"How many fulfillments to return, 1 to {MAX_FULFILLMENTS_PAGE}.",
                maximum=MAX_FULFILLMENTS_PAGE,
            ),
            filter=_filter("status:success"),
        ),
        outputs=(
            Output("order_id", "text", {"type": "string"}),
            Output("fulfillments", "array", {"type": "array", "items": models.FULFILLMENT}),
            Output("total_count", "integer", {"type": ["integer", "null"]}),
            Output("truncated", "boolean", {"type": "boolean"}),
        ),
        required_oauth_scopes=(scopes.WRITE_ORDERS,),
    ),
    Operation(
        operation_id="update_order_metadata",
        display_name="Update an order",
        description=(
            "Changes what Shopify lets an app edit on an existing order: note, PO number, "
            "tags, custom attributes, metafields, contact email and phone, shipping address "
            "and localized fields. The replace_ fields overwrite their whole list. Line items, "
            "payments, refunds and order edits are out of reach here."
        ),
        kind="action",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(**_ORDER_UPDATE_FIELDS),
        outputs=(
            Output("order", "object", models.NULLABLE_ORDER),
            *_EXTERNAL_EFFECT_OUTPUTS,
        ),
        required_oauth_scopes=(scopes.WRITE_ORDERS,),
        effect_kind="shopify_order_metadata_update",
        extra_error_codes=(errors.MISSING_IDEMPOTENCY_KEY, errors.TIMEOUT_UNKNOWN),
    ),
    Operation(
        operation_id="set_order_metafields",
        display_name="Set order metafields",
        description=(
            "Creates or updates 1 to 25 metafields on orders in one atomic call, with the same "
            "compare-and-set protection as the catalog operation."
        ),
        kind="action",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(metafields=_order_metafields_schema()),
        outputs=(
            Output("metafields", "array", {"type": "array", "items": models.METAFIELD}),
            *_EXTERNAL_EFFECT_OUTPUTS,
        ),
        required_oauth_scopes=(scopes.WRITE_ORDERS,),
        effect_kind="shopify_order_metafields_set",
        extra_error_codes=(errors.MISSING_IDEMPOTENCY_KEY, errors.TIMEOUT_UNKNOWN),
    ),
    Operation(
        operation_id="create_fulfillment",
        display_name="Create a fulfillment",
        description=(
            "Fulfills named line items on named fulfillment orders. Every line item and "
            "quantity must be stated: Shopify would otherwise fulfil everything remaining, and "
            "that is not a decision an omitted field should make. The customer is notified "
            "only when notify_customer is true."
        ),
        kind="action",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            fulfillment_orders={
                "type": "array",
                "title": "Fulfillment orders",
                "description": (
                    "The fulfillment orders to fulfil, each with its explicit line items."
                ),
                "minItems": MIN_BATCH_ITEMS,
                "maxItems": MAX_FULFILLMENT_ORDERS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["fulfillment_order_id", "line_items"],
                    "properties": {
                        "fulfillment_order_id": dict(_GID_SCHEMA_BASE),
                        "line_items": {
                            "type": "array",
                            "minItems": MIN_BATCH_ITEMS,
                            "maxItems": MAX_FULFILLMENT_LINE_ITEMS,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["fulfillment_order_line_item_id", "quantity"],
                                "properties": {
                                    "fulfillment_order_line_item_id": dict(_GID_SCHEMA_BASE),
                                    "quantity": {
                                        "type": "integer",
                                        "minimum": 1,
                                        "maximum": MAX_QUANTITY,
                                    },
                                },
                            },
                        },
                    },
                },
                "_required": True,
            },
            tracking=_TRACKING_INPUT_SCHEMA,
            notify_customer=_NOTIFY_CUSTOMER_SCHEMA,
            origin_address=inputs.obj(
                {
                    "address1": inputs.text(),
                    "address2": inputs.text(),
                    "city": inputs.text(),
                    "zip": inputs.text(32),
                    "province_code": inputs.text(8),
                    "country_code": inputs.text(2, minimum=2),
                },
                required=("country_code",),
                title="Shipped from",
                description="The address the goods leave from, if not the assigned location.",
            ),
            message={
                "type": "string",
                "title": "Message",
                "description": "A note recorded with the fulfillment.",
                "minLength": 1,
                "maxLength": MAX_NOTE_LENGTH,
            },
        ),
        outputs=(
            Output("fulfillment", "object", models.NULLABLE_FULFILLMENT),
            *_EXTERNAL_EFFECT_OUTPUTS,
        ),
        required_oauth_scopes=scopes.FULFILLMENT_ORDER_WRITE_SCOPES,
        effect_kind="shopify_fulfillment_create",
        extra_error_codes=(errors.MISSING_IDEMPOTENCY_KEY, errors.TIMEOUT_UNKNOWN),
    ),
    Operation(
        operation_id="update_fulfillment_tracking",
        display_name="Update fulfillment tracking",
        description=(
            "Replaces the tracking information on one existing fulfillment. At least one "
            "tracking value is required: this operation cannot be used to clear tracking. The "
            "customer is notified only when notify_customer is true."
        ),
        kind="action",
        contacts_shopify=True,
        workflow_visible=True,
        input_schema=_connection_input(
            fulfillment_id=_gid("Fulfillment id", "Fulfillment"),
            tracking={**_TRACKING_INPUT_SCHEMA, "_required": True},
            notify_customer=_NOTIFY_CUSTOMER_SCHEMA,
        ),
        outputs=(
            Output("fulfillment", "object", models.NULLABLE_FULFILLMENT),
            *_EXTERNAL_EFFECT_OUTPUTS,
        ),
        required_oauth_scopes=scopes.FULFILLMENT_ORDER_WRITE_SCOPES,
        effect_kind="shopify_fulfillment_tracking_update",
        extra_error_codes=(errors.MISSING_IDEMPOTENCY_KEY, errors.TIMEOUT_UNKNOWN),
    ),
)

OPERATIONS_BY_ID: dict[str, Operation] = {row.operation_id: row for row in OPERATIONS}
OPERATION_IDS: tuple[str, ...] = tuple(OPERATIONS_BY_ID)
NETWORK_OPERATION_IDS: tuple[str, ...] = tuple(
    row.operation_id for row in OPERATIONS if row.contacts_shopify
)
ACTION_OPERATION_IDS: tuple[str, ...] = tuple(
    row.operation_id for row in OPERATIONS if row.kind == "action"
)


def operation(operation_id: Any) -> Operation | None:
    """The declared row for ``operation_id``, or ``None``."""
    if not isinstance(operation_id, str):
        return None
    return OPERATIONS_BY_ID.get(operation_id)


def connection_type_for(row: Operation) -> str:
    """The connection type an operation binds to, if it needs one."""
    return CONNECTION_TYPE_ID if "connection_ref" in row.input_field_names else ""


def _ui_widget(spec: Mapping[str, Any]) -> str:
    declared = spec.get("type")
    types = [declared] if isinstance(declared, str) else list(declared or [])
    if "array" in types or "object" in types:
        return "json"
    if "boolean" in types:
        return "boolean"
    if "integer" in types or "number" in types:
        return "number"
    return "text"


def ui_fields(row: Operation) -> tuple[UiField, ...]:
    """The step-builder fields for one operation, derived from its input schema.

    ``connection_ref`` is excluded: the platform renders the connection picker
    itself from the operation's declared connection type.
    """
    properties = row.input_schema.get("properties") or {}
    required = set(row.required_input_field_names)
    fields: list[UiField] = []
    for name, spec in properties.items():
        if name == "connection_ref" or not isinstance(spec, Mapping):
            continue
        fields.append(
            UiField(
                name=name,
                label=str(spec.get("title") or name.replace("_", " ").capitalize()),
                widget_type=_ui_widget(spec),
                required=name in required,
            )
        )
    return tuple(fields)


__all__ = [
    "ACTION_OPERATION_IDS",
    "CATEGORY",
    "CHANNEL",
    "DEFAULT_PAGE_SIZE",
    "MAX_BATCH_ITEMS",
    "MAX_CREATE_VARIANTS",
    "MAX_PAGE_SIZE",
    "MAX_QUANTITY",
    "MIN_BATCH_ITEMS",
    "NETWORK_OPERATION_IDS",
    "OPERATIONS",
    "OPERATIONS_BY_ID",
    "OPERATION_IDS",
    "ORDER_METADATA_CHANGE_FIELDS",
    "PRODUCT_IDENTIFIER_FIELDS",
    "PRODUCT_UPDATE_CHANGE_FIELDS",
    "QUALITY_FIELD_CHECKS",
    "SET_QUANTITIES_OPERATION_ID",
    "SHOPIFY_RECOMMENDED_IMAGE_SIZE",
    "TEST_CONNECTION_OPERATION_ID",
    "VALIDATE_SETTINGS_OPERATION_ID",
    "VARIANT_UPDATE_CHANGE_FIELDS",
    "Operation",
    "Output",
    "UiField",
    "connection_type_for",
    "operation",
    "ui_fields",
]
