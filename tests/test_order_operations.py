"""Orders, fulfillment orders and fulfillments.

The recurring theme: an order is full of other people's personal data, and this
extension is built so that none of it can leave the shop through here.
"""

from __future__ import annotations

import json

import pytest
from conftest import (
    FULFILLMENT_A,
    FULFILLMENT_ORDER_A,
    FULFILLMENT_ORDER_LINE_A,
    FULFILLMENT_ORDER_LINE_B,
    ORDER_A,
    PRODUCT_A,
    VARIANT_A,
    FakeHttp,
    connection,
    fulfillment_node,
    graphql_response,
    metafield_node,
    order_node,
    run_action,
    run_operation,
)
from runtime import documents, errors


class TestOrdersCarryNoPersonalData:
    #: Everything an order query must never ask Shopify for.
    FORBIDDEN_FIELDS = (
        "customer",
        "email",
        "phone",
        "billingAddress",
        "shippingAddress",
        "customerJourney",
        "paymentGatewayNames",
        "transactions",
        "clientIp",
        "browserIp",
        "paymentCollectionDetails",
        "purchasingEntity",
    )

    @pytest.mark.parametrize(
        "document",
        [
            documents.LIST_ORDERS,
            documents.GET_ORDER,
            documents.LIST_ORDER_LINE_ITEMS,
            documents.UPDATE_ORDER_METADATA,
        ],
    )
    def test_no_order_document_asks_for_contact_or_payment_data(self, document: str) -> None:
        for field in self.FORBIDDEN_FIELDS:
            assert field not in document, field

    def test_the_shaped_order_carries_only_the_declared_keys(self, http: FakeHttp) -> None:
        """Even if a future document over-asked, the shape would drop it."""
        node = order_node()
        node["customer"] = {"email": "someone@example.test"}
        node["shippingAddress"] = {"address1": "1 Main St"}
        http.queue(graphql_response({"order": node}))

        response = run_operation("get_order", {"order_id": ORDER_A}, http)

        order = response["result"]["order"]
        assert "customer" not in order
        assert "shipping_address" not in order
        assert "someone@example.test" not in json.dumps(response)

    def test_money_stays_a_decimal_string(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"order": order_node()}))

        response = run_operation("get_order", {"order_id": ORDER_A}, http)

        total = response["result"]["order"]["total_price"]
        assert total == {"amount": "19.99", "currency_code": "EUR"}
        assert isinstance(total["amount"], str)


class TestOrderSources:
    def test_line_items_come_back_with_their_product_and_variant(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "order": {
                        "id": ORDER_A,
                        "lineItems": connection(
                            [
                                {
                                    "id": "gid://shopify/LineItem/1",
                                    "title": "Boots",
                                    "name": "Boots - 42",
                                    "sku": "SKU-1",
                                    "quantity": 2,
                                    "currentQuantity": 2,
                                    "refundableQuantity": 2,
                                    "unfulfilledQuantity": 2,
                                    "requiresShipping": True,
                                    "product": {"id": PRODUCT_A},
                                    "variant": {"id": VARIANT_A},
                                    "originalUnitPriceSet": {
                                        "shopMoney": {"amount": "9.99", "currencyCode": "EUR"}
                                    },
                                }
                            ]
                        ),
                    }
                }
            )
        )

        response = run_operation("list_order_line_items", {"order_id": ORDER_A}, http)

        item = response["result"]["line_items"][0]
        assert item["product_id"] == PRODUCT_A
        assert item["variant_id"] == VARIANT_A
        assert item["original_unit_price"]["amount"] == "9.99"
        assert item["discounted_total"] is None

    def test_order_metafields_are_owned_by_the_order_that_was_queried(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {"order": {"id": ORDER_A, "metafields": connection([metafield_node()])}}
            )
        )

        response = run_operation("list_order_metafields", {"order_id": ORDER_A}, http)

        assert response["result"]["metafields"][0]["owner_id"] == ORDER_A

    def test_fulfillment_orders_paginate_their_own_line_items(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "order": {
                        "id": ORDER_A,
                        "fulfillmentOrders": connection(
                            [
                                {
                                    "id": FULFILLMENT_ORDER_A,
                                    "status": "OPEN",
                                    "requestStatus": "UNSUBMITTED",
                                    "assignedLocation": {
                                        "name": "Warehouse",
                                        "location": {"id": "gid://shopify/Location/2001"},
                                    },
                                    "lineItems": connection(
                                        [
                                            {
                                                "id": FULFILLMENT_ORDER_LINE_A,
                                                "totalQuantity": 2,
                                                "remainingQuantity": 2,
                                                "lineItem": {"id": "gid://shopify/LineItem/1"},
                                            }
                                        ],
                                        has_next=True,
                                        cursor="lc1",
                                    ),
                                }
                            ]
                        ),
                    }
                }
            )
        )

        response = run_operation(
            "list_order_fulfillment_orders",
            {"order_id": ORDER_A, "line_items_first": 1},
            http,
        )

        group = response["result"]["fulfillment_orders"][0]
        assert group["assigned_location_id"] == "gid://shopify/Location/2001"
        assert group["line_items_page_info"] == {"has_next_page": True, "end_cursor": "lc1"}
        assert http.variables()["lineItemsFirst"] == 1

    def test_fulfillments_report_the_stores_own_total(self, http: FakeHttp) -> None:
        """`Order.fulfillments` has no cursor, so a caller cannot page it.

        Reporting the count Shopify holds is what lets them tell a complete
        answer from a clipped one instead of assuming.
        """
        http.queue(
            graphql_response(
                {
                    "order": {
                        "id": ORDER_A,
                        "fulfillmentsCount": {"count": 7, "precision": "EXACT"},
                        "fulfillments": [fulfillment_node()],
                    }
                }
            )
        )

        response = run_operation("list_order_fulfillments", {"order_id": ORDER_A, "first": 1}, http)

        assert response["result"]["total_count"] == 7
        assert response["result"]["truncated"] is True
        assert len(response["result"]["fulfillments"]) == 1

    def test_a_complete_answer_is_not_marked_truncated(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "order": {
                        "id": ORDER_A,
                        "fulfillmentsCount": {"count": 1, "precision": "EXACT"},
                        "fulfillments": [fulfillment_node()],
                    }
                }
            )
        )

        response = run_operation("list_order_fulfillments", {"order_id": ORDER_A}, http)

        assert response["result"]["truncated"] is False

    def test_a_missing_order_is_not_found(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"order": None}))

        response = run_operation("list_order_line_items", {"order_id": ORDER_A}, http)

        assert response["error_code"] == errors.NOT_FOUND


class TestUpdateOrderMetadata:
    def _answer(self):
        return graphql_response({"orderUpdate": {"order": order_node(), "userErrors": []}})

    def test_only_the_supplied_fields_are_sent(self, http: FakeHttp) -> None:
        http.queue(self._answer())

        run_action("update_order_metadata", {"order_id": ORDER_A, "note": "call first"}, http)

        assert set(http.variables()["input"]) == {"id", "note"}

    def test_the_replace_fields_overwrite_their_whole_list(self, http: FakeHttp) -> None:
        http.queue(self._answer())

        run_action(
            "update_order_metadata",
            {
                "order_id": ORDER_A,
                "replace_tags": ["vip"],
                "replace_custom_attributes": [{"key": "gift", "value": "no"}],
            },
            http,
        )

        sent = http.variables()["input"]
        assert sent["tags"] == ["vip"]
        assert sent["customAttributes"] == [{"key": "gift", "value": "no"}]

    def test_naming_an_order_without_a_change_is_refused(self, http: FakeHttp) -> None:
        response = run_action("update_order_metadata", {"order_id": ORDER_A}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    @pytest.mark.parametrize(
        "field",
        ["email", "phone", "shippingAddress", "customer", "metafields", "localizedFields"],
    )
    def test_customer_and_address_inputs_are_unreachable(self, field: str, http: FakeHttp) -> None:
        response = run_action("update_order_metadata", {"order_id": ORDER_A, field: "x"}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    @pytest.mark.parametrize(
        "operation_input",
        [
            {"order_id": ORDER_A, "note": ""},
            {"order_id": ORDER_A, "po_number": ""},
            {"order_id": ORDER_A, "replace_tags": []},
            {"order_id": ORDER_A, "replace_custom_attributes": []},
        ],
    )
    def test_an_empty_replacement_is_refused(self, operation_input: dict, http: FakeHttp) -> None:
        response = run_action("update_order_metadata", operation_input, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD

    def test_the_result_is_only_what_the_mutation_could_change(self, http: FakeHttp) -> None:
        http.queue(self._answer())

        response = run_action("update_order_metadata", {"order_id": ORDER_A, "note": "x"}, http)

        assert set(response["result"]["order"]) == {
            "id",
            "name",
            "updated_at",
            "tags",
            "note",
            "po_number",
            "custom_attributes",
        }


class TestCreateFulfillment:
    def _answer(self):
        return graphql_response(
            {"fulfillmentCreate": {"fulfillment": fulfillment_node(), "userErrors": []}}
        )

    def _request(self, **overrides):
        request = {
            "fulfillment_orders": [
                {
                    "fulfillment_order_id": FULFILLMENT_ORDER_A,
                    "line_items": [
                        {
                            "fulfillment_order_line_item_id": FULFILLMENT_ORDER_LINE_A,
                            "quantity": 2,
                        }
                    ],
                }
            ]
        }
        request.update(overrides)
        return request

    def test_every_line_item_and_quantity_is_stated(self, http: FakeHttp) -> None:
        """Shopify fulfils everything remaining when line items are omitted.

        An omitted field must not be able to ship goods, so the extension always
        names them and refuses a group that does not.
        """
        http.queue(self._answer())

        run_action("create_fulfillment", self._request(), http)

        groups = http.variables()["fulfillment"]["lineItemsByFulfillmentOrder"]
        assert groups == [
            {
                "fulfillmentOrderId": FULFILLMENT_ORDER_A,
                "fulfillmentOrderLineItems": [{"id": FULFILLMENT_ORDER_LINE_A, "quantity": 2}],
            }
        ]

    def test_the_customer_is_never_notified(self, http: FakeHttp) -> None:
        """`notifyCustomer` lives in the input object Shopify's schema defines.

        The tracking mutation takes it as an argument instead, so the two
        operations hard-code it in different places. Both are false, and both
        are pinned — this is the difference a reader would otherwise trip over.
        """
        http.queue(self._answer())

        run_action("create_fulfillment", self._request(), http)

        assert http.variables()["fulfillment"]["notifyCustomer"] is False
        assert "notifyCustomer" not in documents.CREATE_FULFILLMENT

    def test_no_message_or_origin_address_is_sent(self, http: FakeHttp) -> None:
        http.queue(self._answer())

        run_action("create_fulfillment", self._request(), http)

        sent = http.variables()["fulfillment"]
        assert set(sent) == {"lineItemsByFulfillmentOrder", "notifyCustomer"}

    @pytest.mark.parametrize(
        "line_items",
        [
            [],
            [{"fulfillment_order_line_item_id": FULFILLMENT_ORDER_LINE_A, "quantity": 0}],
            [{"fulfillment_order_line_item_id": FULFILLMENT_ORDER_LINE_A, "quantity": -1}],
            [{"fulfillment_order_line_item_id": FULFILLMENT_ORDER_LINE_A}],
            [{"quantity": 1}],
            [
                {"fulfillment_order_line_item_id": FULFILLMENT_ORDER_LINE_A, "quantity": 1},
                {"fulfillment_order_line_item_id": FULFILLMENT_ORDER_LINE_A, "quantity": 1},
            ],
        ],
    )
    def test_an_unusable_line_item_list_never_reaches_shopify(
        self, line_items: list, http: FakeHttp
    ) -> None:
        response = run_action(
            "create_fulfillment",
            {
                "fulfillment_orders": [
                    {"fulfillment_order_id": FULFILLMENT_ORDER_A, "line_items": line_items}
                ]
            },
            http,
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_a_duplicate_fulfillment_order_is_refused(self, http: FakeHttp) -> None:
        group = {
            "fulfillment_order_id": FULFILLMENT_ORDER_A,
            "line_items": [
                {"fulfillment_order_line_item_id": FULFILLMENT_ORDER_LINE_A, "quantity": 1}
            ],
        }

        response = run_action("create_fulfillment", {"fulfillment_orders": [group, group]}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD

    def test_two_line_items_on_one_order_are_allowed(self, http: FakeHttp) -> None:
        http.queue(self._answer())

        response = run_action(
            "create_fulfillment",
            {
                "fulfillment_orders": [
                    {
                        "fulfillment_order_id": FULFILLMENT_ORDER_A,
                        "line_items": [
                            {
                                "fulfillment_order_line_item_id": FULFILLMENT_ORDER_LINE_A,
                                "quantity": 1,
                            },
                            {
                                "fulfillment_order_line_item_id": FULFILLMENT_ORDER_LINE_B,
                                "quantity": 3,
                            },
                        ],
                    }
                ]
            },
            http,
        )

        assert response["ok"] is True

    def test_tracking_is_optional_and_bounded(self, http: FakeHttp) -> None:
        http.queue(self._answer())

        run_action(
            "create_fulfillment",
            self._request(
                tracking={
                    "company": "DHL",
                    "numbers": ["TRK1"],
                    "urls": ["https://track.test/1"],
                }
            ),
            http,
        )

        assert http.variables()["fulfillment"]["trackingInfo"] == {
            "company": "DHL",
            "numbers": ["TRK1"],
            "urls": ["https://track.test/1"],
        }

    @pytest.mark.parametrize(
        "url", ["http://track.test/1", "ftp://track.test", "javascript:alert(1)", "track.test"]
    )
    def test_a_tracking_url_that_is_not_https_is_refused(self, url: str, http: FakeHttp) -> None:
        response = run_action("create_fulfillment", self._request(tracking={"urls": [url]}), http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_no_preflight_request_is_made(self, http: FakeHttp) -> None:
        """Shopify checks that the orders share an order and a location."""
        http.queue(self._answer())

        run_action("create_fulfillment", self._request(), http)

        assert len(http.requests) == 1


class TestUpdateFulfillmentTracking:
    def _answer(self, identifier: str = FULFILLMENT_A):
        return graphql_response(
            {
                "fulfillmentTrackingInfoUpdate": {
                    "fulfillment": fulfillment_node(identifier),
                    "userErrors": [],
                }
            }
        )

    def test_the_customer_is_never_notified(self, http: FakeHttp) -> None:
        http.queue(self._answer())

        run_action(
            "update_fulfillment_tracking",
            {"fulfillment_id": FULFILLMENT_A, "tracking": {"numbers": ["TRK2"]}},
            http,
        )

        assert documents.FULFILLMENT_NOTIFY_CUSTOMER in documents.UPDATE_FULFILLMENT_TRACKING
        assert "notifyCustomer" not in http.variables()

    def test_only_the_documented_tracking_fields_are_sent(self, http: FakeHttp) -> None:
        http.queue(self._answer())

        run_action(
            "update_fulfillment_tracking",
            {"fulfillment_id": FULFILLMENT_A, "tracking": {"company": "DHL"}},
            http,
        )

        assert http.variables()["trackingInfoInput"] == {"company": "DHL"}

    @pytest.mark.parametrize("tracking", [{}, {"numbers": []}, {"urls": []}])
    def test_clearing_tracking_is_refused(self, tracking: dict, http: FakeHttp) -> None:
        """This operation replaces tracking; it does not offer to remove it."""
        response = run_action(
            "update_fulfillment_tracking",
            {"fulfillment_id": FULFILLMENT_A, "tracking": tracking},
            http,
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_tracking_is_required(self, http: FakeHttp) -> None:
        response = run_action(
            "update_fulfillment_tracking", {"fulfillment_id": FULFILLMENT_A}, http
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD

    @pytest.mark.parametrize("operation_id", ["create_fulfillment", "update_fulfillment_tracking"])
    @pytest.mark.parametrize(
        "tracking",
        [
            {"urls": ["https://track.test/1"]},
            {"company": "DHL", "urls": ["https://track.test/1"]},
            {"numbers": ["TRK1", "TRK2"], "urls": ["https://track.test/1"]},
            {"numbers": ["TRK1"], "urls": ["https://track.test/1", "https://track.test/2"]},
        ],
    )
    def test_unpaired_tracking_urls_are_refused_before_http(
        self, operation_id: str, tracking: dict, http: FakeHttp
    ) -> None:
        if operation_id == "create_fulfillment":
            payload = TestCreateFulfillment()._request(tracking=tracking)
        else:
            payload = {"fulfillment_id": FULFILLMENT_A, "tracking": tracking}

        response = run_action(operation_id, payload, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_multiple_tracking_pairs_keep_their_order(self, http: FakeHttp) -> None:
        http.queue(self._answer())
        tracking = {
            "numbers": ["TRK2", "TRK1"],
            "urls": ["https://track.test/2", "https://track.test/1"],
        }

        response = run_action(
            "update_fulfillment_tracking",
            {"fulfillment_id": FULFILLMENT_A, "tracking": tracking},
            http,
        )

        assert response["ok"] is True
        assert http.variables()["trackingInfoInput"] == tracking

    def test_a_confirmation_for_another_fulfillment_is_not_success(self, http: FakeHttp) -> None:
        http.queue(self._answer("gid://shopify/Fulfillment/9999"))

        response = run_action(
            "update_fulfillment_tracking",
            {"fulfillment_id": FULFILLMENT_A, "tracking": {"numbers": ["TRK2"]}},
            http,
        )

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN
        assert response["definitely_no_external_effect"] is False
