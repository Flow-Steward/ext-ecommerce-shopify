"""The thirty-one documents are literals, and nothing a caller sends reaches them.

This is the property the whole design rests on: if a workflow value could reach
document *text*, every other guarantee in the extension would be advisory.
"""

from __future__ import annotations

import ast
import pathlib
from typing import ClassVar

import pytest
from conftest import (
    FULFILLMENT_A,
    ORDER_A,
    PRODUCT_A,
    FakeHttp,
    graphql_response,
    run_action,
    run_operation,
)
from runtime import documents
from runtime.catalog import NETWORK_OPERATION_IDS, OPERATIONS, OPERATIONS_BY_ID

BUNDLE_ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCUMENTS_SOURCE = (BUNDLE_ROOT / "runtime" / "documents.py").read_text(encoding="utf-8")


class TestEveryDocumentIsALiteral:
    def test_there_are_exactly_thirty_two(self) -> None:
        assert len(documents.DOCUMENTS) == 32
        assert set(documents.DOCUMENTS) == set(NETWORK_OPERATION_IDS)

    def test_every_document_constant_is_a_plain_string_literal(self) -> None:
        """Parsed, not grepped: an f-string or a concatenation would show here."""
        tree = ast.parse(DOCUMENTS_SOURCE)
        literals = 0
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or not target.id.isupper():
                continue
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                if "query " in node.value.value or "mutation " in node.value.value:
                    literals += 1
            else:
                assert not isinstance(node.value, (ast.JoinedStr, ast.BinOp)), target.id

        assert literals == 32

    def test_nothing_assembles_a_document_at_runtime(self) -> None:
        for marker in (".format(", "f'''", 'f"""', "% (", ".join(", ".replace("):
            assert marker not in DOCUMENTS_SOURCE, marker

    @pytest.mark.parametrize("operation_id", sorted(documents.DOCUMENTS))
    def test_a_document_names_exactly_one_graphql_operation(self, operation_id: str) -> None:
        document = documents.DOCUMENTS[operation_id]

        assert document.count("query FlowSteward") + document.count("mutation FlowSteward") == 1

    def test_no_two_operations_share_a_document_object(self) -> None:
        identities = {id(documents.DOCUMENTS[name]) for name in NETWORK_OPERATION_IDS}

        assert len(identities) == 32


class TestNoCallerValueReachesDocumentText:
    #: A workflow value that would be unmistakable if it were interpolated.
    NEEDLE = "zz-injection-needle-zz"

    CASES: ClassVar[list[tuple[str, dict, bool]]] = [
        ("list_inventory_items", {"sku": NEEDLE}, False),
        ("get_product", {"product_id": PRODUCT_A}, False),
        ("list_catalog_metafields", {"owner_type": "product", "owner_id": PRODUCT_A}, False),
        ("list_products", {"after": NEEDLE}, False),
        ("get_order", {"order_id": ORDER_A}, False),
        ("create_product", {"title": NEEDLE, "handle": "h"}, True),
        ("update_product", {"product_id": PRODUCT_A, "vendor": NEEDLE}, True),
        ("update_order_metadata", {"order_id": ORDER_A, "note": NEEDLE}, True),
        (
            "update_fulfillment_tracking",
            {"fulfillment_id": FULFILLMENT_A, "tracking": {"company": NEEDLE}},
            True,
        ),
    ]

    @pytest.mark.parametrize(("operation_id", "operation_input", "is_action"), CASES)
    def test_the_document_is_unchanged_and_the_value_travels_in_variables(
        self, operation_id: str, operation_input: dict, is_action: bool, http: FakeHttp
    ) -> None:
        http.default = graphql_response({})
        runner = run_action if is_action else run_operation

        runner(operation_id, operation_input, http)

        assert http.document() == documents.DOCUMENTS[operation_id]
        assert self.NEEDLE not in http.document()
        if self.NEEDLE in str(operation_input):
            assert self.NEEDLE in str(http.variables())

    def test_a_sku_can_never_become_search_syntax(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"inventoryItems": {"pageInfo": {}, "nodes": []}}))

        run_operation("list_inventory_items", {"sku": '" OR id:>0 OR sku:"'}, http)

        assert http.variables()["query"] == 'sku:"\\" OR id:>0 OR sku:\\""'


class TestNoOperationAcceptsGraphqlOrAnEndpoint:
    FORBIDDEN_INPUTS: ClassVar = {
        "query",
        "graphql",
        "document",
        "mutation",
        "operation",
        "variables",
        "fields",
        "selection",
        "endpoint",
        "url",
        "api_version",
        "host",
        "base_url",
        "input",
        "product",
        "order",
        "fulfillment",
        "files",
    }

    @pytest.mark.parametrize("row", OPERATIONS, ids=lambda row: row.operation_id)
    def test_no_operation_publishes_a_forbidden_input(self, row) -> None:
        assert not self.FORBIDDEN_INPUTS & set(row.input_field_names), row.operation_id

    @pytest.mark.parametrize("row", OPERATIONS, ids=lambda row: row.operation_id)
    def test_every_input_schema_is_closed(self, row) -> None:
        assert row.input_schema["additionalProperties"] is False

    @pytest.mark.parametrize("row", OPERATIONS, ids=lambda row: row.operation_id)
    def test_every_nested_object_input_is_closed_too(self, row) -> None:
        """A closed outer object with an open inner one is not closed."""

        def walk(schema: dict, path: str) -> None:
            if schema.get("type") == "object" or "object" in (schema.get("type") or []):
                assert schema.get("additionalProperties") is False, path
            for name, child in (schema.get("properties") or {}).items():
                walk(child, f"{path}.{name}")
            items = schema.get("items")
            if isinstance(items, dict):
                walk(items, f"{path}[]")

        walk(row.input_schema, row.operation_id)

    @pytest.mark.parametrize("row", OPERATIONS, ids=lambda row: row.operation_id)
    def test_every_workflow_operation_takes_exactly_one_connection(self, row) -> None:
        names = row.input_field_names
        if row.operation_id == "validate_connection_settings":
            assert "connection_ref" not in names
            return
        assert names[0] == "connection_ref"
        assert len([name for name in names if "connection" in name]) == 1

    def test_no_operation_can_name_a_second_integration(self) -> None:
        for row in OPERATIONS:
            for name in row.input_field_names:
                assert name not in {"connection_refs", "connections", "target_connection_ref"}


class TestPaginationIsForwardOnlyAndBounded:
    #: `get_fulfillment_order` paginates its nested line items rather than a
    #: top-level list, so its page size is named for what it pages.
    PAGINATED: ClassVar = [
        row.operation_id
        for row in OPERATIONS
        if {"first", "line_items_first"} & set(row.input_field_names)
    ]

    def test_the_paginated_sources_are_the_expected_ones(self) -> None:
        assert set(self.PAGINATED) == {
            "list_locations",
            "list_inventory_items",
            "list_products",
            "export_products",
            "list_product_variants",
            "list_catalog_metafields",
            "list_product_media",
            "list_orders",
            "list_order_line_items",
            "list_order_metafields",
            "list_order_fulfillment_orders",
            "get_fulfillment_order",
            "list_order_fulfillments",
        }

    @pytest.mark.parametrize("operation_id", sorted(PAGINATED))
    def test_the_page_size_is_bounded_and_defaults_to_fifty(self, operation_id: str) -> None:
        properties = OPERATIONS_BY_ID[operation_id].input_schema["properties"]
        first = properties.get("first") or properties["line_items_first"]

        assert first["minimum"] == 1
        assert first["maximum"] == 250
        assert first["default"] == 50

    @pytest.mark.parametrize("operation_id", sorted(PAGINATED))
    def test_there_is_no_backward_pagination(self, operation_id: str) -> None:
        """`last`/`before` would let a caller walk a store backwards forever."""
        names = set(OPERATIONS_BY_ID[operation_id].input_field_names)

        assert not names & {"last", "before", "reverse", "sort_key"}

    @pytest.mark.parametrize("operation_id", sorted(documents.DOCUMENTS))
    def test_no_document_declares_a_backward_page(self, operation_id: str) -> None:
        document = documents.DOCUMENTS[operation_id]

        assert "$last" not in document
        assert "$before" not in document


class TestForbiddenSurfacesAreAbsent:
    #: Mutations the task rules out. None may appear in any document.
    FORBIDDEN_MUTATIONS: ClassVar = (
        "productDelete",
        "productVariantsBulkDelete",
        "productOptionsDelete",
        "productSet",
        "productDuplicate",
        "publishablePublish",
        "publishableUnpublish",
        "collectionAddProducts",
        "orderCancel",
        "orderClose",
        "orderOpen",
        "orderMarkAsPaid",
        "orderEditBegin",
        "refundCreate",
        "returnCreate",
        "orderInvoiceSend",
        "fileCreate",
        "fileDelete",
        "stagedUploadsCreate",
        "inventoryActivate",
        "inventoryDeactivate",
        "inventoryBulkToggleActivation",
        "inventoryAdjustQuantities",
        "bulkOperationRunQuery",
        "webhookSubscriptionCreate",
        "draftOrderCreate",
        "discountAutomaticAppCreate",
        "customerCreate",
    )

    @pytest.mark.parametrize("name", FORBIDDEN_MUTATIONS)
    def test_no_document_names_a_forbidden_operation(self, name: str) -> None:
        for operation_id, document in documents.DOCUMENTS.items():
            assert name not in document, f"{operation_id} names {name}"

    @pytest.mark.parametrize("name", FORBIDDEN_MUTATIONS)
    def test_no_operation_is_registered_under_a_forbidden_name(self, name: str) -> None:
        assert name not in OPERATIONS_BY_ID

    def test_only_bulk_creation_can_start_a_bulk_mutation(self) -> None:
        starters = {
            key
            for key, document in documents.DOCUMENTS.items()
            if "bulkOperationRunMutation(" in document
        }
        assert starters == {"create_products_bulk"}

    def test_the_api_version_has_one_source_of_truth(self) -> None:
        runtime = BUNDLE_ROOT / "runtime"
        carrying = [
            path.name
            for path in runtime.glob("*.py")
            if documents.API_VERSION in path.read_text(encoding="utf-8")
        ]

        assert carrying == ["documents.py"]
