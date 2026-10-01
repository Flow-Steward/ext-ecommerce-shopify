"""Every result carries exactly the fields its operation publishes.

A workflow binds to ``result.<name>``. A result that quietly grows a field, or
quietly drops one, breaks a binding that the manifest says will work.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import (
    ITEM_A,
    LOCATION_A,
    SHOP_DOMAIN,
    FakeHttp,
    adjustment_group_response,
    connection_payload,
    graphql_response,
    inventory_item_node,
    inventory_level,
    quantity,
    set_quantities_payload,
)
from runtime import schema
from runtime.catalog import OPERATIONS_BY_ID
from runtime.errors import ExtensionError
from runtime.operations import handle_runtime

BUNDLE_ROOT = Path(__file__).resolve().parents[1]

#: One scripted answer and one valid input per operation, so every declared
#: result shape is produced by the real code path rather than asserted about.
CASES: dict[str, tuple[dict, object]] = {
    "validate_connection_settings": ({"shop_domain": "acme"}, None),
    "test_connection": (
        {},
        {
            "shop": {"id": "gid://shopify/Shop/1", "name": "S", "myshopifyDomain": SHOP_DOMAIN},
            "currentAppInstallation": {"accessScopes": [{"handle": "write_inventory"}]},
        },
    ),
    "get_shop": (
        {},
        {
            "shop": {
                "id": "gid://shopify/Shop/1",
                "name": "S",
                "myshopifyDomain": SHOP_DOMAIN,
                "currencyCode": "EUR",
                "ianaTimezone": "Europe/Amsterdam",
            }
        },
    ),
    "list_locations": (
        {},
        {
            "locations": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [
                    {
                        "id": LOCATION_A,
                        "name": "W",
                        "isActive": True,
                        "fulfillsOnlineOrders": True,
                        "shipsInventory": True,
                    }
                ],
            }
        },
    ),
    "list_inventory_items": (
        {},
        {
            "inventoryItems": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [inventory_item_node()],
            }
        },
    ),
    "get_inventory_item": (
        {"inventory_item_id": ITEM_A},
        {"inventoryItem": inventory_item_node()},
    ),
    "get_inventory_levels_batch": (
        {"location_id": LOCATION_A, "inventory_item_ids": [ITEM_A]},
        {"nodes": [{**inventory_item_node(), "inventoryLevel": inventory_level()}]},
    ),
}

OPERATION_IDS = list(CASES)


def _run(operation_id: str, http: FakeHttp) -> dict:
    from runtime.transport import ShopifyGraphQLTransport

    operation_input, answer = CASES[operation_id]
    if answer is not None:
        http.queue(graphql_response(answer))
    payload = connection_payload(operation_id, operation_input)
    if "connection_ref" not in OPERATIONS_BY_ID[operation_id].input_field_names:
        # The pre-save check runs before a connection exists, so it takes none.
        del payload["action"]["input"]["connection_ref"]
    return handle_runtime(
        payload, transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http)
    )


class TestTheResultMatchesTheDeclaredOutputs:
    def test_connection_capabilities_have_human_and_machine_shapes(self, http: FakeHttp) -> None:
        response = _run("test_connection", http)
        result = response["result"]

        assert result["capabilities"]
        assert all(isinstance(operation_id, str) for operation_id in result["capabilities"])
        assert isinstance(result["capability_scope_matrix"], dict)
        assert all(
            set(details)
            == {
                "scope_eligible",
                "required_oauth_scopes",
                "missing_required_oauth_scopes",
            }
            for details in result["capability_scope_matrix"].values()
        )

    def test_connection_matrix_value_types_are_enforced_by_the_published_schema(self) -> None:
        output = next(
            output
            for output in OPERATIONS_BY_ID["test_connection"].outputs
            if output.name == "capability_scope_matrix"
        )
        malformed = {
            "get_shop": {
                "scope_eligible": "yes",
                "required_oauth_scopes": [],
                "missing_required_oauth_scopes": [],
            }
        }

        with pytest.raises(ExtensionError):
            schema.validate(malformed, output.schema or {}, path="result.capability_scope_matrix")

    @pytest.mark.parametrize("operation_id", OPERATION_IDS)
    def test_a_successful_result_carries_exactly_the_declared_fields(
        self, operation_id: str, http: FakeHttp
    ) -> None:
        response = _run(operation_id, http)

        assert response["ok"] is True, response
        assert set(response["result"]) == set(OPERATIONS_BY_ID[operation_id].result_fields)

    @pytest.mark.parametrize("operation_id", OPERATION_IDS)
    def test_every_result_field_matches_its_published_schema(
        self, operation_id: str, http: FakeHttp
    ) -> None:
        response = _run(operation_id, http)
        row = OPERATIONS_BY_ID[operation_id]

        for output in row.outputs:
            if output.schema is None:
                continue
            schema.validate(
                response["result"][output.name],
                output.schema,
                path=f"result.{output.name}",
            )

    def test_a_confirmed_mutation_carries_exactly_the_declared_fields(self, http: FakeHttp) -> None:
        from runtime.transport import ShopifyGraphQLTransport

        http.queue(adjustment_group_response())

        response = handle_runtime(
            set_quantities_payload([quantity()]),
            transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
        )

        assert set(response["result"]) == set(
            OPERATIONS_BY_ID["set_inventory_quantities"].result_fields
        )

    def test_a_suppressed_mutation_carries_the_same_fields(self) -> None:
        """A rehearsal must not hand a workflow a differently-shaped result."""
        response = handle_runtime(
            set_quantities_payload([quantity()], test_mode=True),
            transport_factory=lambda c: None,
        )

        assert set(response["result"]) == set(
            OPERATIONS_BY_ID["set_inventory_quantities"].result_fields
        )

    def test_the_mutation_result_validates_against_its_schema(self, http: FakeHttp) -> None:
        from runtime.transport import ShopifyGraphQLTransport

        http.queue(adjustment_group_response())

        response = handle_runtime(
            set_quantities_payload([quantity()]),
            transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
        )
        row = OPERATIONS_BY_ID["set_inventory_quantities"]

        for output in row.outputs:
            if output.schema is not None:
                schema.validate(
                    response["result"][output.name],
                    output.schema,
                    path=f"result.{output.name}",
                )


class TestTheEntrypointBoundsAndSanitizesItsOutput:
    def _entrypoint(self, payload: object) -> tuple[int, dict]:
        process = subprocess.run(
            [sys.executable, "main.py"],
            cwd=str(BUNDLE_ROOT),
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            check=False,
        )
        return process.returncode, json.loads(process.stdout.decode("utf-8"))

    def test_a_control_character_in_a_result_is_replaced_and_flagged(self, http: FakeHttp) -> None:
        from main import _bounded_serialized_response

        sanitized, serialized = _bounded_serialized_response(
            {"ok": True, "result": {"shop": {"name": "Acme\x07Store"}}}
        )

        assert sanitized["result"]["shop"]["name"] == "Acme Store"
        assert sanitized["output_sanitized"] is True
        assert b"\x07" not in serialized

    def test_ordinary_whitespace_is_left_alone(self) -> None:
        from main import _bounded_serialized_response

        sanitized, _serialized = _bounded_serialized_response(
            {"ok": True, "result": {"note": "one\ttwo\nthree\r"}}
        )

        assert sanitized["result"]["note"] == "one\ttwo\nthree\r"
        assert "output_sanitized" not in sanitized

    def test_an_oversized_result_is_refused_rather_than_truncated(self) -> None:
        from main import MAX_SERIALIZED_RESPONSE_BYTES, _bounded_serialized_response

        sanitized, _serialized = _bounded_serialized_response(
            {"ok": True, "result": {"blob": "x" * (MAX_SERIALIZED_RESPONSE_BYTES + 1)}}
        )

        assert sanitized["ok"] is False
        assert sanitized["error_code"] == "response_too_large"

    def test_the_output_is_one_line_of_compact_json(self) -> None:
        process = subprocess.run(
            [sys.executable, "main.py"],
            cwd=str(BUNDLE_ROOT),
            input=json.dumps(
                {
                    "mode": "action",
                    "action": {
                        "action_id": "validate_connection_settings",
                        "input": {"shop_domain": "acme"},
                    },
                }
            ).encode("utf-8"),
            capture_output=True,
            check=False,
        )

        assert process.stdout.endswith(b"\n")
        assert process.stdout.count(b"\n") == 1
        assert process.stderr == b""

    def test_an_empty_request_is_refused(self) -> None:
        code, response = self._entrypoint({})

        assert code == 2
        assert response["error_code"] in {"invalid_payload", "unsupported_operation"}
