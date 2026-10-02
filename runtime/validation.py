"""Operation-specific input validation, applied before any outbound I/O.

Two layers, in this order:

1. The operation's own published JSON Schema is executed as written
   (:mod:`runtime.schema`). Shapes, required fields — nested ones included —
   bounds and unknown-field rejection all come from the contract itself, so
   ``quantities: [{}]`` fails here rather than at Shopify.
2. The rules a JSON Schema in the platform's executable subset cannot express:
   which Shopify id type belongs in which field, and that a batch does not name
   the same inventory item at the same location twice.

Only then are defaults applied and the typed input handed to the operation.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from . import catalog, errors, gids, schema
from .catalog import DEFAULT_PAGE_SIZE, Operation
from .errors import ExtensionError

MAX_EXTERNAL_EFFECT_ID_LENGTH = 128

#: The host's external effect id becomes both Shopify's idempotency key and the
#: last segment of the reference document URI, so it is held to a character set
#: that is safe in both.
_EXTERNAL_EFFECT_ID_RE = re.compile(
    rf"^[A-Za-z0-9][A-Za-z0-9._-]{{0,{MAX_EXTERNAL_EFFECT_ID_LENGTH - 1}}}$"
)

#: The id fields each operation declares, and the Shopify type each one carries.
_GID_FIELDS: dict[str, dict[str, str]] = {
    "get_inventory_item": {"inventory_item_id": gids.INVENTORY_ITEM},
    "get_inventory_levels_batch": {"location_id": gids.LOCATION},
    "get_product": {"product_id": gids.PRODUCT},
    "get_product_variant": {"product_variant_id": gids.PRODUCT_VARIANT},
    "list_product_media": {"product_id": gids.PRODUCT},
    "create_product": {"category_id": gids.TAXONOMY_CATEGORY},
    "update_product": {"product_id": gids.PRODUCT, "category_id": gids.TAXONOMY_CATEGORY},
    "create_product_variants_batch": {"product_id": gids.PRODUCT},
    "update_product_variants_batch": {"product_id": gids.PRODUCT},
    "get_order": {"order_id": gids.ORDER},
    "list_order_line_items": {"order_id": gids.ORDER},
    "list_order_metafields": {"order_id": gids.ORDER},
    "list_order_fulfillment_orders": {"order_id": gids.ORDER},
    "list_order_fulfillments": {"order_id": gids.ORDER},
    "get_fulfillment_order": {"fulfillment_order_id": gids.FULFILLMENT_ORDER},
    "update_order_metadata": {"order_id": gids.ORDER},
    "update_fulfillment_tracking": {"fulfillment_id": gids.FULFILLMENT},
}

#: List-of-id fields, and the type every element carries.
_GID_LIST_FIELDS: dict[str, dict[str, str]] = {
    "get_inventory_levels_batch": {"inventory_item_ids": gids.INVENTORY_ITEM},
}

#: The metafield owner types each set operation may address.
_METAFIELD_OWNER_TYPES: dict[str, tuple[str, ...]] = {
    "set_catalog_metafields": (gids.PRODUCT, gids.PRODUCT_VARIANT),
    "set_order_metafields": (gids.ORDER,),
}

#: A decimal amount as Shopify sends and accepts it: digits, one optional
#: decimal point, optional leading minus. Kept as text end to end, because
#: turning "19.99" into a binary float and back is how a price quietly moves.
_DECIMAL_RE = re.compile(r"^-?(?:0|[1-9](?a:\d){0,14})(?:\.(?a:\d){1,6})?$")

#: Tracking URLs, like creation image sources, are forwarded to Shopify rather
#: than fetched by the extension. HTTPS only, so a
#: merchant-visible link cannot be plain http.
_TRACKING_URL_RE = re.compile(r"^https://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{1,2040}$")


def validated_input(row: Operation, raw_input: Any) -> dict[str, Any]:
    """Return the typed input for one operation, or refuse the invocation."""
    if not isinstance(raw_input, Mapping):
        raise ExtensionError(errors.INVALID_PAYLOAD, "The operation input contract is invalid")
    payload = dict(raw_input)
    schema.validate(payload, row.input_schema)

    for name, gid_type in _GID_FIELDS.get(row.operation_id, {}).items():
        if name in payload:
            payload[name] = gids.gid(payload[name], expected_type=gid_type, field=name)
    for name, gid_type in _GID_LIST_FIELDS.get(row.operation_id, {}).items():
        if name in payload:
            payload[name] = _unique_gids(payload[name], expected_type=gid_type, field=name)
    if row.operation_id in _METAFIELD_OWNER_TYPES:
        payload["metafields"] = _metafields(
            payload.get("metafields"), owners=_METAFIELD_OWNER_TYPES[row.operation_id]
        )
    rule = _SEMANTIC_RULES.get(row.operation_id)
    if rule is not None:
        payload = rule(payload)
    return _with_defaults(row, payload)


def _with_defaults(row: Operation, payload: dict[str, Any]) -> dict[str, Any]:
    """Fill in exactly the defaults the operation's schema publishes."""
    properties = row.input_schema.get("properties") or {}
    for name, spec in properties.items():
        if name in payload or not isinstance(spec, Mapping) or "default" not in spec:
            continue
        payload[name] = spec["default"]
    if "first" in properties and payload.get("first") is None:
        payload["first"] = DEFAULT_PAGE_SIZE
    return payload


def _unique_gids(value: Any, *, expected_type: str, field: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ExtensionError(errors.INVALID_PAYLOAD, f"{field} must be an array")
    checked: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        identifier = gids.gid(item, expected_type=expected_type, field=f"{field}[{index}]")
        if identifier in seen:
            raise ExtensionError(
                errors.INVALID_PAYLOAD, f"{field} names {identifier} more than once"
            )
        seen.add(identifier)
        checked.append(identifier)
    return checked


def _quantities(value: Any) -> list[dict[str, Any]]:
    """Check each quantity's ids and refuse a batch that writes twice to one place.

    Two entries for the same inventory item at the same location would leave the
    final stock level dependent on the order Shopify happened to apply them in.
    That is not a partial success worth having, so the batch is refused before
    anything is sent.
    """
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ExtensionError(errors.INVALID_PAYLOAD, "quantities must be an array")
    checked: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping):  # pragma: no cover - the schema ran first
            raise ExtensionError(errors.INVALID_PAYLOAD, f"quantities[{index}] must be an object")
        inventory_item_id = gids.gid(
            entry.get("inventory_item_id"),
            expected_type=gids.INVENTORY_ITEM,
            field=f"quantities[{index}].inventory_item_id",
        )
        location_id = gids.gid(
            entry.get("location_id"),
            expected_type=gids.LOCATION,
            field=f"quantities[{index}].location_id",
        )
        pair = (inventory_item_id, location_id)
        if pair in seen:
            raise ExtensionError(
                errors.INVALID_PAYLOAD,
                f"quantities names the same inventory item at the same location twice "
                f"(entry {index})",
            )
        seen.add(pair)
        checked.append(
            {
                "inventory_item_id": inventory_item_id,
                "location_id": location_id,
                "quantity": entry["quantity"],
                "change_from_quantity": entry["change_from_quantity"],
            }
        )
    return checked


# -- Values the executable schema subset cannot describe --------------------


def _decimal(value: Any, *, field: str) -> str:
    """A money amount, kept as the string Shopify uses.

    The schema can only say "a bounded string"; there is no pattern keyword in
    the subset the platform executes, so the format is checked here.
    """
    text = value if isinstance(value, str) else ""
    if _DECIMAL_RE.fullmatch(text) is None:
        raise ExtensionError(
            errors.INVALID_PAYLOAD, f'{field} must be a decimal amount such as "19.99"'
        )
    return text


def _tracking_url(value: Any, *, field: str) -> str:
    text = value if isinstance(value, str) else ""
    if _TRACKING_URL_RE.fullmatch(text) is None:
        raise ExtensionError(errors.INVALID_PAYLOAD, f"{field} must be an https:// URL")
    return text


def _require_one_of(payload: Mapping[str, Any], fields: Sequence[str], *, what: str) -> None:
    if not any(name in payload for name in fields):
        raise ExtensionError(
            errors.INVALID_PAYLOAD,
            f"{what} needs at least one of: {', '.join(fields)}",
        )


def _tracking(value: Any, *, field: str) -> dict[str, Any]:
    """One tracking object, with at least one populated field.

    An empty object would ask Shopify to replace tracking with nothing, and
    "clear the tracking" is not something this operation offers.
    """
    entry = dict(value) if isinstance(value, Mapping) else {}
    if not any(name in entry for name in catalog.TRACKING_FIELDS):
        raise ExtensionError(
            errors.INVALID_PAYLOAD,
            f"{field} needs at least one of: {', '.join(catalog.TRACKING_FIELDS)}",
        )
    urls = entry.get("urls")
    if isinstance(urls, Sequence) and not isinstance(urls, (str, bytes)):
        entry["urls"] = [
            _tracking_url(url, field=f"{field}.urls[{index}]") for index, url in enumerate(urls)
        ]
        numbers = entry.get("numbers")
        if numbers is None or len(numbers) != len(urls):
            raise ExtensionError(
                errors.INVALID_PAYLOAD,
                f"{field}.urls requires one corresponding number for every URL",
            )
    return entry


def _variant_money(entry: dict[str, Any], *, field: str) -> dict[str, Any]:
    for name in ("price", "compare_at_price"):
        if name in entry:
            entry[name] = _decimal(entry[name], field=f"{field}.{name}")
    item = entry.get("inventory_item")
    if isinstance(item, Mapping) and "cost" in item:
        inventory_item = dict(item)
        inventory_item["cost"] = _decimal(item["cost"], field=f"{field}.inventory_item.cost")
        entry["inventory_item"] = inventory_item
    return entry


# -- Per-operation semantic rules ------------------------------------------


def _create_product(payload: dict[str, Any]) -> dict[str, Any]:
    for image in payload.get("images", []):
        source = image["url"]
        try:
            parsed = urlsplit(source)
            valid = (
                source.startswith("https://")
                and parsed.hostname
                and parsed.username is None
                and parsed.password is None
                and not any(char.isspace() or ord(char) < 32 for char in source)
            )
            _ = parsed.port  # Reject malformed ports before submitting a batch.
        except ValueError:
            valid = False
        if not valid:
            raise ExtensionError(
                errors.INVALID_PAYLOAD,
                "images.url must be an HTTPS URL without credentials or whitespace",
            )
    options = payload.get("options")
    if isinstance(options, Sequence) and not isinstance(options, (str, bytes)):
        names = [entry.get("name") for entry in options if isinstance(entry, Mapping)]
        if len(set(names)) != len(names):
            raise ExtensionError(errors.INVALID_PAYLOAD, "options names the same option twice")
    return payload


def _update_product(payload: dict[str, Any]) -> dict[str, Any]:
    changes = [name for name in catalog.PRODUCT_UPDATE_CHANGE_FIELDS if name in payload]
    if not changes:
        raise ExtensionError(
            errors.INVALID_PAYLOAD,
            "update_product needs at least one of: "
            + ", ".join(catalog.PRODUCT_UPDATE_CHANGE_FIELDS),
        )
    return payload


def _variants(payload: dict[str, Any], *, updating: bool) -> dict[str, Any]:
    entries = payload.get("variants")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise ExtensionError(errors.INVALID_PAYLOAD, "variants must be an array")
    checked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(entries):
        entry = dict(raw) if isinstance(raw, Mapping) else {}
        field = f"variants[{index}]"
        if updating:
            variant_id = gids.gid(
                entry.get("variant_id"),
                expected_type=gids.PRODUCT_VARIANT,
                field=f"{field}.variant_id",
            )
            if variant_id in seen:
                raise ExtensionError(
                    errors.INVALID_PAYLOAD, f"variants names {variant_id} more than once"
                )
            seen.add(variant_id)
            entry["variant_id"] = variant_id
            if not any(
                name in entry and (name != "inventory_item" or bool(entry[name]))
                for name in catalog.VARIANT_UPDATE_CHANGE_FIELDS
            ):
                raise ExtensionError(
                    errors.INVALID_PAYLOAD, f"{field} names a variant but asks for no change"
                )
        checked.append(_variant_money(entry, field=field))
    payload["variants"] = checked
    return payload


def _metafields(value: Any, *, owners: Sequence[str]) -> list[dict[str, Any]]:
    """Check every metafield entry, its owner type, and the batch as a whole.

    ``compare_digest`` must be *present* on every entry. A missing key would
    mean "overwrite whatever is there", which is the outcome compare-and-set
    exists to prevent, so the schema requires it and an explicit ``null`` is
    how a caller asks to create only.
    """
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ExtensionError(errors.INVALID_PAYLOAD, "metafields must be an array")
    checked: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(value):
        entry = dict(raw) if isinstance(raw, Mapping) else {}
        field = f"metafields[{index}]"
        owner_id = gids.one_of_gid(
            entry.get("owner_id"), expected_types=owners, field=f"{field}.owner_id"
        )
        if "compare_digest" not in entry:
            raise ExtensionError(
                errors.INVALID_PAYLOAD,
                f"{field}.compare_digest is required; send null to create only",
            )
        identity = (owner_id, str(entry.get("namespace")), str(entry.get("key")))
        if identity in seen:
            raise ExtensionError(
                errors.INVALID_PAYLOAD,
                f"metafields names the same owner, namespace and key twice (entry {index})",
            )
        seen.add(identity)
        entry["owner_id"] = owner_id
        checked.append(entry)
    return checked


def _media_alt(payload: dict[str, Any]) -> dict[str, Any]:
    payload["media_id"] = gids.one_of_gid(
        payload.get("media_id"), expected_types=gids.MEDIA_GID_TYPES, field="media_id"
    )
    return payload


def _catalog_metafield_owner(payload: dict[str, Any]) -> dict[str, Any]:
    """The owner id must be the type the caller said it was.

    Asking for the owner type explicitly, rather than inferring it from the id,
    means a Product id pasted where a variant belongs is refused here instead of
    quietly reading the wrong record's metafields.
    """
    owner_type = str(payload.get("owner_type") or "")
    expected = gids.CATALOG_METAFIELD_OWNERS.get(owner_type)
    if expected is None:  # pragma: no cover - the schema enum ran first
        raise ExtensionError(
            errors.INVALID_PAYLOAD, "owner_type must be one of the documented values"
        )
    payload["owner_id"] = gids.gid(
        payload.get("owner_id"), expected_type=expected, field="owner_id"
    )
    return payload


def _order_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    _require_one_of(payload, catalog.ORDER_METADATA_CHANGE_FIELDS, what="update_order_metadata")
    return payload


def _fulfillment_lines(group: dict[str, Any], field: str) -> list[dict[str, Any]]:
    line_items = group.get("line_items")
    if not isinstance(line_items, Sequence) or isinstance(line_items, (str, bytes)):
        raise ExtensionError(errors.INVALID_PAYLOAD, f"{field}.line_items must be an array")
    seen_lines: set[str] = set()
    checked_lines: list[dict[str, Any]] = []
    for line_index, raw_line in enumerate(line_items):
        line = dict(raw_line) if isinstance(raw_line, Mapping) else {}
        line_field = f"{field}.line_items[{line_index}]"
        line_id = gids.gid(
            line.get("fulfillment_order_line_item_id"),
            expected_type=gids.FULFILLMENT_ORDER_LINE_ITEM,
            field=f"{line_field}.fulfillment_order_line_item_id",
        )
        if line_id in seen_lines:
            raise ExtensionError(
                errors.INVALID_PAYLOAD,
                f"{field}.line_items names {line_id} more than once",
            )
        seen_lines.add(line_id)
        checked_lines.append(
            {"fulfillment_order_line_item_id": line_id, "quantity": line["quantity"]}
        )
    return checked_lines


def _fulfillment(payload: dict[str, Any]) -> dict[str, Any]:
    """Every fulfillment order and every line item must be named explicitly.

    Shopify fulfils *everything remaining* on a fulfillment order when the line
    items are omitted. That is a reasonable API default and a terrible thing for
    an omitted field to decide, so this extension always states the line items
    and refuses a group that does not.
    """
    groups = payload.get("fulfillment_orders")
    if not isinstance(groups, Sequence) or isinstance(groups, (str, bytes)):
        raise ExtensionError(errors.INVALID_PAYLOAD, "fulfillment_orders must be an array")
    checked: list[dict[str, Any]] = []
    seen_orders: set[str] = set()
    for index, raw in enumerate(groups):
        group = dict(raw) if isinstance(raw, Mapping) else {}
        field = f"fulfillment_orders[{index}]"
        order_id = gids.gid(
            group.get("fulfillment_order_id"),
            expected_type=gids.FULFILLMENT_ORDER,
            field=f"{field}.fulfillment_order_id",
        )
        if order_id in seen_orders:
            raise ExtensionError(
                errors.INVALID_PAYLOAD,
                f"fulfillment_orders names {order_id} more than once",
            )
        seen_orders.add(order_id)
        checked_lines = _fulfillment_lines(group, field)
        checked.append({"fulfillment_order_id": order_id, "line_items": checked_lines})
    payload["fulfillment_orders"] = checked
    if "tracking" in payload:
        payload["tracking"] = _tracking(payload["tracking"], field="tracking")
    return payload


def _fulfillment_tracking(payload: dict[str, Any]) -> dict[str, Any]:
    payload["tracking"] = _tracking(payload.get("tracking"), field="tracking")
    return payload


_SEMANTIC_RULES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "create_product": _create_product,
    "update_product": _update_product,
    "create_product_variants_batch": lambda payload: _variants(payload, updating=False),
    "update_product_variants_batch": lambda payload: _variants(payload, updating=True),
    "list_catalog_metafields": _catalog_metafield_owner,
    "update_product_media_alt": _media_alt,
    "update_order_metadata": _order_metadata,
    "create_fulfillment": _fulfillment,
    "update_fulfillment_tracking": _fulfillment_tracking,
    "set_inventory_quantities": lambda payload: {
        **payload,
        "quantities": _quantities(payload.get("quantities")),
    },
}


def test_mode(payload: Mapping[str, Any]) -> bool:
    """Whether the host asked for a rehearsal rather than a real invocation."""
    runtime_context = payload.get("runtime_context")
    if not isinstance(runtime_context, Mapping):
        return False
    value = runtime_context.get("test_mode", False)
    if not isinstance(value, bool):
        raise ExtensionError(errors.INVALID_PAYLOAD, "runtime_context.test_mode must be boolean")
    return value


def external_effect_id(payload: Mapping[str, Any]) -> str:
    """The host's external effect id, which becomes Shopify's idempotency key.

    A mutating invocation without one cannot be made safe to retry, so it is
    refused rather than sent with an invented key.
    """
    runtime_context = payload.get("runtime_context")
    runtime_context = runtime_context if isinstance(runtime_context, Mapping) else {}
    value = runtime_context.get("external_effect_id")
    text = value.strip() if isinstance(value, str) else ""
    if not text or _EXTERNAL_EFFECT_ID_RE.fullmatch(text) is None:
        raise ExtensionError(
            errors.MISSING_IDEMPOTENCY_KEY,
            "runtime_context.external_effect_id is required to set stock quantities",
        )
    return text


__all__ = [
    "MAX_EXTERNAL_EFFECT_ID_LENGTH",
    "external_effect_id",
    "test_mode",
    "validated_input",
]
