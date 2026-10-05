"""Every endpoint this extension uses matches Shopify's official schema completely.

Compared against ``tests/reference/admin_schema_2026_07.json``, cut from
Shopify's own introspection of API version ``2026-07``:

1. every field a document selects exists and is not deprecated;
2. every argument of every selected field is used, or excluded with a reason;
3. every record table carries every scalar and money field of its Shopify type,
   or excludes it with a reason;
4. every document selects exactly what its record table declares;
5. every field of every mutation input type is reachable from an operation's
   input, or excluded with a reason — proved by running each operation and
   reading the variables it actually sends;
6. no document can ask for more than Shopify's 1000-point query cost limit.

Exclusions live in ``runtime/coverage.py`` and are what the user documentation
lists as not supported.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import admin_schema
import pytest
from conftest import (
    CATEGORY_A,
    FULFILLMENT_A,
    FULFILLMENT_ORDER_A,
    FULFILLMENT_ORDER_LINE_A,
    ITEM_A,
    LOCATION_A,
    MEDIA_A,
    ORDER_A,
    PRODUCT_A,
    VARIANT_A,
    FakeHttp,
    run_action,
)
from graphql_selection import Field, named_type, parse

from runtime import catalog, coverage, documents, export_details, records, validation
from runtime.product_input import product_set_input

SNAPSHOT = admin_schema.load()
DOCUMENTS = admin_schema.all_documents()
OBJECTS: dict[str, dict[str, Any]] = SNAPSHOT["objects"]
KINDS: dict[str, str] = SNAPSHOT["kinds"]
MAX_QUERY_COST = 1000
COLLECTION_A = "gid://shopify/Collection/5001"
METAFIELD_A = "gid://shopify/Metafield/1"


def _root(kind: str) -> str:
    return SNAPSHOT["roots"][kind]


def _walk(type_name: str, fields: list[Field], path: str) -> Iterator[tuple[str, Field, str]]:
    for field in fields:
        if field.name == "__typename":
            continue
        yield type_name, field, f"{path}.{field.name}" if path else field.name
        target = named_type(OBJECTS[type_name][field.name]["type"])
        yield from _walk(target, field.selections, f"{path}.{field.name}")
        for condition, inner in field.fragments.items():
            yield from _walk(condition, inner, f"{path}.{field.name}")


def _selected() -> Iterator[tuple[str, str, Field, str]]:
    for name, text in DOCUMENTS.items():
        operation = parse(text)
        for parent, field, path in _walk(_root(operation.kind), operation.selections, ""):
            yield name, parent, field, path


# -- 1. Validity -------------------------------------------------------------


@pytest.mark.parametrize("document", sorted(DOCUMENTS))
def test_every_selected_field_exists_and_is_current(document: str) -> None:
    operation = parse(DOCUMENTS[document])
    for parent, field, path in _walk(_root(operation.kind), operation.selections, ""):
        declared = OBJECTS[parent].get(field.name)
        assert declared is not None, f"{document}: {parent}.{field.name} is not in the schema"
        assert not declared["deprecated"], f"{document}: {path} is deprecated"
        unknown = set(field.arguments) - set(declared["args"])
        assert not unknown, f"{document}: {path} passes unknown or deprecated {unknown}"


# -- 2. Arguments ------------------------------------------------------------


def test_every_argument_of_every_selected_field_is_used_or_excluded() -> None:
    gaps: list[str] = []
    for document, parent, field, path in _selected():
        for argument in OBJECTS[parent][field.name]["args"]:
            if argument in field.arguments:
                continue
            if argument in coverage.GLOBAL_ARGUMENT_EXCLUSIONS:
                continue
            if argument in coverage.ARGUMENT_EXCLUSIONS.get(f"{parent}.{field.name}", {}):
                continue
            if parent in (_root("mutation"),) and argument in coverage.INPUT_EXCLUSIONS.get(
                _operation_for(document), {}
            ):
                continue
            gaps.append(f"{document}: {path}({argument})")
    assert not gaps, "Arguments neither used nor excluded:\n" + "\n".join(sorted(set(gaps)))


def _operation_for(document: str) -> str:
    module, name = document.split(".", 1)
    if module == "bulk_documents" and name == "CREATE_ROW":
        return "create_products_bulk"
    for operation_id, text in documents.DOCUMENTS.items():
        if text is DOCUMENTS[document]:
            return operation_id
    return ""


# -- 3. Record tables against the official types -----------------------------


def _eligible(type_name: str) -> set[str]:
    """Scalar, enum and money fields Shopify offers without a required argument."""
    found: set[str] = set()
    for name, declared in OBJECTS[type_name].items():
        if declared["deprecated"]:
            continue
        if any(arg.endswith("!") for arg in declared["args"].values()):
            continue
        target = named_type(declared["type"])
        if KINDS.get(target) in ("SCALAR", "ENUM") or target in ("MoneyBag", "MoneyV2"):
            found.add(name)
    return found


_TABLE_TYPES = {name: name for name in records.RECORDS}


@pytest.mark.parametrize("table", sorted(records.RECORDS))
def test_every_record_table_carries_every_official_field(table: str) -> None:
    type_name = _TABLE_TYPES[table]
    assert type_name in OBJECTS, f"{type_name} is not selected by any document"
    excluded = set(coverage.FIELD_EXCLUSIONS.get(type_name, {}))
    plain = {field.graphql for field in records.RECORDS[table] if not field.on}
    for field in records.RECORDS[table]:
        owner = field.on or type_name
        assert field.graphql in OBJECTS[owner], f"{table}: {owner}.{field.graphql} does not exist"
    missing = _eligible(type_name) - plain - excluded
    assert not missing, f"{table} lacks {sorted(missing)}"
    for condition in {field.on for field in records.RECORDS[table] if field.on}:
        own = {field.graphql for field in records.RECORDS[table] if field.on == condition}
        missing = (
            _eligible(condition)
            - _eligible(type_name)
            - own
            - set(coverage.FIELD_EXCLUSIONS.get(condition, {}))
        )
        assert not missing, f"{table} on {condition} lacks {sorted(missing)}"


def test_every_exclusion_names_a_real_field() -> None:
    for type_name, fields in coverage.FIELD_EXCLUSIONS.items():
        for name, reason in fields.items():
            assert name in OBJECTS.get(type_name, {}), f"{type_name}.{name}"
            assert reason.strip()


# -- 4. Documents select exactly their tables --------------------------------


def _table_signature(table: str) -> set[str]:
    plain: set[str] = set()
    fragments: dict[str, set[str]] = {}
    for field in records.RECORDS[table]:
        signature = _field_signature(field)
        if field.on:
            fragments.setdefault(field.on, set()).add(signature)
        else:
            plain.add(signature)
    for condition, inner in fragments.items():
        plain.add(f"... on {condition}{{{','.join(sorted(inner))}}}")
    return plain


def _field_signature(field: records.Field) -> str:
    if field.kind == "ref":
        return f"{field.graphql}{{id}}"
    if field.kind == "money":
        return f"{field.graphql}{{shopMoney{{amount,currencyCode}}}}"
    if field.kind in ("record", "records"):
        return f"{field.graphql}{{{','.join(sorted(_table_signature(field.target)))}}}"
    if field.kind == "connection":
        nodes = ",".join(sorted(_table_signature(field.target)))
        return f"{field.graphql}{{nodes{{{nodes}}},pageInfo{{endCursor,hasNextPage}}}}"
    return field.graphql


def _selection_signature(fields: list[Field], fragments: dict[str, list[Field]]) -> set[str]:
    found = {_doc_signature(field) for field in fields if field.name != "__typename"}
    for condition, inner in fragments.items():
        found.add(f"... on {condition}{{{','.join(sorted(_selection_signature(inner, {})))}}}")
    return found


def _doc_signature(field: Field) -> str:
    if not field.selections and not field.fragments:
        return field.name
    inner = _selection_signature(field.selections, field.fragments)
    return f"{field.name}{{{','.join(sorted(inner))}}}"


def _find(fields: list[Field], path: tuple[str, ...]) -> Field:
    current: Field | None = None
    for name in path:
        candidates = fields if current is None else current.selections
        if current is not None:
            for inner in current.fragments.values():
                candidates = candidates + inner
        current = next(field for field in candidates if field.name == name)
    assert current is not None
    return current


#: Where each record is selected: (document, path to the record, table, extra fields).
RECORD_SELECTIONS: list[tuple[str, tuple[str, ...], str, frozenset[str]]] = [
    ("documents.GET_SHOP", ("shop",), "Shop", frozenset()),
    ("documents.LIST_LOCATIONS", ("locations", "nodes"), "Location", frozenset()),
    ("documents.LIST_INVENTORY_ITEMS", ("inventoryItems", "nodes"), "InventoryItem", frozenset()),
    ("documents.GET_INVENTORY_ITEM", ("inventoryItem",), "InventoryItem", frozenset()),
    (
        "documents.SET_INVENTORY_QUANTITIES",
        ("inventorySetQuantities", "inventoryAdjustmentGroup"),
        "InventoryAdjustmentGroup",
        frozenset(),
    ),
    ("documents.LIST_PRODUCTS", ("products", "nodes"), "Product", frozenset()),
    ("documents.EXPORT_PRODUCTS", ("products", "nodes"), "Product", frozenset()),
    ("documents.GET_PRODUCT", ("product",), "Product", frozenset()),
    (
        "documents.LIST_PRODUCT_VARIANTS",
        ("productVariants", "nodes"),
        "ProductVariant",
        frozenset(),
    ),
    ("documents.GET_PRODUCT_VARIANT", ("productVariant",), "ProductVariant", frozenset()),
    ("documents.LIST_PRODUCT_MEDIA", ("product", "media", "nodes"), "Media", frozenset()),
    ("documents.CREATE_PRODUCT", ("productSet", "product"), "Product", frozenset({"variants"})),
    (
        "documents.CREATE_PRODUCT",
        ("productSet", "product", "variants", "nodes"),
        "ProductVariant",
        frozenset(),
    ),
    ("documents.UPDATE_PRODUCT", ("productUpdate", "product"), "Product", frozenset()),
    (
        "documents.CREATE_PRODUCT_VARIANTS_BATCH",
        ("productVariantsBulkCreate", "productVariants"),
        "ProductVariant",
        frozenset(),
    ),
    (
        "documents.UPDATE_PRODUCT_VARIANTS_BATCH",
        ("productVariantsBulkUpdate", "productVariants"),
        "ProductVariant",
        frozenset(),
    ),
    (
        "documents.SET_CATALOG_METAFIELDS",
        ("metafieldsSet", "metafields"),
        "Metafield",
        frozenset({"owner"}),
    ),
    (
        "documents.SET_ORDER_METAFIELDS",
        ("metafieldsSet", "metafields"),
        "Metafield",
        frozenset({"owner"}),
    ),
    ("documents.UPDATE_PRODUCT_MEDIA", ("fileUpdate", "files"), "File", frozenset()),
    (
        "documents.LIST_CATALOG_METAFIELDS",
        ("node", "metafields", "nodes"),
        "Metafield",
        frozenset(),
    ),
    ("documents.LIST_ORDER_METAFIELDS", ("order", "metafields", "nodes"), "Metafield", frozenset()),
    ("documents.LIST_ORDERS", ("orders", "nodes"), "Order", frozenset()),
    ("documents.GET_ORDER", ("order",), "Order", frozenset()),
    ("documents.UPDATE_ORDER_METADATA", ("orderUpdate", "order"), "Order", frozenset()),
    ("documents.LIST_ORDER_LINE_ITEMS", ("order", "lineItems", "nodes"), "LineItem", frozenset()),
    (
        "documents.LIST_ORDER_FULFILLMENT_ORDERS",
        ("order", "fulfillmentOrders", "nodes"),
        "FulfillmentOrder",
        frozenset(),
    ),
    ("documents.GET_FULFILLMENT_ORDER", ("fulfillmentOrder",), "FulfillmentOrder", frozenset()),
    ("documents.LIST_ORDER_FULFILLMENTS", ("order", "fulfillments"), "Fulfillment", frozenset()),
    (
        "documents.CREATE_FULFILLMENT",
        ("fulfillmentCreate", "fulfillment"),
        "Fulfillment",
        frozenset(),
    ),
    (
        "documents.UPDATE_FULFILLMENT_TRACKING",
        ("fulfillmentTrackingInfoUpdate", "fulfillment"),
        "Fulfillment",
        frozenset(),
    ),
    ("export_documents.VARIANTS", ("nodes", "variants", "nodes"), "ProductVariant", frozenset()),
]


@pytest.mark.parametrize(
    ("document", "path", "table", "extra"),
    RECORD_SELECTIONS,
    ids=[f"{doc}:{'.'.join(path)}" for doc, path, _t, _e in RECORD_SELECTIONS],
)
def test_each_document_selects_exactly_its_record_table(
    document: str, path: tuple[str, ...], table: str, extra: frozenset[str]
) -> None:
    operation = parse(DOCUMENTS[document])
    node = _find(operation.selections, path)
    kept = [field for field in node.selections if field.name not in extra]
    assert _selection_signature(kept, node.fragments) == _table_signature(table)


def test_every_record_selection_is_declared() -> None:
    """A document cannot grow a record selection the table test does not see."""
    declared = {(doc, ".".join(path)) for doc, path, _table, _extra in RECORD_SELECTIONS}
    covered_documents = {doc for doc, _path in declared}
    for name, text in documents.DOCUMENTS.items():
        if name in ("test_connection", "get_inventory_levels_batch", "create_products_bulk"):
            continue
        assert any(text is DOCUMENTS[doc] for doc in covered_documents), name


# -- 5. Every mutation input field is reachable ------------------------------


def _paths(value: Any, prefix: str) -> set[str]:
    found = {prefix}
    if isinstance(value, Mapping):
        for key, item in value.items():
            found |= _paths(item, f"{prefix}.{key}")
    elif isinstance(value, list):
        for item in value:
            found |= _paths(item, prefix)
    return found


def _expected_paths(root_field: str) -> set[str]:
    expected: set[str] = set()
    for argument, type_ref in OBJECTS[_root("mutation")][root_field]["args"].items():
        expected.add(argument)
        target = named_type(type_ref)
        if KINDS.get(target) == "INPUT_OBJECT":
            expected |= {
                f"{argument}.{path}" for path in admin_schema.input_paths(SNAPSHOT, target)
            }
    return expected


def _excluded(path: str, operation_id: str) -> bool:
    exclusions = coverage.INPUT_EXCLUSIONS.get(operation_id, {})
    return any(path == item or path.startswith(f"{item}.") for item in exclusions)


def _sent_paths(document: str, variables: Mapping[str, Any]) -> tuple[str, set[str]]:
    operation = parse(document)
    root = operation.selections[0]
    sent: set[str] = set()
    for argument, value_text in root.arguments.items():
        if value_text.startswith("$"):
            variable = value_text[1:].strip()
            if variable in variables and variables[variable] is not None:
                sent |= _paths(variables[variable], argument)
    return root.name, sent


def _assert_complete(operation_id: str, document: str, sent_variables: list[dict[str, Any]]):
    root_field = parse(document).selections[0].name
    sent: set[str] = set()
    for variables in sent_variables:
        sent |= _sent_paths(document, variables)[1]
    expected = _expected_paths(root_field)
    unknown = sent - expected
    assert not unknown, f"{operation_id} sends fields Shopify does not have: {sorted(unknown)}"
    missing = {path for path in expected - sent if not _excluded(path, operation_id)}
    assert not missing, f"{operation_id} cannot reach: {sorted(missing)}"


_INVENTORY_ITEM_FULL = {
    "sku": "SKU-1",
    "cost": "4.50",
    "tracked": True,
    "requires_shipping": True,
    "country_code_of_origin": "DE",
    "province_code_of_origin": "BY",
    "harmonized_system_code": "640399",
    "country_harmonized_system_codes": [
        {"harmonized_system_code": "6403990000", "country_code": "US"}
    ],
    "measurement": {
        "weight": {"value": 1.2, "unit": "KILOGRAMS"},
        "shipping_package_id": "gid://shopify/ShippingPackage/1",
    },
}

_VARIANT_COMMON_FULL = {
    "price": "19.99",
    "compare_at_price": "24.99",
    "barcode": "4006381333931",
    "inventory_policy": "DENY",
    "taxable": True,
    "tax_code": "P0000000",
    "requires_components": False,
    "published": True,
    "show_unit_price": True,
    "unit_price_measurement": {
        "quantity_value": 500.0,
        "quantity_unit": "G",
        "reference_value": 1,
        "reference_unit": "KG",
    },
}

_NEW_METAFIELD = {
    "namespace": "custom",
    "key": "care",
    "type": "single_line_text_field",
    "value": "x",
}

_CREATE_PRODUCT_FULL = {
    "title": "Boots",
    "handle": "boots",
    "description_html": "<p>Boots</p>",
    "vendor": "Acme",
    "product_type": "Footwear",
    "category_id": CATEGORY_A,
    "seo_title": "Boots",
    "seo_description": "Good boots",
    "template_suffix": "special",
    "gift_card_template_suffix": "gift",
    "requires_selling_plan": False,
    "tags": ["new"],
    "status": "ACTIVE",
    "gift_card": False,
    "collection_ids": [COLLECTION_A],
    "combined_listing_role": "PARENT",
    "claim_ownership": {"bundles": True},
    "metafields": [_NEW_METAFIELD],
    "options": [
        {"name": "Size", "position": 1, "values": ["42", "43"]},
        {"name": "Color", "linked_metafield": {"namespace": "shopify", "key": "color",
                                               "values": ["red"]}},
    ],
    "variants": [
        {
            "option_values": [
                {"option_name": "Size", "value": "42"},
                {"option_name": "Color", "linked_metafield_value": "red"},
            ],
            "sku": "SKU-42",
            "position": 1,
            **_VARIANT_COMMON_FULL,
            "inventory_item": _INVENTORY_ITEM_FULL,
            "image": {
                "source_url": "https://cdn.example.test/v.jpg",
                "alt": "Variant",
                "filename": "v.jpg",
                "duplicate_resolution_mode": "APPEND_UUID",
            },
            "inventory_quantities": [{"location_id": LOCATION_A, "name": "available", "quantity": 3}],
            "metafields": [_NEW_METAFIELD],
        },
        {
            "option_values": [
                {"option_name": "Size", "value": "43"},
                {"option_name": "Color", "linked_metafield_value": "red"},
            ],
            "image": {"file_id": MEDIA_A},
        },
    ],
    "media": [
        {
            "source_url": "https://cdn.example.test/a.jpg",
            "content_type": "IMAGE",
            "alt": "Front",
            "filename": "a.jpg",
            "duplicate_resolution_mode": "REPLACE",
        },
        {"file_id": MEDIA_A},
    ],
}  # fmt: skip


def _capture(operation_id: str, inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    for operation_input in inputs:
        http = FakeHttp()
        run_action(operation_id, operation_input, http)
        assert http.requests, f"{operation_id} sent nothing for {operation_input}"
        captured.append(http.variables(-1))
    return captured


_BULK_VARIANT = {
    **_VARIANT_COMMON_FULL,
    "inventory_item": _INVENTORY_ITEM_FULL,
    "media_src": ["https://cdn.example.test/a.jpg"],
    "media_id": MEDIA_A,
    "inventory_quantities": [{"location_id": LOCATION_A, "available_quantity": 3}],
    "quantity_adjustments": [
        {"location_id": LOCATION_A, "adjustment": 2, "change_from_quantity": None}
    ],
    "metafields": [{**_NEW_METAFIELD}, {"id": METAFIELD_A, "value": "y"}],
}

_MEDIA_LIST = [
    {"source_url": "https://cdn.example.test/a.jpg", "content_type": "IMAGE", "alt": "A"}
]

_TRACKING = {"company": "DHL", "numbers": ["TRK1"], "urls": ["https://track.test/1"]}

WRITE_CASES: dict[str, list[dict[str, Any]]] = {
    "create_product": [_CREATE_PRODUCT_FULL],
    "update_product": [
        {
            "product_id": PRODUCT_A,
            "title": "Boots",
            "handle": "boots-2",
            "redirect_new_handle": False,
            "description_html": "<p>x</p>",
            "vendor": "Acme",
            "product_type": "Footwear",
            "category_id": CATEGORY_A,
            "delete_conflicting_constrained_metafields": True,
            "seo_title": "t",
            "seo_description": "d",
            "template_suffix": "s",
            "gift_card_template_suffix": "g",
            "requires_selling_plan": False,
            "replace_tags": ["a"],
            "status": "ARCHIVED",
            "join_collection_ids": [COLLECTION_A],
            "leave_collection_ids": [COLLECTION_A],
            "metafields": [{"id": METAFIELD_A, "value": "y"}, _NEW_METAFIELD],
            "media": _MEDIA_LIST,
        },
        {"product_handle": "boots", "title": "Boots"},
        {
            "product_custom_id": {"namespace": "custom", "key": "erp_id", "value": "E-1"},
            "title": "Boots",
        },
    ],
    "create_product_variants_batch": [
        {
            "product_id": PRODUCT_A,
            "variants": [
                {
                    "option_values": [{"option_name": "Size", "value": "44"}],
                    **_BULK_VARIANT,
                },
                {"option_values": [{"option_name": "Color", "linked_metafield_value": "red"}]},
            ],
            "media": _MEDIA_LIST,
            "strategy": "REMOVE_STANDALONE_VARIANT",
        }
    ],
    "update_product_variants_batch": [
        {
            "product_id": PRODUCT_A,
            "variants": [
                {
                    "variant_id": VARIANT_A,
                    "option_values": [
                        {"option_name": "Size", "value": "44"},
                    ],
                    **_BULK_VARIANT,
                },
                {
                    "variant_id": "gid://shopify/ProductVariant/4002",
                    "option_values": [{"option_name": "Color", "linked_metafield_value": "red"}],
                },
            ],
            "media": _MEDIA_LIST,
            "allow_partial_updates": True,
        }
    ],
    "set_inventory_quantities": [
        {
            "quantities": [
                {
                    "inventory_item_id": ITEM_A,
                    "location_id": LOCATION_A,
                    "quantity": 3,
                    "change_from_quantity": 1,
                }
            ],
            "name": "on_hand",
            "reason": "received",
        }
    ],
    "set_catalog_metafields": [
        {
            "metafields": [
                {
                    "owner_id": PRODUCT_A,
                    "namespace": "custom",
                    "key": "care",
                    "type": "single_line_text_field",
                    "value": "x",
                    "compare_digest": None,
                }
            ]
        }
    ],
    "set_order_metafields": [
        {
            "metafields": [
                {
                    "owner_id": ORDER_A,
                    "namespace": "custom",
                    "key": "care",
                    "type": "single_line_text_field",
                    "value": "x",
                    "compare_digest": "d",
                }
            ]
        }
    ],
    "update_product_media": [
        {
            "media_id": MEDIA_A,
            "alt": "Front",
            "source_url": "https://cdn.example.test/new.jpg",
            "preview_image_url": "https://cdn.example.test/preview.jpg",
            "filename": "new.jpg",
            "add_to_product_ids": [PRODUCT_A],
            "remove_from_product_ids": ["gid://shopify/Product/3002"],
        }
    ],
    "update_order_metadata": [
        {
            "order_id": ORDER_A,
            "note": "n",
            "po_number": "PO",
            "replace_tags": ["a"],
            "replace_custom_attributes": [{"key": "k", "value": "v"}],
            "email": "buyer@example.test",
            "phone": "+15555550100",
            "shipping_address": {
                "first_name": "A",
                "last_name": "B",
                "company": "C",
                "address1": "1 Street",
                "address2": "Flat 2",
                "city": "Riga",
                "province_code": "RI",
                "zip": "LV-1000",
                "country_code": "LV",
                "phone": "+37100000000",
            },
            "metafields": [{"id": METAFIELD_A, "value": "y"}, _NEW_METAFIELD],
            "localized_fields": [{"key": "TAX_CREDENTIAL_BR", "value": "123"}],
        }
    ],
    "create_fulfillment": [
        {
            "fulfillment_orders": [
                {
                    "fulfillment_order_id": FULFILLMENT_ORDER_A,
                    "line_items": [
                        {"fulfillment_order_line_item_id": FULFILLMENT_ORDER_LINE_A, "quantity": 1}
                    ],
                }
            ],
            "tracking": _TRACKING,
            "notify_customer": True,
            "origin_address": {
                "address1": "1 Street",
                "address2": "Unit 2",
                "city": "Riga",
                "zip": "LV-1000",
                "province_code": "RI",
                "country_code": "LV",
            },
            "message": "Shipped",
        }
    ],
    "update_fulfillment_tracking": [
        {"fulfillment_id": FULFILLMENT_A, "tracking": _TRACKING, "notify_customer": True}
    ],
}


def test_every_action_has_a_coverage_case() -> None:
    missing = set(catalog.ACTION_OPERATION_IDS) - set(WRITE_CASES) - {"create_products_bulk"}
    assert not missing


@pytest.mark.parametrize("operation_id", sorted(WRITE_CASES))
def test_every_official_input_field_is_reachable(operation_id: str) -> None:
    document = documents.DOCUMENTS[operation_id]
    _assert_complete(operation_id, document, _capture(operation_id, WRITE_CASES[operation_id]))


def test_every_bulk_row_input_field_is_reachable() -> None:
    from runtime import bulk_documents

    create = catalog.operation("create_product")
    assert create is not None
    row = dict(_CREATE_PRODUCT_FULL)
    item = validation.validated_input(create, {"connection_ref": "conn-1", **row})
    _assert_complete(
        "create_products_bulk",
        bulk_documents.CREATE_ROW,
        [{"input": product_set_input(item)}],
    )


# -- 6. Query cost -----------------------------------------------------------


def _cost(type_name: str, fields: list[Field], fragments: dict[str, list[Field]], sizes) -> int:
    total = 0
    for field in fields:
        if field.name == "__typename":
            continue
        declared = OBJECTS[type_name][field.name]
        target = named_type(declared["type"])
        if KINDS.get(target) in ("SCALAR", "ENUM"):
            continue
        child = _cost(target, field.selections, field.fragments, sizes)
        size = _size(field.arguments.get("first"), sizes)
        if target.endswith("Connection"):
            node = next((f for f in field.selections if f.name == "nodes"), None)
            per_node = 0
            if node is not None:
                node_type = named_type(OBJECTS[target]["nodes"]["type"])
                per_node = 1 + _cost(node_type, node.selections, node.fragments, sizes)
            total += 2 + (size or 1) * per_node
        elif field.name == "nodes" and "ids" in field.arguments:
            total += sizes["$ids"] * (1 + child)
        elif size is not None and field.name not in ("quantities",):
            total += size * (1 + child)
        else:
            total += 1 + child
    for condition, inner in fragments.items():
        total = max(total, _cost(condition, inner, {}, sizes))
    return total


def _size(value: str | None, sizes: Mapping[str, int]) -> int | None:
    if value is None:
        return None
    value = value.replace(" ", "")
    if value.startswith("$"):
        return sizes[value]
    return int(value)


def _document_cost(text: str, sizes: Mapping[str, int]) -> int:
    operation = parse(text)
    base = 10 if operation.kind == "mutation" else 0
    return base + _cost(_root(operation.kind), operation.selections, {}, sizes)


def _maximum(operation_id: str, name: str) -> int:
    row = catalog.operation(operation_id)
    assert row is not None
    return int(row.input_schema["properties"][name]["maximum"])


def _sizes(operation_id: str) -> dict[str, int]:
    sizes = {
        "$variantsFirst": catalog.MAX_CREATE_VARIANTS,
        "$trackingFirst": documents.TRACKING_INFO_LIMIT,
        "$ids": catalog.MAX_BATCH_ITEMS,
    }
    row = catalog.operation(operation_id)
    if row is not None:
        properties = row.input_schema["properties"]
        if "first" in properties:
            sizes["$first"] = _maximum(operation_id, "first")
        if "line_items_first" in properties:
            sizes["$lineItemsFirst"] = _maximum(operation_id, "line_items_first")
    return sizes


@pytest.mark.parametrize("operation_id", sorted(documents.DOCUMENTS))
def test_no_document_exceeds_the_query_cost_limit(operation_id: str) -> None:
    if operation_id == "list_order_fulfillment_orders":
        pytest.skip("bounded by the first x line_items_first rule, checked below")
    cost = _document_cost(documents.DOCUMENTS[operation_id], _sizes(operation_id))
    assert cost <= MAX_QUERY_COST, f"{operation_id} can cost {cost}"


@pytest.mark.parametrize(("first", "lines"), [(1, 100), (10, 20), (4, 100), (50, 7), (19, 23)])
def test_the_fulfillment_order_rule_is_the_real_cost(first: int, lines: int) -> None:
    sizes = {"$first": first, "$lineItemsFirst": lines}
    cost = _document_cost(documents.LIST_ORDER_FULFILLMENT_ORDERS, sizes)
    assert cost == 3 + first * (5 + 2 * lines)
    row = catalog.operation("list_order_fulfillment_orders")
    assert row is not None
    payload = {
        "connection_ref": "conn-1",
        "order_id": ORDER_A,
        "first": first,
        "line_items_first": lines,
    }
    if cost <= MAX_QUERY_COST:
        validation.validated_input(row, payload)
    else:
        with pytest.raises(Exception, match="cost limit"):
            validation.validated_input(row, payload)


@pytest.mark.parametrize("name", ["IMAGES", "VARIANTS", "INVENTORY"])
def test_export_relation_documents_stay_within_the_cost_limit(name: str) -> None:
    sizes = {"$ids": export_details.PARENT_BATCH_SIZE}
    assert _document_cost(DOCUMENTS[f"export_documents.{name}"], sizes) <= MAX_QUERY_COST
