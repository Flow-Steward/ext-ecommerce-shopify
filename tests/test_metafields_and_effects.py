"""Metafield compare-and-set, action suppression, and mutation confirmation.

These are the rules that decide whether a workflow is told the truth about what
happened in the store, so they are tested against the real runtime rather than
against the shapes in isolation.
"""

from __future__ import annotations

import json
from typing import ClassVar

import pytest
from conftest import (
    ACCESS_TOKEN,
    ORDER_A,
    PRODUCT_A,
    VARIANT_A,
    FakeHttp,
    FakeResponse,
    graphql_response,
    metafield_node,
    run_action,
)
from runtime import errors
from runtime.catalog import ACTION_OPERATION_IDS, OPERATIONS_BY_ID
from runtime.transport import MAX_REQUEST_BODY_BYTES


def entry(
    *,
    owner_id: str = PRODUCT_A,
    namespace: str = "custom",
    key: str = "care",
    value: str = "hand wash",
    compare_digest: str | None = "digest-1",
) -> dict:
    return {
        "owner_id": owner_id,
        "namespace": namespace,
        "key": key,
        "type": "single_line_text_field",
        "value": value,
        "compare_digest": compare_digest,
    }


def answer(*nodes: dict) -> FakeResponse:
    return graphql_response({"metafieldsSet": {"metafields": list(nodes), "userErrors": []}})


class TestCompareAndSet:
    def test_the_digest_travels_to_shopify(self, http: FakeHttp) -> None:
        http.queue(answer(metafield_node(owner={"__typename": "Product", "id": PRODUCT_A})))

        run_action("set_catalog_metafields", {"metafields": [entry()]}, http)

        sent = http.variables()["metafields"][0]
        assert sent["compareDigest"] == "digest-1"
        assert set(sent) == {"ownerId", "namespace", "key", "type", "value", "compareDigest"}

    def test_an_explicit_null_means_create_only(self, http: FakeHttp) -> None:
        http.queue(answer(metafield_node(owner={"__typename": "Product", "id": PRODUCT_A})))

        run_action("set_catalog_metafields", {"metafields": [entry(compare_digest=None)]}, http)

        assert http.variables()["metafields"][0]["compareDigest"] is None

    def test_omitting_the_digest_entirely_is_refused(self, http: FakeHttp) -> None:
        """A missing key would mean "overwrite whatever is there".

        That is precisely the outcome compare-and-set exists to prevent, so the
        third, silent meaning is not available: send a digest, or send null.
        """
        without = entry()
        del without["compare_digest"]

        response = run_action("set_catalog_metafields", {"metafields": [without]}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert "compare_digest" in response["error"]
        assert http.requests == []

    def test_duplicate_owner_namespace_key_tuples_are_refused(self, http: FakeHttp) -> None:
        response = run_action(
            "set_catalog_metafields",
            {"metafields": [entry(value="a"), entry(value="b")]},
            http,
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_the_same_key_on_two_owners_is_allowed(self, http: FakeHttp) -> None:
        http.queue(
            answer(
                metafield_node(owner={"__typename": "Product", "id": PRODUCT_A}),
                metafield_node(owner={"__typename": "ProductVariant", "id": VARIANT_A}),
            )
        )

        response = run_action(
            "set_catalog_metafields",
            {"metafields": [entry(), entry(owner_id=VARIANT_A)]},
            http,
        )

        assert response["ok"] is True

    @pytest.mark.parametrize("count", [1, 25])
    def test_the_batch_bounds_are_one_and_twenty_five(self, count: int, http: FakeHttp) -> None:
        entries = [entry(key=f"k{index}") for index in range(count)]
        http.queue(
            answer(
                *[
                    metafield_node(
                        key=f"k{index}", owner={"__typename": "Product", "id": PRODUCT_A}
                    )
                    for index in range(count)
                ]
            )
        )

        response = run_action("set_catalog_metafields", {"metafields": entries}, http)

        assert response["ok"] is True
        assert len(response["result"]["metafields"]) == count

    @pytest.mark.parametrize("count", [0, 26])
    def test_a_batch_outside_the_bounds_is_refused(self, count: int, http: FakeHttp) -> None:
        entries = [entry(key=f"k{index}") for index in range(count)]

        response = run_action("set_catalog_metafields", {"metafields": entries}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_the_one_mebibyte_request_limit_is_not_raised_for_metafields(
        self, http: FakeHttp
    ) -> None:
        """Shopify allows 10 MB; this extension still sends at most 1 MiB.

        The transport's limit is a property of the extension, not of the
        endpoint, and quietly raising it for one operation would remove the
        bound every other operation relies on.
        """
        huge = entry(value="x" * (MAX_REQUEST_BODY_BYTES + 10))

        response = run_action("set_catalog_metafields", {"metafields": [huge]}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert MAX_REQUEST_BODY_BYTES == 1024 * 1024

    def test_owner_types_are_enforced_per_operation(self, http: FakeHttp) -> None:
        catalog = run_action(
            "set_catalog_metafields", {"metafields": [entry(owner_id=ORDER_A)]}, http
        )
        order = run_action(
            "set_order_metafields", {"metafields": [entry(owner_id=PRODUCT_A)]}, http
        )

        assert catalog["error_code"] == errors.INVALID_PAYLOAD
        assert order["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []


class TestMetafieldsAreCorrelatedByTheirNaturalKey:
    def test_a_reordered_answer_still_lines_up(self, http: FakeHttp) -> None:
        """A metafield has no caller-supplied id, so owner/namespace/key is it."""
        http.queue(
            answer(
                metafield_node(key="b", owner={"__typename": "Product", "id": PRODUCT_A}),
                metafield_node(key="a", owner={"__typename": "Product", "id": PRODUCT_A}),
            )
        )

        response = run_action(
            "set_catalog_metafields",
            {"metafields": [entry(key="a"), entry(key="b")]},
            http,
        )

        assert [m["key"] for m in response["result"]["metafields"]] == ["a", "b"]

    def test_every_confirmed_metafield_carries_its_new_digest(self, http: FakeHttp) -> None:
        http.queue(answer(metafield_node(owner={"__typename": "Product", "id": PRODUCT_A})))

        response = run_action("set_catalog_metafields", {"metafields": [entry()]}, http)

        assert response["result"]["metafields"][0]["compare_digest"] == "digest-2"
        assert response["result"]["metafields"][0]["owner_id"] == PRODUCT_A

    @pytest.mark.parametrize(
        "returned",
        [
            (),
            (metafield_node(key="other", owner={"__typename": "Product", "id": PRODUCT_A}),),
            (
                metafield_node(owner={"__typename": "Product", "id": PRODUCT_A}),
                metafield_node(owner={"__typename": "Product", "id": PRODUCT_A}),
            ),
            (metafield_node(owner={"__typename": "ProductVariant", "id": VARIANT_A}),),
        ],
    )
    def test_an_answer_that_cannot_be_matched_is_unknown(
        self, returned: tuple, http: FakeHttp
    ) -> None:
        http.queue(answer(*returned))

        response = run_action("set_catalog_metafields", {"metafields": [entry()]}, http)

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN
        assert response["definitely_no_external_effect"] is False


class TestEveryActionSuppressesInTestMode:
    #: One valid, minimal request per action.
    REQUESTS: ClassVar[dict[str, dict]] = {
        "set_inventory_quantities": {
            "quantities": [
                {
                    "inventory_item_id": "gid://shopify/InventoryItem/1001",
                    "location_id": "gid://shopify/Location/2001",
                    "quantity": 1,
                    "change_from_quantity": None,
                }
            ]
        },
        "create_products_bulk": {"products": [{"title": "Draft", "handle": "draft-bulk"}]},
        "create_product": {"title": "Boots", "handle": "boots"},
        "update_product": {"product_id": PRODUCT_A, "vendor": "Acme"},
        "create_product_variants_batch": {
            "product_id": PRODUCT_A,
            "variants": [{"option_values": [{"option_name": "Size", "value": "42"}]}],
        },
        "update_product_variants_batch": {
            "product_id": PRODUCT_A,
            "variants": [{"variant_id": VARIANT_A, "price": "1.00"}],
        },
        "set_catalog_metafields": {"metafields": [entry()]},
        "update_product_media_alt": {"media_id": "gid://shopify/MediaImage/6001", "alt": "a"},
        "update_order_metadata": {"order_id": ORDER_A, "note": "x"},
        "set_order_metafields": {"metafields": [entry(owner_id=ORDER_A)]},
        "create_fulfillment": {
            "fulfillment_orders": [
                {
                    "fulfillment_order_id": "gid://shopify/FulfillmentOrder/8001",
                    "line_items": [
                        {
                            "fulfillment_order_line_item_id": (
                                "gid://shopify/FulfillmentOrderLineItem/8101"
                            ),
                            "quantity": 1,
                        }
                    ],
                }
            ]
        },
        "update_fulfillment_tracking": {
            "fulfillment_id": "gid://shopify/Fulfillment/9001",
            "tracking": {"numbers": ["TRK1"]},
        },
    }

    def test_every_action_has_a_request_here(self) -> None:
        assert set(self.REQUESTS) == set(ACTION_OPERATION_IDS)
        assert len(self.REQUESTS) == 12

    @pytest.mark.parametrize("operation_id", ACTION_OPERATION_IDS)
    def test_it_suppresses_before_any_request(self, operation_id: str, http: FakeHttp) -> None:
        response = run_action(operation_id, self.REQUESTS[operation_id], http, test_mode=True)

        assert response["ok"] is True
        assert response["external_effect_status"] == "suppressed"
        assert response["definitely_no_external_effect"] is True
        assert http.requests == []

    @pytest.mark.parametrize("operation_id", ACTION_OPERATION_IDS)
    def test_it_suppresses_before_a_transport_is_constructed(self, operation_id: str) -> None:
        from conftest import action_payload
        from runtime.operations import handle_runtime

        def explode(connection: object) -> object:  # pragma: no cover - must never run
            raise AssertionError("a transport was constructed in test mode")

        response = handle_runtime(
            action_payload(operation_id, self.REQUESTS[operation_id], test_mode=True),
            transport_factory=explode,
        )

        assert response["external_effect_status"] == "suppressed"

    @pytest.mark.parametrize("operation_id", ACTION_OPERATION_IDS)
    def test_the_suppressed_result_is_valid_against_its_own_schema(
        self, operation_id: str, http: FakeHttp
    ) -> None:
        """A rehearsal must hand back the shape a real run would.

        The first release returned a result its own schema rejected, so a
        workflow binding to it worked in production and broke in test mode.
        """
        from runtime import schema

        row = OPERATIONS_BY_ID[operation_id]
        response = run_action(operation_id, self.REQUESTS[operation_id], http, test_mode=True)

        assert set(response["result"]) == set(row.result_fields)
        for output in row.outputs:
            if output.schema is not None:
                schema.validate(
                    response["result"][output.name],
                    output.schema,
                    path=f"result.{output.name}",
                )

    @pytest.mark.parametrize("operation_id", ACTION_OPERATION_IDS)
    def test_it_needs_no_external_effect_id_in_test_mode(
        self, operation_id: str, http: FakeHttp
    ) -> None:
        response = run_action(
            operation_id,
            self.REQUESTS[operation_id],
            http,
            test_mode=True,
            external_effect_id=None,
        )

        assert response["ok"] is True

    @pytest.mark.parametrize("operation_id", ACTION_OPERATION_IDS)
    def test_a_real_run_requires_the_external_effect_id(
        self, operation_id: str, http: FakeHttp
    ) -> None:
        response = run_action(
            operation_id, self.REQUESTS[operation_id], http, external_effect_id=None
        )

        assert response["error_code"] == errors.MISSING_IDEMPOTENCY_KEY
        assert http.requests == []

    @pytest.mark.parametrize("operation_id", ACTION_OPERATION_IDS)
    def test_an_invalid_request_is_still_refused_in_test_mode(
        self, operation_id: str, http: FakeHttp
    ) -> None:
        """A rehearsal that accepts what the real run refuses teaches nothing."""
        response = run_action(operation_id, {}, http, test_mode=True)

        assert response["error_code"] == errors.INVALID_PAYLOAD


class TestOnlyInventoryClaimsShopifyIdempotency:
    def test_the_inventory_mutation_still_sends_its_idempotency_key(self, http: FakeHttp) -> None:
        from conftest import adjustment_group_response, quantity

        http.queue(adjustment_group_response())

        run_action("set_inventory_quantities", {"quantities": [quantity()]}, http)

        assert "idempotencyKey" in http.variables()

    @pytest.mark.parametrize(
        "operation_id",
        [name for name in ACTION_OPERATION_IDS if name != "set_inventory_quantities"],
    )
    def test_no_new_action_pretends_to_be_idempotent(self, operation_id: str) -> None:
        """`@idempotent` is a Shopify feature, not a wrapper this side can add.

        Sending the host's effect id as an idempotency key where Shopify does
        not support one would look like duplicate protection and provide none.
        """
        from runtime.documents import DOCUMENTS

        document = DOCUMENTS[operation_id]

        assert "@idempotent" not in document
        assert "idempotencyKey" not in document


class TestNothingLeaksIntoOutput:
    def test_no_action_result_carries_the_token(self, http: FakeHttp) -> None:
        http.queue(answer(metafield_node(owner={"__typename": "Product", "id": PRODUCT_A})))

        response = run_action("set_catalog_metafields", {"metafields": [entry()]}, http)

        assert ACCESS_TOKEN not in json.dumps(response)

    def test_shopifys_user_error_text_is_never_echoed(self, http: FakeHttp) -> None:
        leak = "customer someone@example.test refused the charge"
        http.queue(
            graphql_response(
                {
                    "metafieldsSet": {
                        "metafields": [],
                        "userErrors": [
                            {"code": "INVALID_VALUE", "field": ["value"], "message": leak}
                        ],
                    }
                }
            )
        )

        response = run_action("set_catalog_metafields", {"metafields": [entry()]}, http)

        assert response["error_code"] == errors.UPSTREAM_VALIDATION_FAILED
        assert leak not in json.dumps(response)
        assert "someone@example.test" not in json.dumps(response)

    def test_the_submitted_value_is_never_echoed_back_in_an_error(self, http: FakeHttp) -> None:
        secret_looking = "a merchant note nobody else should read"
        http.queue(
            graphql_response(
                {"metafieldsSet": {"metafields": [], "userErrors": [{"code": "X", "field": None}]}}
            )
        )

        response = run_action(
            "set_catalog_metafields", {"metafields": [entry(value=secret_looking)]}, http
        )

        assert secret_looking not in json.dumps(response)
