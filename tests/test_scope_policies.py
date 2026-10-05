"""Canonical all-of OAuth scope requirements owned by operation rows."""

from __future__ import annotations

import pathlib

import pytest

from runtime import scopes
from runtime.catalog import OPERATIONS, OPERATIONS_BY_ID

FULFILLMENT_WRITES = scopes.FULFILLMENT_ORDER_WRITE_SCOPES

EXPECTED_REQUIRED_SCOPES: dict[str, tuple[str, ...]] = {
    "validate_connection_settings": (),
    "test_connection": (),
    "get_shop": (),
    "list_locations": ("write_inventory", "read_locations"),
    "list_inventory_items": ("write_inventory",),
    "get_inventory_item": ("write_inventory",),
    "get_inventory_levels_batch": ("write_inventory",),
    "set_inventory_quantities": ("write_inventory",),
    "list_products": ("write_products",),
    "export_products": ("write_products",),
    "get_product": ("write_products",),
    "list_product_variants": ("write_products",),
    "get_product_variant": ("write_products",),
    "list_catalog_metafields": ("write_products",),
    "list_product_media": ("write_products",),
    "create_product": ("write_products",),
    "create_products_bulk": ("write_products",),
    "update_product": ("write_products",),
    "create_product_variants_batch": ("write_products",),
    "update_product_variants_batch": ("write_products",),
    "set_catalog_metafields": ("write_products",),
    "update_product_media": ("write_files",),
    "list_orders": ("write_orders",),
    "get_order": ("write_orders",),
    "list_order_line_items": ("write_orders",),
    "list_order_metafields": ("write_orders",),
    "list_order_fulfillment_orders": ("write_orders", *FULFILLMENT_WRITES),
    "get_fulfillment_order": ("write_orders", *FULFILLMENT_WRITES),
    "list_order_fulfillments": ("write_orders",),
    "update_order_metadata": ("write_orders",),
    "set_order_metafields": ("write_orders",),
    "create_fulfillment": FULFILLMENT_WRITES,
    "update_fulfillment_tracking": FULFILLMENT_WRITES,
}


def test_every_operation_has_one_expected_canonical_scope_declaration() -> None:
    assert set(EXPECTED_REQUIRED_SCOPES) == {row.operation_id for row in OPERATIONS}
    assert len(EXPECTED_REQUIRED_SCOPES) == 33


@pytest.mark.parametrize("operation_id", sorted(EXPECTED_REQUIRED_SCOPES))
def test_registry_matches_canonical_scope_declaration(operation_id: str) -> None:
    assert (
        OPERATIONS_BY_ID[operation_id].required_oauth_scopes
        == EXPECTED_REQUIRED_SCOPES[operation_id]
    )


def test_only_connection_level_operations_need_no_business_scope() -> None:
    open_rows = [row.operation_id for row in OPERATIONS if not row.required_oauth_scopes]
    assert open_rows == ["validate_connection_settings", "test_connection", "get_shop"]


def test_capability_reporting_uses_the_same_all_of_declaration() -> None:
    row = scopes.capability_row(
        "list_order_fulfillment_orders",
        EXPECTED_REQUIRED_SCOPES["list_order_fulfillment_orders"],
        ["write_orders", *FULFILLMENT_WRITES[:-1]],
    )

    assert row["scope_eligible"] is False
    assert row["required_oauth_scopes"] == ["write_orders", *FULFILLMENT_WRITES]
    assert row["missing_required_oauth_scopes"] == [FULFILLMENT_WRITES[-1]]


def test_stale_seven_write_scope_grant_does_not_cover_list_locations() -> None:
    granted = {
        "write_assigned_fulfillment_orders",
        "write_files",
        "write_inventory",
        "write_merchant_managed_fulfillment_orders",
        "write_orders",
        "write_products",
        "write_third_party_fulfillment_orders",
    }

    missing_by_operation = {
        operation.operation_id: set(operation.required_oauth_scopes) - granted
        for operation in OPERATIONS
        if set(operation.required_oauth_scopes) - granted
    }

    assert missing_by_operation == {"list_locations": {"read_locations"}}


def test_fresh_scope_grant_covers_every_operation() -> None:
    granted = {
        "read_locations",
        "write_assigned_fulfillment_orders",
        "write_files",
        "write_inventory",
        "write_merchant_managed_fulfillment_orders",
        "write_orders",
        "write_products",
        "write_third_party_fulfillment_orders",
    }

    missing_by_operation = {
        operation.operation_id: set(operation.required_oauth_scopes) - granted
        for operation in OPERATIONS
        if set(operation.required_oauth_scopes) - granted
    }

    assert missing_by_operation == {}


def test_read_locations_is_required_only_by_the_document_that_needs_it() -> None:
    assert [
        operation.operation_id
        for operation in OPERATIONS
        if "read_locations" in operation.required_oauth_scopes
    ] == ["list_locations"]


def test_grant_without_inventory_scope_rejects_locations_and_inventory() -> None:
    granted = {
        "write_assigned_fulfillment_orders",
        "write_files",
        "write_merchant_managed_fulfillment_orders",
        "write_orders",
        "write_products",
        "write_third_party_fulfillment_orders",
    }

    missing_by_operation = {
        operation.operation_id: set(operation.required_oauth_scopes) - granted
        for operation in OPERATIONS
        if set(operation.required_oauth_scopes) - granted
    }

    assert missing_by_operation["list_locations"] == {"write_inventory", "read_locations"}
    assert missing_by_operation["list_inventory_items"] == {"write_inventory"}


def test_runtime_has_no_private_scope_policy_dialect() -> None:
    runtime = pathlib.Path(__file__).resolve().parents[1] / "runtime"
    offenders = [
        path.name
        for path in runtime.glob("*.py")
        if "scope_policy" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_no_global_scope_gate_replaces_per_operation_contracts() -> None:
    from runtime import documents

    assert not hasattr(documents, "REQUIRED_ACCESS_SCOPE")
    assert not hasattr(documents, "REQUIRED_ACCESS_SCOPES")
