"""What happens when Shopify's answer does not settle the question.

A mutation has one failure mode worse than failing: succeeding and being
reported as failed, or failing and being reported as done. Everything here is
about the boundary between "this definitely did not happen" and "nobody on this
side can say".
"""

from __future__ import annotations

import json
from typing import ClassVar
from urllib.error import HTTPError, URLError

import pytest
from conftest import (
    ORDER_A,
    PRODUCT_A,
    FakeHttp,
    FakeResponse,
    graphql_response,
    order_node,
    run_action,
    run_operation,
)
from runtime import errors
from runtime.catalog import ACTION_OPERATION_IDS
from runtime.transport import MAX_RESPONSE_BYTES


def update_order(http: FakeHttp, **kwargs) -> dict:
    return run_action("update_order_metadata", {"order_id": ORDER_A, "note": "x"}, http, **kwargs)


class TestAnUnreadableAnswerLeavesTheOutcomeUnknown:
    """Shopify may have applied the write and only the confirmation be unreadable."""

    @pytest.mark.parametrize(
        "response",
        [
            FakeResponse(200, b""),
            FakeResponse(200, b"not json"),
            FakeResponse(200, b"[1,2,3]"),
            FakeResponse(200, b'{"data": 4}'),
            FakeResponse(200, b"x" * (MAX_RESPONSE_BYTES + 1)),
        ],
        ids=["empty", "malformed", "array", "wrong-data-type", "oversized"],
    )
    def test_a_body_this_side_cannot_read_is_unknown(
        self, response: FakeResponse, http: FakeHttp
    ) -> None:
        http.queue(response)

        result = update_order(http)

        assert result["error_code"] == errors.TIMEOUT_UNKNOWN
        assert result["external_effect_status"] == "timeout_unknown"
        assert result["definitely_no_external_effect"] is False

    def test_the_same_bodies_are_plain_failures_for_a_source(self, http: FakeHttp) -> None:
        """A source changed nothing, so an unreadable answer is just a failure."""
        http.queue(FakeResponse(200, b"not json"))

        result = run_operation("get_order", {"order_id": ORDER_A}, http)

        assert result["error_code"] == errors.INVALID_JSON_RESPONSE
        assert "external_effect_status" not in result

    def test_a_missing_mutation_payload_is_unknown(self, http: FakeHttp) -> None:
        http.queue(graphql_response({}))

        result = update_order(http)

        assert result["error_code"] == errors.TIMEOUT_UNKNOWN
        assert result["definitely_no_external_effect"] is False

    def test_a_payload_without_the_resource_is_unknown(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"orderUpdate": {"order": None, "userErrors": []}}))

        result = update_order(http)

        assert result["error_code"] == errors.TIMEOUT_UNKNOWN

    def test_a_resource_returned_alongside_errors_is_unknown(self, http: FakeHttp) -> None:
        """Partial data with top-level errors settles nothing either way."""
        http.queue(
            graphql_response(
                {"orderUpdate": {"order": order_node(), "userErrors": []}},
                errors=[{"message": "partial", "extensions": {"code": "SOMETHING_NEW"}}],
            )
        )

        result = update_order(http)

        assert result["error_code"] == errors.TIMEOUT_UNKNOWN
        assert result["definitely_no_external_effect"] is False

    def test_an_unrecognised_top_level_code_is_unknown_for_a_mutation(self, http: FakeHttp) -> None:
        http.queue(graphql_response(None, errors=[{"extensions": {"code": "BRAND_NEW_CODE"}}]))

        result = update_order(http)

        assert result["error_code"] == errors.TIMEOUT_UNKNOWN

    def test_the_same_code_is_a_plain_failure_for_a_source(self, http: FakeHttp) -> None:
        http.queue(graphql_response(None, errors=[{"extensions": {"code": "BRAND_NEW_CODE"}}]))

        result = run_operation("get_order", {"order_id": ORDER_A}, http)

        assert result["error_code"] == errors.UPSTREAM_FAILURE

    @pytest.mark.parametrize("status", [408, 500, 502, 503, 504])
    def test_a_server_failure_after_sending_is_unknown(self, status: int, http: FakeHttp) -> None:
        http.queue(HTTPError("https://x", status, "boom", {}, None))

        result = update_order(http)

        assert result["error_code"] == errors.TIMEOUT_UNKNOWN

    @pytest.mark.parametrize("failure", [TimeoutError("timed out"), URLError("reset")])
    def test_a_timeout_or_disconnect_after_sending_is_unknown(
        self, failure: BaseException, http: FakeHttp
    ) -> None:
        http.queue(failure)

        result = update_order(http)

        assert result["error_code"] == errors.TIMEOUT_UNKNOWN


class TestAnExplicitRejectionIsDefinite:
    """Only Shopify saying no counts as proof that nothing happened."""

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("THROTTLED", errors.RATE_LIMITED),
            ("ACCESS_DENIED", errors.AUTHORIZATION_FAILED),
            ("SHOP_INACTIVE", errors.SHOP_INACTIVE),
            ("MAX_COST_EXCEEDED", errors.UPSTREAM_VALIDATION_FAILED),
        ],
    )
    def test_a_documented_refusal_is_not_ambiguous(
        self, code: str, expected: str, http: FakeHttp
    ) -> None:
        http.queue(graphql_response(None, errors=[{"extensions": {"code": code}}]))

        result = update_order(http)

        assert result["error_code"] == expected
        assert result["external_effect_status"] == "failed"
        assert result["definitely_no_external_effect"] is True

    def test_user_errors_are_a_definite_refusal(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "orderUpdate": {
                        "order": None,
                        "userErrors": [{"field": ["note"], "message": "too long"}],
                    }
                }
            )
        )

        result = update_order(http)

        assert result["error_code"] == errors.UPSTREAM_VALIDATION_FAILED
        assert "external_effect_status" not in result

    @pytest.mark.parametrize("status", [401, 403, 429])
    def test_a_refusal_before_execution_is_not_ambiguous(self, status: int, http: FakeHttp) -> None:
        http.queue(HTTPError("https://x", status, "no", {}, None))

        result = update_order(http)

        assert result["error_code"] != errors.TIMEOUT_UNKNOWN
        assert result["external_effect_status"] == "failed"
        assert result["definitely_no_external_effect"] is True

    def test_a_local_refusal_never_reaches_shopify_at_all(self, http: FakeHttp) -> None:
        result = run_action("update_order_metadata", {"order_id": ORDER_A}, http)

        assert result["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []


class TestSuccessIsOnlyEverConfirmed:
    def test_a_confirmed_mutation_reports_succeeded(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"orderUpdate": {"order": order_node(), "userErrors": []}}))

        result = update_order(http)

        assert result["ok"] is True
        assert result["external_effect_status"] == "succeeded"
        assert result["definitely_no_external_effect"] is False

    @pytest.mark.parametrize("operation_id", ACTION_OPERATION_IDS)
    def test_every_action_publishes_the_ambiguous_code(self, operation_id: str) -> None:
        from runtime.catalog import OPERATIONS_BY_ID

        assert errors.TIMEOUT_UNKNOWN in OPERATIONS_BY_ID[operation_id].error_codes

    def test_no_source_publishes_the_ambiguous_code(self) -> None:
        from runtime.catalog import OPERATIONS

        for row in OPERATIONS:
            if not row.has_external_effect:
                assert errors.TIMEOUT_UNKNOWN not in row.error_codes, row.operation_id


class TestNothingIsRetriedOrChunked:
    @pytest.mark.parametrize(
        "failure", [TimeoutError("t"), URLError("r"), HTTPError("https://x", 503, "b", {}, None)]
    )
    def test_an_ambiguous_mutation_is_sent_exactly_once(
        self, failure: BaseException, http: FakeHttp
    ) -> None:
        http.queue(failure)

        update_order(http)

        assert len(http.requests) == 1

    def test_a_two_hundred_and_fifty_item_batch_is_one_request(self, http: FakeHttp) -> None:
        variants = [
            {"variant_id": f"gid://shopify/ProductVariant/{index}", "price": "1.00"}
            for index in range(1, 251)
        ]
        http.queue(
            graphql_response(
                {
                    "productVariantsBulkUpdate": {
                        "productVariants": [
                            {
                                "id": f"gid://shopify/ProductVariant/{index}",
                                "product": {"id": PRODUCT_A},
                            }
                            for index in range(1, 251)
                        ],
                        "userErrors": [],
                    }
                }
            )
        )

        response = run_action(
            "update_product_variants_batch",
            {"product_id": PRODUCT_A, "variants": variants},
            http,
        )

        assert response["ok"] is True
        assert len(http.requests) == 1
        assert len(response["result"]["product_variants"]) == 250

    def test_a_confirmed_result_larger_than_a_source_page_is_not_truncated(
        self, http: FakeHttp
    ) -> None:
        """A mutation's receipt is not a page, so a page limit must not clip it."""
        from conftest import adjustment_group_response, quantity

        changes = [
            {
                "name": "available",
                "delta": 1,
                "quantityAfterChange": index,
                "item": {"id": f"gid://shopify/InventoryItem/{index}"},
                "location": {"id": "gid://shopify/Location/2001"},
            }
            for index in range(400)
        ]
        http.queue(adjustment_group_response(changes=changes))

        response = run_action("set_inventory_quantities", {"quantities": [quantity()]}, http)

        reported = response["result"]["inventory_adjustment_group"]["changes"]
        assert len(reported) == 400


class TestOneShopifyRequestPerInvocation:
    #: One valid request per Shopify-contacting operation, minimal.
    CASES: ClassVar[dict[str, dict]] = {
        "test_connection": {},
        "get_shop": {},
        "list_locations": {},
        "list_inventory_items": {},
        "get_inventory_item": {"inventory_item_id": "gid://shopify/InventoryItem/1001"},
        "get_inventory_levels_batch": {
            "location_id": "gid://shopify/Location/2001",
            "inventory_item_ids": ["gid://shopify/InventoryItem/1001"],
        },
        "list_products": {},
        "get_product": {"product_id": PRODUCT_A},
        "list_product_variants": {},
        "get_product_variant": {"product_variant_id": "gid://shopify/ProductVariant/4001"},
        "list_catalog_metafields": {"owner_type": "product", "owner_id": PRODUCT_A},
        "list_product_media": {"product_id": PRODUCT_A},
        "list_orders": {},
        "get_order": {"order_id": ORDER_A},
        "list_order_line_items": {"order_id": ORDER_A},
        "list_order_metafields": {"order_id": ORDER_A},
        "list_order_fulfillment_orders": {"order_id": ORDER_A},
        "get_fulfillment_order": {"fulfillment_order_id": "gid://shopify/FulfillmentOrder/8001"},
        "list_order_fulfillments": {"order_id": ORDER_A},
    }

    @pytest.mark.parametrize("operation_id", sorted(CASES))
    def test_a_source_issues_exactly_one_request(self, operation_id: str, http: FakeHttp) -> None:
        """No preflight lookup, no scope discovery, no second round trip."""
        http.default = graphql_response({})

        run_operation(operation_id, self.CASES[operation_id], http)

        assert len(http.requests) == 1

    def test_every_network_operation_is_covered_here(self) -> None:
        from runtime.catalog import ACTION_OPERATION_IDS, NETWORK_OPERATION_IDS

        covered = set(self.CASES) | set(ACTION_OPERATION_IDS) | {"export_products"}

        assert covered == set(NETWORK_OPERATION_IDS)


class TestUpstreamTextIsNeverEchoed:
    def test_a_graphql_message_does_not_reach_the_caller(self, http: FakeHttp) -> None:
        leak = "Field 'x' on order for someone@example.test"
        http.queue(graphql_response(None, errors=[{"message": leak, "extensions": {"code": "X"}}]))

        result = run_operation("get_order", {"order_id": ORDER_A}, http)

        assert leak not in json.dumps(result)

    def test_an_http_error_body_does_not_reach_the_caller(self, http: FakeHttp) -> None:
        http.queue(HTTPError("https://acme.myshopify.com/secret?token=abc", 500, "b", {}, None))

        result = run_operation("get_order", {"order_id": ORDER_A}, http)

        assert "token=abc" not in json.dumps(result)
        assert "secret" not in json.dumps(result)
