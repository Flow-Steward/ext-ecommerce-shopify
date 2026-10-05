"""The one operation that changes the store.

Setting stock is an intentional business effect, not a harmless read: a quantity
of zero makes an item unpurchasable at that location. Everything here is about
refusing a batch that would do the wrong thing, and about never reporting a
result the extension did not actually get from Shopify.
"""

from __future__ import annotations

import json

import pytest
from conftest import (
    ACCESS_TOKEN,
    EXTERNAL_EFFECT_ID,
    ITEM_A,
    ITEM_B,
    LOCATION_A,
    LOCATION_B,
    FakeHttp,
    adjustment_group_response,
    graphql_response,
    quantity,
    set_quantities_payload,
)

from runtime import documents, errors
from runtime.operations import handle_runtime


def run(quantities: list[dict], http: FakeHttp, **kwargs) -> dict:
    from runtime.transport import ShopifyGraphQLTransport

    return handle_runtime(
        set_quantities_payload(quantities, **kwargs),
        transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
    )


class TestTheBatchSizeLimits:
    def test_one_entry_is_a_valid_batch(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response())

        response = run([quantity()], http)

        assert response["ok"] is True
        assert len(http.variables()["input"]["quantities"]) == 1

    def test_two_hundred_and_fifty_entries_are_a_valid_batch(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response(changes=[]))
        quantities = [
            quantity(inventory_item_id=f"gid://shopify/InventoryItem/{index}", value=index)
            for index in range(1, 251)
        ]

        response = run(quantities, http)

        assert response["ok"] is True
        assert len(http.variables()["input"]["quantities"]) == 250

    def test_an_empty_batch_is_refused(self, http: FakeHttp) -> None:
        response = run([], http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_a_batch_of_two_hundred_and_fifty_one_is_refused(self, http: FakeHttp) -> None:
        quantities = [
            quantity(inventory_item_id=f"gid://shopify/InventoryItem/{index}")
            for index in range(1, 252)
        ]

        response = run(quantities, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_an_oversized_batch_is_never_split_into_several_calls(self, http: FakeHttp) -> None:
        quantities = [
            quantity(inventory_item_id=f"gid://shopify/InventoryItem/{index}")
            for index in range(1, 400)
        ]

        run(quantities, http)

        assert http.requests == []


class TestTheNestedQuantityContract:
    def test_an_entry_with_no_fields_at_all_is_refused_locally(self, http: FakeHttp) -> None:
        response = run([{}], http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    @pytest.mark.parametrize(
        "missing",
        ["inventory_item_id", "location_id", "quantity", "change_from_quantity"],
    )
    def test_every_nested_field_is_required(self, missing: str, http: FakeHttp) -> None:
        entry = quantity()
        del entry[missing]

        response = run([entry], http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert missing in response["error"]
        assert http.requests == []

    def test_an_unknown_nested_field_is_refused(self, http: FakeHttp) -> None:
        response = run([{**quantity(), "compare_quantity": 3}], http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_an_unknown_outer_field_is_refused(self, http: FakeHttp) -> None:
        from conftest import connection_payload

        payload = connection_payload(
            "set_inventory_quantities",
            {"quantities": [quantity()], "ignore_compare_quantity": True},
            runtime_context={"external_effect_id": EXTERNAL_EFFECT_ID},
        )

        response = handle_runtime(payload, transport_factory=lambda c: None)

        assert response["error_code"] == errors.INVALID_PAYLOAD

    @pytest.mark.parametrize("value", [-1, 1.5, "7", True, None, 2_147_483_648])
    def test_a_quantity_that_is_not_a_non_negative_int_is_refused(
        self, value: object, http: FakeHttp
    ) -> None:
        response = run([quantity(value=value)], http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_zero_is_an_accepted_quantity(self, http: FakeHttp) -> None:
        """Setting stock to zero is intentional, so it must reach Shopify."""
        http.queue(adjustment_group_response(changes=[]))

        response = run([quantity(value=0)], http)

        assert response["ok"] is True
        assert http.variables()["input"]["quantities"][0]["quantity"] == 0

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("inventory_item_id", LOCATION_A),
            ("inventory_item_id", "gid://shopify/Product/1"),
            ("inventory_item_id", "1001"),
            ("location_id", ITEM_A),
            ("location_id", "gid://shopify/Location/abc"),
        ],
    )
    def test_an_id_of_the_wrong_type_is_refused_before_transport(
        self, field: str, value: str, http: FakeHttp
    ) -> None:
        response = run([{**quantity(), field: value}], http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_the_same_item_at_the_same_location_may_not_appear_twice(self, http: FakeHttp) -> None:
        response = run([quantity(value=1), quantity(value=2)], http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_the_same_item_at_two_locations_is_allowed(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response(changes=[]))

        response = run([quantity(location_id=LOCATION_A), quantity(location_id=LOCATION_B)], http)

        assert response["ok"] is True

    def test_two_items_at_the_same_location_are_allowed(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response(changes=[]))

        response = run(
            [quantity(inventory_item_id=ITEM_A), quantity(inventory_item_id=ITEM_B)], http
        )

        assert response["ok"] is True


class TestCompareAndSwap:
    def test_an_explicit_null_opts_out_and_is_still_sent(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response())

        run([quantity(change_from_quantity=None)], http)

        entry = http.variables()["input"]["quantities"][0]
        assert "changeFromQuantity" in entry
        assert entry["changeFromQuantity"] is None

    def test_an_integer_is_sent_as_the_last_known_quantity(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response())

        run([quantity(change_from_quantity=5)], http)

        assert http.variables()["input"]["quantities"][0]["changeFromQuantity"] == 5

    def test_zero_is_a_meaningful_last_known_quantity(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response())

        run([quantity(change_from_quantity=0)], http)

        assert http.variables()["input"]["quantities"][0]["changeFromQuantity"] == 0

    @pytest.mark.parametrize("value", [-1, 1.5, "5", True])
    def test_an_unusable_last_known_quantity_is_refused(
        self, value: object, http: FakeHttp
    ) -> None:
        response = run([quantity(change_from_quantity=value)], http)

        assert response["error_code"] == errors.INVALID_PAYLOAD

    def test_the_field_is_always_present_on_every_entry(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response(changes=[]))

        run(
            [
                quantity(inventory_item_id=ITEM_A, change_from_quantity=None),
                quantity(inventory_item_id=ITEM_B, change_from_quantity=3),
            ],
            http,
        )

        for entry in http.variables()["input"]["quantities"]:
            assert "changeFromQuantity" in entry

    @pytest.mark.parametrize("field", documents.FORBIDDEN_CAS_FIELDS)
    def test_the_deprecated_compare_and_swap_fields_appear_nowhere(self, field: str) -> None:
        assert field not in documents.SET_INVENTORY_QUANTITIES
        for document in documents.DOCUMENTS.values():
            assert field not in document

    def test_the_deprecated_fields_cannot_be_sent_either(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response())

        run([quantity(change_from_quantity=1)], http)

        body = json.dumps(http.json_body())
        for field in documents.FORBIDDEN_CAS_FIELDS:
            assert field not in body


class TestIdempotency:
    def test_the_document_declares_the_key_and_the_directive(self) -> None:
        document = documents.SET_INVENTORY_QUANTITIES

        assert "$idempotencyKey: String!" in document
        assert "inventorySetQuantities(input: $input) @idempotent(key: $idempotencyKey)" in (
            document
        )

    def test_the_hosts_external_effect_id_is_the_key(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response())

        run([quantity()], http)

        assert http.variables()["idempotencyKey"] == EXTERNAL_EFFECT_ID

    def test_the_same_id_becomes_the_reference_document_uri(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response())

        run([quantity()], http)

        assert http.variables()["input"]["referenceDocumentUri"] == (
            f"gid://flow-steward/ExternalEffect/{EXTERNAL_EFFECT_ID}"
        )

    def test_a_real_invocation_without_an_external_effect_id_is_refused(
        self, http: FakeHttp
    ) -> None:
        response = run([quantity()], http, external_effect_id=None)

        assert response["error_code"] == errors.MISSING_IDEMPOTENCY_KEY
        assert http.requests == []

    @pytest.mark.parametrize(
        "external_effect_id",
        ["", "   ", "has space", "has/slash", "has?query", "../escape", "a" * 129, "#hash"],
    )
    def test_an_unusable_external_effect_id_is_refused(
        self, external_effect_id: str, http: FakeHttp
    ) -> None:
        response = run([quantity()], http, external_effect_id=external_effect_id)

        assert response["error_code"] == errors.MISSING_IDEMPOTENCY_KEY
        assert http.requests == []

    def test_no_key_is_invented_when_the_host_supplies_none(self, http: FakeHttp) -> None:
        from conftest import connection_payload

        payload = connection_payload(
            "set_inventory_quantities", {"quantities": [quantity()]}, runtime_context=None
        )

        response = handle_runtime(payload, transport_factory=lambda c: None)

        assert response["error_code"] == errors.MISSING_IDEMPOTENCY_KEY


class TestTheFixedMutationInput:
    def test_the_quantity_name_and_reason_are_not_the_callers_to_choose(
        self, http: FakeHttp
    ) -> None:
        http.queue(adjustment_group_response())

        run([quantity()], http)

        assert http.variables()["input"]["name"] == "available"
        assert http.variables()["input"]["reason"] == "correction"

    def test_the_document_sent_is_the_fixed_one(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response())

        run([quantity()], http)

        assert http.document() == documents.SET_INVENTORY_QUANTITIES

    def test_each_entry_carries_exactly_the_four_shopify_fields(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response())

        run([quantity(change_from_quantity=2)], http)

        assert set(http.variables()["input"]["quantities"][0]) == {
            "inventoryItemId",
            "locationId",
            "quantity",
            "changeFromQuantity",
        }

    def test_the_mutation_input_carries_exactly_the_four_declared_keys(
        self, http: FakeHttp
    ) -> None:
        http.queue(adjustment_group_response())

        run([quantity()], http)

        assert set(http.variables()["input"]) == {
            "name",
            "reason",
            "referenceDocumentUri",
            "quantities",
        }
        assert set(http.variables()) == {"input", "idempotencyKey"}


class TestTheResult:
    def test_an_unchanged_cas_batch_succeeds_without_an_adjustment_group(
        self, http: FakeHttp
    ) -> None:
        http.queue(
            graphql_response(
                {
                    "inventorySetQuantities": {
                        "inventoryAdjustmentGroup": None,
                        "userErrors": [],
                    }
                }
            )
        )

        response = run(
            [
                quantity(inventory_item_id=ITEM_A, value=50, change_from_quantity=50),
                quantity(inventory_item_id=ITEM_B, value=20, change_from_quantity=20),
            ],
            http,
        )

        assert response["ok"] is True
        assert response["result"]["inventory_adjustment_group"] is None
        assert response["external_effect_status"] == "succeeded"
        assert response["definitely_no_external_effect"] is False

    def test_a_confirmed_write_reports_the_adjustment_group(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response())

        response = run([quantity()], http)

        assert response["result"]["inventory_adjustment_group"] == {
            "id": "gid://shopify/InventoryAdjustmentGroup/3001",
            "created_at": "2026-08-28T09:00:00Z",
            "reason": "Inventory correction",
            "reference_document_uri": (f"gid://flow-steward/ExternalEffect/{EXTERNAL_EFFECT_ID}"),
            "changes": [
                {
                    "inventory_item_id": ITEM_A,
                    "location_id": LOCATION_A,
                    "name": "available",
                    "delta": 2,
                    "quantity_after_change": 7,
                    "ledger_document_uri": None,
                }
            ],
        }

    def test_a_confirmed_write_reports_the_effect_as_succeeded(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response())

        response = run([quantity()], http)

        assert response["external_effect_status"] == "succeeded"
        assert response["definitely_no_external_effect"] is False
        assert response["result"]["external_effect_status"] == "succeeded"

    def test_every_confirmed_change_is_reported_even_beyond_the_batch_size(
        self, http: FakeHttp
    ) -> None:
        """The receipt for a write that already happened must not be truncated.

        One requested quantity can produce several ``InventoryChange`` entries,
        so a batch of 250 can legitimately be confirmed by more than 250
        changes. Silently keeping the first 250 would hand a caller reconciling
        stock an incomplete record of a change Shopify had already applied.
        """
        confirmed = [
            {
                "name": "available",
                "delta": 1,
                "quantityAfterChange": index,
                "item": {"id": f"gid://shopify/InventoryItem/{index}"},
                "location": {"id": LOCATION_A},
            }
            for index in range(600)
        ]
        http.queue(adjustment_group_response(changes=confirmed))

        response = run([quantity()], http)

        reported = response["result"]["inventory_adjustment_group"]["changes"]
        assert len(reported) == 600
        assert reported[-1]["quantity_after_change"] == 599
        assert reported[-1]["inventory_item_id"] == "gid://shopify/InventoryItem/599"

    def test_a_change_shopify_leaves_null_stays_null(self, http: FakeHttp) -> None:
        http.queue(
            adjustment_group_response(
                changes=[
                    {
                        "name": "available",
                        "delta": 1,
                        "quantityAfterChange": None,
                        "item": None,
                        "location": None,
                    }
                ]
            )
        )

        response = run([quantity()], http)

        change = response["result"]["inventory_adjustment_group"]["changes"][0]
        assert change["quantity_after_change"] is None
        assert change["inventory_item_id"] is None


class TestFailuresAreNeverReportedAsSuccess:
    def test_a_user_error_fails_the_action(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "inventorySetQuantities": {
                        "inventoryAdjustmentGroup": None,
                        "userErrors": [
                            {
                                "code": "INVALID_INVENTORY_ITEM",
                                "field": ["input", "quantities", "0"],
                                "message": "Inventory item does not exist",
                            }
                        ],
                    }
                }
            )
        )

        response = run([quantity()], http)

        assert response["ok"] is False
        assert response["error_code"] == errors.UPSTREAM_VALIDATION_FAILED

    def test_a_user_error_alongside_an_adjustment_group_still_fails(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "inventorySetQuantities": {
                        "inventoryAdjustmentGroup": {
                            "id": "gid://shopify/InventoryAdjustmentGroup/1",
                            "createdAt": None,
                            "reason": None,
                            "referenceDocumentUri": None,
                            "changes": [],
                        },
                        "userErrors": [{"code": "STOCK_CHANGED", "field": None, "message": "x"}],
                    }
                }
            )
        )

        response = run([quantity()], http)

        assert response["ok"] is False
        assert response["error_code"] == errors.UPSTREAM_VALIDATION_FAILED

    def test_the_documented_error_code_is_surfaced(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "inventorySetQuantities": {
                        "inventoryAdjustmentGroup": None,
                        "userErrors": [
                            {"code": "STOCK_CHANGED", "field": None, "message": "x"},
                            {"code": "OTHER", "field": None, "message": "y"},
                        ],
                    }
                }
            )
        )

        response = run([quantity()], http)

        assert "STOCK_CHANGED" in response["error"]
        assert "2" in response["error"]

    def test_shopifys_own_message_is_never_echoed(self, http: FakeHttp) -> None:
        secret_looking = "token shpat_leaked_via_a_user_error"  # pragma: allowlist secret
        http.queue(
            graphql_response(
                {
                    "inventorySetQuantities": {
                        "inventoryAdjustmentGroup": None,
                        "userErrors": [
                            {"code": "not an enum", "field": None, "message": secret_looking}
                        ],
                    }
                }
            )
        )

        response = run([quantity()], http)

        assert secret_looking not in json.dumps(response)
        assert "not an enum" not in json.dumps(response)

    def test_an_accepted_request_with_no_adjustment_is_reported_as_unknown(
        self, http: FakeHttp
    ) -> None:
        http.queue(
            graphql_response(
                {
                    "inventorySetQuantities": {
                        "inventoryAdjustmentGroup": None,
                        "userErrors": [],
                    }
                }
            )
        )

        response = run([quantity()], http)

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN
        assert response["external_effect_status"] == "timeout_unknown"
        assert response["definitely_no_external_effect"] is False

    def test_a_missing_adjustment_for_a_mixed_batch_is_reported_as_unknown(
        self, http: FakeHttp
    ) -> None:
        http.queue(
            graphql_response(
                {
                    "inventorySetQuantities": {
                        "inventoryAdjustmentGroup": None,
                        "userErrors": [],
                    }
                }
            )
        )

        response = run(
            [
                quantity(inventory_item_id=ITEM_A, value=50, change_from_quantity=50),
                quantity(inventory_item_id=ITEM_B, value=21, change_from_quantity=20),
            ],
            http,
        )

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN
        assert response["external_effect_status"] == "timeout_unknown"
        assert response["definitely_no_external_effect"] is False

    @pytest.mark.parametrize(
        "mutation_result",
        [
            {"userErrors": []},
            {"inventoryAdjustmentGroup": [], "userErrors": []},
        ],
        ids=["missing-field", "wrong-type"],
    )
    def test_a_malformed_noop_receipt_is_reported_as_unknown(
        self, mutation_result: dict, http: FakeHttp
    ) -> None:
        http.queue(graphql_response({"inventorySetQuantities": mutation_result}))

        response = run([quantity(value=50, change_from_quantity=50)], http)

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN
        assert response["external_effect_status"] == "timeout_unknown"
        assert response["definitely_no_external_effect"] is False


class TestTestMode:
    def test_it_suppresses_before_any_request_is_made(self, http: FakeHttp) -> None:
        response = run([quantity()], http, test_mode=True)

        assert response["ok"] is True
        assert response["external_effect_status"] == "suppressed"
        assert response["definitely_no_external_effect"] is True
        assert http.requests == []

    def test_it_suppresses_before_a_transport_is_even_constructed(self) -> None:
        def explode(connection: object) -> object:  # pragma: no cover - must never run
            raise AssertionError("a transport was constructed in test mode")

        response = handle_runtime(
            set_quantities_payload([quantity()], test_mode=True), transport_factory=explode
        )

        assert response["external_effect_status"] == "suppressed"

    def test_it_does_not_need_an_external_effect_id(self, http: FakeHttp) -> None:
        response = run([quantity()], http, test_mode=True, external_effect_id=None)

        assert response["ok"] is True
        assert response["external_effect_status"] == "suppressed"

    def test_an_invalid_batch_is_still_refused_in_test_mode(self, http: FakeHttp) -> None:
        """A rehearsal that accepts a batch the real run would refuse is useless."""
        response = run([{}], http, test_mode=True)

        assert response["error_code"] == errors.INVALID_PAYLOAD

    def test_a_non_boolean_test_mode_is_refused(self, http: FakeHttp) -> None:
        from conftest import connection_payload

        payload = connection_payload(
            "set_inventory_quantities",
            {"quantities": [quantity()]},
            runtime_context={"test_mode": "yes", "external_effect_id": EXTERNAL_EFFECT_ID},
        )

        response = handle_runtime(payload, transport_factory=lambda c: None)

        assert response["error_code"] == errors.INVALID_PAYLOAD

    def test_a_real_invocation_is_not_suppressed(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response())

        response = run([quantity()], http, test_mode=False)

        assert response["external_effect_status"] == "succeeded"
        assert len(http.requests) == 1


class TestTheTokenNeverAppears:
    def test_not_in_a_success(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response())

        response = run([quantity()], http)

        assert ACCESS_TOKEN not in json.dumps(response)

    def test_not_in_a_failure(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(None, errors=[{"message": "x", "extensions": {"code": "THROTTLED"}}])
        )

        response = run([quantity()], http)

        assert response["ok"] is False
        assert ACCESS_TOKEN not in json.dumps(response)

    def test_it_travels_only_in_the_shopify_header(self, http: FakeHttp) -> None:
        http.queue(adjustment_group_response())

        run([quantity()], http)

        assert http.last["headers"]["x-shopify-access-token"] == ACCESS_TOKEN
        assert ACCESS_TOKEN not in http.last["url"]
        assert ACCESS_TOKEN.encode() not in http.last["body"]
