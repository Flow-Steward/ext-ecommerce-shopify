"""What each reading operation sends, and what it makes of the answer."""

from __future__ import annotations

import json

import pytest
from conftest import (
    ITEM_A,
    ITEM_B,
    LOCATION_A,
    LOCATION_B,
    SHOP_DOMAIN,
    FakeHttp,
    connection_payload,
    graphql_response,
    inventory_item_node,
    inventory_level,
)

from runtime import documents, errors
from runtime.catalog import DEFAULT_PAGE_SIZE, OPERATIONS, OPERATIONS_BY_ID
from runtime.operations import handle_runtime


def run(operation_id: str, operation_input: dict, http: FakeHttp, **kwargs) -> dict:
    from runtime.transport import ShopifyGraphQLTransport

    return handle_runtime(
        connection_payload(operation_id, operation_input, **kwargs),
        transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
    )


class TestTestConnection:
    def _answer(
        self,
        *,
        domain: str = SHOP_DOMAIN,
        scopes: list[str] | None = None,
    ):
        return graphql_response(
            {
                "shop": {
                    "id": "gid://shopify/Shop/42",
                    "name": "Flow Steward Test",
                    "myshopifyDomain": domain,
                },
                "currentAppInstallation": {
                    "accessScopes": [
                        {"handle": handle}
                        for handle in (
                            scopes if scopes is not None else ["write_inventory", "read_products"]
                        )
                    ]
                },
            }
        )

    def test_it_reports_the_store_identity_the_version_and_the_scopes(self, http: FakeHttp) -> None:
        http.queue(self._answer())

        response = run("test_connection", {}, http)

        assert response["ok"] is True
        result = response["result"]
        assert result["shop_id"] == "gid://shopify/Shop/42"
        assert result["shop_name"] == "Flow Steward Test"
        assert result["myshopify_domain"] == SHOP_DOMAIN
        assert result["api_version"] == documents.API_VERSION
        assert result["granted_scopes"] == ["write_inventory", "read_products"]

    def test_it_separates_readable_capability_ids_from_the_scope_matrix(
        self, http: FakeHttp
    ) -> None:
        http.queue(self._answer(scopes=[]))

        result = run("test_connection", {}, http)["result"]

        assert result["capabilities"] == ["get_shop"]
        assert result["capability_scope_matrix"]["get_shop"] == {
            "scope_eligible": True,
            "required_oauth_scopes": [],
            "missing_required_oauth_scopes": [],
        }
        assert result["capability_scope_matrix"]["set_inventory_quantities"] == {
            "scope_eligible": False,
            "required_oauth_scopes": ["write_inventory"],
            "missing_required_oauth_scopes": ["write_inventory"],
        }
        assert "operation_id" not in result["capability_scope_matrix"]["get_shop"]

    def test_it_no_longer_publishes_a_single_global_required_scope(self) -> None:
        """The connection is not one scope wide any more, so nothing claims it is."""
        row = OPERATIONS_BY_ID["test_connection"]

        assert "required_scopes" not in row.result_fields
        assert "capabilities" in row.result_fields
        assert "capability_scope_matrix" in row.result_fields

    def test_it_sends_the_fixed_document_with_no_variables(self, http: FakeHttp) -> None:
        http.queue(self._answer())

        run("test_connection", {}, http)

        assert http.document() == documents.TEST_CONNECTION
        assert http.variables() == {}

    def test_a_token_that_belongs_to_another_store_is_refused(self, http: FakeHttp) -> None:
        http.queue(self._answer(domain="someone-else.myshopify.com"))

        response = run("test_connection", {}, http)

        assert response["error_code"] == errors.SHOP_DOMAIN_MISMATCH

    def test_the_returned_domain_is_compared_case_insensitively(self, http: FakeHttp) -> None:
        http.queue(self._answer(domain=SHOP_DOMAIN.upper()))

        response = run("test_connection", {}, http)

        assert response["ok"] is True

    def test_a_stale_partial_grant_reports_exact_missing_write_scopes(self, http: FakeHttp) -> None:
        """Diagnostics use the same write-scope vocabulary as OAuth setup."""
        http.queue(self._answer(scopes=["write_products"]))

        response = run("test_connection", {}, http)

        assert response["ok"] is True
        rows = response["result"]["capability_scope_matrix"]
        assert rows["set_inventory_quantities"]["scope_eligible"] is False
        assert rows["set_inventory_quantities"]["missing_required_oauth_scopes"] == [
            "write_inventory"
        ]
        assert rows["list_inventory_items"]["scope_eligible"] is False
        assert rows["list_products"]["scope_eligible"] is True

    def test_a_token_with_no_business_scopes_at_all_still_connects(self, http: FakeHttp) -> None:
        http.queue(self._answer(scopes=[]))

        response = run("test_connection", {}, http)

        assert response["ok"] is True
        rows = response["result"]["capability_scope_matrix"]
        assert len(rows) == 31
        assert list(rows) == [
            operation.operation_id
            for operation in OPERATIONS
            if operation.operation_id not in {"validate_connection_settings", "test_connection"}
        ]
        assert response["result"]["capabilities"] == ["get_shop"]

    def test_inventory_write_scope_does_not_cover_location_details(self, http: FakeHttp) -> None:
        http.queue(self._answer(scopes=["write_inventory"]))

        response = run("test_connection", {}, http)

        rows = response["result"]["capability_scope_matrix"]
        assert rows["list_locations"]["scope_eligible"] is False
        assert rows["list_locations"]["missing_required_oauth_scopes"] == ["read_locations"]
        assert rows["list_inventory_items"]["scope_eligible"] is True
        assert rows["list_products"]["scope_eligible"] is False

    def test_old_seven_scope_grant_is_not_reported_as_full_coverage(self, http: FakeHttp) -> None:
        http.queue(
            self._answer(
                scopes=[
                    "write_inventory",
                    "write_products",
                    "write_files",
                    "write_orders",
                    "write_assigned_fulfillment_orders",
                    "write_merchant_managed_fulfillment_orders",
                    "write_third_party_fulfillment_orders",
                ]
            )
        )

        response = run("test_connection", {}, http)

        result = response["result"]
        rows = result["capability_scope_matrix"]
        assert result["capability_summary"] == (
            "30 of 31 operations are covered; not covered: list_locations"
        )
        assert rows["list_locations"]["scope_eligible"] is False
        assert rows["list_locations"]["missing_required_oauth_scopes"] == ["read_locations"]

    def test_a_fulfillment_source_needs_both_of_its_groups(self, http: FakeHttp) -> None:
        """An order scope alone is not enough to read fulfillment orders."""
        http.queue(self._answer(scopes=["write_orders"]))

        response = run("test_connection", {}, http)

        rows = response["result"]["capability_scope_matrix"]
        assert rows["list_orders"]["scope_eligible"] is True
        assert rows["list_order_fulfillment_orders"]["scope_eligible"] is False
        assert rows["list_order_fulfillment_orders"]["missing_required_oauth_scopes"] == [
            "write_assigned_fulfillment_orders",
            "write_merchant_managed_fulfillment_orders",
            "write_third_party_fulfillment_orders",
        ]

    def test_fulfillment_mutations_publish_the_full_supported_family_set(
        self, http: FakeHttp
    ) -> None:
        """The operation supports every ownership family under one all-of contract."""
        http.queue(self._answer(scopes=["write_third_party_fulfillment_orders"]))

        response = run("test_connection", {}, http)

        rows = response["result"]["capability_scope_matrix"]
        assert rows["create_fulfillment"]["scope_eligible"] is False
        assert rows["update_fulfillment_tracking"]["scope_eligible"] is False

    def test_media_file_updates_use_one_canonical_documented_scope(self, http: FakeHttp) -> None:
        http.queue(self._answer(scopes=["write_themes"]))

        response = run("test_connection", {}, http)

        rows = response["result"]["capability_scope_matrix"]
        assert rows["update_product_media"]["scope_eligible"] is False
        assert rows["update_product_media"]["missing_required_oauth_scopes"] == ["write_files"]

    def test_product_only_grant_keeps_create_product_eligible(self, http: FakeHttp) -> None:
        """InventoryItem is readable with read_products or read_inventory."""
        http.queue(self._answer(scopes=["write_products"]))

        response = run("test_connection", {}, http)

        row = response["result"]["capability_scope_matrix"]["create_product"]
        assert set(row) == {
            "scope_eligible",
            "required_oauth_scopes",
            "missing_required_oauth_scopes",
        }
        assert row["required_oauth_scopes"] == ["write_products"]
        assert row["scope_eligible"] is True
        assert row["missing_required_oauth_scopes"] == []

    def test_no_diagnostic_ever_carries_the_token(self, http: FakeHttp) -> None:
        from conftest import ACCESS_TOKEN

        http.queue(self._answer(scopes=[]))

        response = run("test_connection", {}, http)

        assert ACCESS_TOKEN not in json.dumps(response)


class TestGetShop:
    def test_it_returns_the_fixed_selection_and_nothing_else(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "shop": {
                        "id": "gid://shopify/Shop/42",
                        "name": "Flow Steward Test",
                        "myshopifyDomain": SHOP_DOMAIN,
                        "currencyCode": "EUR",
                        "ianaTimezone": "Europe/Amsterdam",
                    }
                }
            )
        )

        response = run("get_shop", {}, http)

        shop = response["result"]["shop"]
        assert {key: shop[key] for key in (
            "id", "name", "myshopify_domain", "currency_code", "iana_timezone"
        )} == {
            "id": "gid://shopify/Shop/42",
            "name": "Flow Steward Test",
            "myshopify_domain": SHOP_DOMAIN,
            "currency_code": "EUR",
            "iana_timezone": "Europe/Amsterdam",
        }  # fmt: skip
        assert shop["weight_unit"] is None

    def test_the_document_asks_for_nothing_personal(self) -> None:
        """No owner email or name, no billing address."""
        selected = set(documents.GET_SHOP.split())
        for forbidden in ("email", "shopOwnerName", "billingAddress", "accountOwner"):
            assert forbidden not in selected

    def test_a_store_that_returns_nothing_still_yields_the_declared_shape(
        self, http: FakeHttp
    ) -> None:
        http.queue(graphql_response({"shop": None}))

        response = run("get_shop", {}, http)

        assert response["result"]["shop"] == {
            **dict.fromkeys(response["result"]["shop"]),
            "id": "",
            "enabled_presentment_currencies": [],
            "ships_to_countries": [],
            "name": None,
            "myshopify_domain": None,
            "currency_code": None,
            "iana_timezone": None,
        }


class TestListLocations:
    def _page(self, *, has_next: bool = False, cursor: str | None = None):
        return graphql_response(
            {
                "locations": {
                    "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                    "nodes": [
                        {
                            "id": LOCATION_A,
                            "name": "Warehouse",
                            "isActive": True,
                            "fulfillsOnlineOrders": True,
                            "shipsInventory": True,
                        }
                    ],
                }
            }
        )

    def test_it_defaults_to_fifty_active_locations(self, http: FakeHttp) -> None:
        http.queue(self._page())

        response = run("list_locations", {}, http)

        assert http.variables() == {
            "first": DEFAULT_PAGE_SIZE,
            "after": None,
            "includeInactive": False,
            "includeLegacy": False,
            "query": None,
            "sortKey": "NAME",
            "reverse": False,
        }
        location = response["result"]["locations"][0]
        assert {key: location[key] for key in (
            "id", "name", "is_active", "fulfills_online_orders", "ships_inventory"
        )} == {
            "id": LOCATION_A,
            "name": "Warehouse",
            "is_active": True,
            "fulfills_online_orders": True,
            "ships_inventory": True,
        }  # fmt: skip

    def test_shopify_authorization_denial_is_still_reported(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                None,
                errors=[
                    {
                        "message": "Access denied for locations field.",
                        "extensions": {"code": "ACCESS_DENIED"},
                    }
                ],
            )
        )

        response = run("list_locations", {}, http)

        assert response["ok"] is False
        assert response["error_code"] == errors.AUTHORIZATION_FAILED

    def test_document_uses_only_fields_and_arguments_verified_in_2026_07(self) -> None:
        document = documents.LIST_LOCATIONS

        assert "includeInactive: $includeInactive" in document
        for field in ("id", "name", "isActive", "fulfillsOnlineOrders", "shipsInventory"):
            assert field in document

    def test_it_normalizes_the_cursor_information(self, http: FakeHttp) -> None:
        http.queue(self._page(has_next=True, cursor="eyJsYXN0X2lkIjoxfQ=="))

        response = run("list_locations", {"first": 250}, http)

        assert response["result"]["page_info"] == {
            "has_next_page": True,
            "end_cursor": "eyJsYXN0X2lkIjoxfQ==",
        }

    def test_it_does_not_auto_paginate(self, http: FakeHttp) -> None:
        http.queue(self._page(has_next=True, cursor="next-page"))

        run("list_locations", {}, http)

        assert len(http.requests) == 1

    def test_the_cursor_travels_as_a_variable(self, http: FakeHttp) -> None:
        http.queue(self._page())

        run("list_locations", {"after": "cursor-1", "include_inactive": True}, http)

        assert http.variables()["after"] == "cursor-1"
        assert http.variables()["includeInactive"] is True
        assert "cursor-1" not in http.document()

    @pytest.mark.parametrize("first", [0, -1, 251, 1000, 1.5, "50", True, None])
    def test_a_page_size_outside_the_published_range_is_refused(
        self, first: object, http: FakeHttp
    ) -> None:
        response = run("list_locations", {"first": first}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    @pytest.mark.parametrize("first", [1, 50, 250])
    def test_the_published_range_is_accepted(self, first: int, http: FakeHttp) -> None:
        http.queue(self._page())

        response = run("list_locations", {"first": first}, http)

        assert response["ok"] is True
        assert http.variables()["first"] == first


class TestListInventoryItems:
    def _page(self, nodes: list | None = None):
        return graphql_response(
            {
                "inventoryItems": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": nodes if nodes is not None else [inventory_item_node()],
                }
            }
        )

    def test_it_returns_the_bounded_item_model(self, http: FakeHttp) -> None:
        http.queue(self._page())

        response = run("list_inventory_items", {}, http)

        item = response["result"]["inventory_items"][0]
        assert {key: item[key] for key in (
            "id", "sku", "tracked", "requires_shipping", "updated_at"
        )} == {
            "id": ITEM_A,
            "sku": "SKU-1",
            "tracked": True,
            "requires_shipping": True,
            "updated_at": "2026-08-27T12:00:00Z",
        }  # fmt: skip
        assert item["unit_cost"] is None

    def test_without_a_sku_no_search_string_is_sent(self, http: FakeHttp) -> None:
        http.queue(self._page())

        run("list_inventory_items", {}, http)

        assert http.variables()["query"] is None

    def test_the_sku_becomes_a_quoted_search_variable(self, http: FakeHttp) -> None:
        http.queue(self._page())

        run("list_inventory_items", {"sku": "ABC-123"}, http)

        assert http.variables()["query"] == 'sku:"ABC-123"'

    @pytest.mark.parametrize(
        ("sku", "expected"),
        [
            ('quote" inside', 'sku:"quote\\" inside"'),
            ("back\\slash", 'sku:"back\\\\slash"'),
            ("has space", 'sku:"has space"'),
            ('" OR id:>0 OR sku:"', 'sku:"\\" OR id:>0 OR sku:\\""'),
        ],
    )
    def test_a_sku_can_never_become_search_syntax(
        self, sku: str, expected: str, http: FakeHttp
    ) -> None:
        http.queue(self._page())

        run("list_inventory_items", {"sku": sku}, http)

        assert http.variables()["query"] == expected
        assert sku not in http.document()

    def test_the_document_is_the_fixed_one(self, http: FakeHttp) -> None:
        http.queue(self._page())

        run("list_inventory_items", {"sku": "ABC"}, http)

        assert http.document() == documents.LIST_INVENTORY_ITEMS

    def test_a_node_that_is_not_a_mapping_is_dropped(self, http: FakeHttp) -> None:
        http.queue(self._page([None, "nonsense", inventory_item_node(ITEM_B, sku=None)]))

        response = run("list_inventory_items", {}, http)

        assert [item["id"] for item in response["result"]["inventory_items"]] == [ITEM_B]
        assert response["result"]["inventory_items"][0]["sku"] is None


class TestGetInventoryItem:
    def test_it_returns_the_same_bounded_item_model(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"inventoryItem": inventory_item_node()}))

        response = run("get_inventory_item", {"inventory_item_id": ITEM_A}, http)

        assert response["result"]["inventory_item"]["id"] == ITEM_A
        assert http.variables() == {"id": ITEM_A}

    def test_a_null_node_is_not_found(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"inventoryItem": None}))

        response = run("get_inventory_item", {"inventory_item_id": ITEM_A}, http)

        assert response["error_code"] == errors.NOT_FOUND

    def test_a_node_of_the_wrong_type_is_an_upstream_failure(self, http: FakeHttp) -> None:
        """A store answering about another record is wrong, not empty."""
        http.queue(
            graphql_response(
                {"inventoryItem": {"__typename": "Product", "id": "gid://shopify/Product/9"}}
            )
        )

        response = run("get_inventory_item", {"inventory_item_id": ITEM_A}, http)

        assert response["error_code"] == errors.UPSTREAM_FAILURE

    @pytest.mark.parametrize(
        "identifier",
        [
            LOCATION_A,
            "gid://shopify/Product/1001",
            "gid://other/InventoryItem/1001",
            "1001",
            "gid://shopify/InventoryItem/",
            "gid://shopify/InventoryItem/abc",
            "gid://shopify/InventoryItem/1001?x=1",
            "",
            None,
            42,
        ],
    )
    def test_an_id_that_is_not_an_inventory_item_gid_is_refused(
        self, identifier: object, http: FakeHttp
    ) -> None:
        response = run("get_inventory_item", {"inventory_item_id": identifier}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []


class TestGetInventoryLevelsBatch:
    def _base(self, ids: list[str], **extra) -> dict:
        return {"location_id": LOCATION_A, "inventory_item_ids": ids, **extra}

    def test_each_row_carries_the_stock_of_the_item_it_names(self, http: FakeHttp) -> None:
        """Rows are keyed by the id Shopify reports, never by list position.

        Attributing one product's stock to another is the worst thing this
        operation could do: a sync acting on it would set the wrong quantities
        with nothing looking wrong. So the answer is matched by id, and a
        reordered response still lines up.
        """
        http.queue(
            graphql_response(
                {
                    "nodes": [
                        {
                            **inventory_item_node(ITEM_B, sku="SKU-B"),
                            "inventoryLevel": inventory_level(available=99, on_hand=99),
                        },
                        {
                            **inventory_item_node(ITEM_A, sku="SKU-A"),
                            "inventoryLevel": inventory_level(available=4, on_hand=6),
                        },
                    ]
                }
            )
        )

        response = run("get_inventory_levels_batch", self._base([ITEM_A, ITEM_B]), http)

        rows = {row["inventory_item_id"]: row for row in response["result"]["items"]}
        assert [row["inventory_item_id"] for row in response["result"]["items"]] == [
            ITEM_A,
            ITEM_B,
        ]
        assert rows[ITEM_A]["sku"] == "SKU-A"
        assert rows[ITEM_A]["level"]["available"] == 4
        assert rows[ITEM_B]["sku"] == "SKU-B"
        assert rows[ITEM_B]["level"]["available"] == 99

    def test_a_node_for_an_item_that_was_not_asked_for_is_ignored(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {"nodes": [{**inventory_item_node(ITEM_B), "inventoryLevel": inventory_level()}]}
            )
        )

        response = run("get_inventory_levels_batch", self._base([ITEM_A]), http)

        assert response["result"]["items"] == [
            {
                "inventory_item_id": ITEM_A,
                "found": False,
                "sku": None,
                "tracked": None,
                "level": None,
            }
        ]

    def test_one_item_is_a_valid_batch(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {"nodes": [{**inventory_item_node(), "inventoryLevel": inventory_level()}]}
            )
        )

        response = run("get_inventory_levels_batch", self._base([ITEM_A]), http)

        assert response["result"]["location_id"] == LOCATION_A
        assert response["result"]["items"] == [
            {
                "inventory_item_id": ITEM_A,
                "found": True,
                "sku": "SKU-1",
                "tracked": True,
                "level": {
                    "id": "gid://shopify/InventoryLevel/9001?inventory_item_id=1001",
                    "location_id": LOCATION_A,
                    "is_active": True,
                    "level_is_active": None,
                    "can_deactivate": None,
                    "deactivation_alert": None,
                    "created_at": None,
                    "updated_at": None,
                    "available": 4,
                    "on_hand": 6,
                    "committed": None,
                    "incoming": None,
                    "reserved": None,
                    "damaged": None,
                    "safety_stock": None,
                    "quality_control": None,
                },
            }
        ]

    def test_two_hundred_and_fifty_items_are_a_valid_batch(self, http: FakeHttp) -> None:
        ids = [f"gid://shopify/InventoryItem/{index}" for index in range(1, 251)]
        http.queue(
            graphql_response(
                {
                    "nodes": [
                        {**inventory_item_node(identifier), "inventoryLevel": inventory_level()}
                        for identifier in ids
                    ]
                }
            )
        )

        response = run("get_inventory_levels_batch", self._base(ids), http)

        assert response["ok"] is True
        assert len(response["result"]["items"]) == 250
        assert http.variables()["ids"] == ids

    def test_the_input_order_is_preserved(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "nodes": [
                        {**inventory_item_node(ITEM_B), "inventoryLevel": None},
                        {**inventory_item_node(ITEM_A), "inventoryLevel": inventory_level()},
                    ]
                }
            )
        )

        response = run("get_inventory_levels_batch", self._base([ITEM_B, ITEM_A]), http)

        assert [row["inventory_item_id"] for row in response["result"]["items"]] == [
            ITEM_B,
            ITEM_A,
        ]

    def test_a_missing_node_is_data_rather_than_a_failure(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {"nodes": [None, {**inventory_item_node(ITEM_B), "inventoryLevel": None}]}
            )
        )

        response = run("get_inventory_levels_batch", self._base([ITEM_A, ITEM_B]), http)

        assert response["ok"] is True
        assert response["result"]["items"][0] == {
            "inventory_item_id": ITEM_A,
            "found": False,
            "sku": None,
            "tracked": None,
            "level": None,
        }

    def test_an_item_not_stocked_at_that_location_has_no_level(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"nodes": [{**inventory_item_node(), "inventoryLevel": None}]}))

        response = run("get_inventory_levels_batch", self._base([ITEM_A]), http)

        assert response["ok"] is True
        assert response["result"]["items"][0]["found"] is True
        assert response["result"]["items"][0]["level"] is None

    def test_a_short_answer_still_answers_for_every_requested_id(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"nodes": []}))

        response = run("get_inventory_levels_batch", self._base([ITEM_A, ITEM_B]), http)

        assert [row["found"] for row in response["result"]["items"]] == [False, False]

    def test_a_deactivated_location_is_hidden_by_default(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "nodes": [
                        {
                            **inventory_item_node(),
                            "inventoryLevel": inventory_level(is_active=False),
                        }
                    ]
                }
            )
        )

        response = run("get_inventory_levels_batch", self._base([ITEM_A]), http)

        assert response["result"]["items"][0]["level"] is None

    def test_a_deactivated_location_is_reported_when_asked_for(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "nodes": [
                        {
                            **inventory_item_node(),
                            "inventoryLevel": inventory_level(is_active=False),
                        }
                    ]
                }
            )
        )

        response = run(
            "get_inventory_levels_batch",
            self._base([ITEM_A], include_inactive=True),
            http,
        )

        assert response["result"]["items"][0]["level"]["is_active"] is False
        assert response["result"]["items"][0]["level"]["available"] == 4

    @pytest.mark.parametrize("include_inactive", [False, True])
    def test_the_flag_reaches_shopify_rather_than_only_filtering_the_answer(
        self, include_inactive: bool, http: FakeHttp
    ) -> None:
        """Shopify omits an inactive level unless the query asks for it.

        Filtering only the response would leave `include_inactive: true` looking
        supported while never returning the level it was meant to reveal, so
        this asserts the document and the variables actually sent — not a
        property of the mocked answer.
        """
        http.queue(graphql_response({"nodes": []}))

        run(
            "get_inventory_levels_batch",
            self._base([ITEM_A], include_inactive=include_inactive),
            http,
        )

        assert http.variables()["includeInactive"] is include_inactive
        assert http.document() == documents.GET_INVENTORY_LEVELS_BATCH

    def test_the_document_declares_and_passes_the_inactive_argument(self) -> None:
        document = documents.GET_INVENTORY_LEVELS_BATCH

        assert "$includeInactive: Boolean!" in document
        assert (
            "inventoryLevel(locationId: $locationId, includeInactive: $includeInactive)" in document
        )

    def test_the_default_is_still_to_leave_inactive_levels_out(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"nodes": []}))

        run("get_inventory_levels_batch", self._base([ITEM_A]), http)

        assert http.variables()["includeInactive"] is False

    def test_a_quantity_shopify_does_not_return_is_null_rather_than_zero(
        self, http: FakeHttp
    ) -> None:
        level = inventory_level()
        level["quantities"] = [{"name": "available", "quantity": 3}]
        http.queue(
            graphql_response({"nodes": [{**inventory_item_node(), "inventoryLevel": level}]})
        )

        response = run("get_inventory_levels_batch", self._base([ITEM_A]), http)

        assert response["result"]["items"][0]["level"]["available"] == 3
        assert response["result"]["items"][0]["level"]["on_hand"] is None

    def test_every_quantity_name_is_fixed_in_the_document(self) -> None:
        names = ", ".join(f'"{name}"' for name in documents.READ_QUANTITY_NAMES)
        assert f"quantities(names: [{names}])" in documents.GET_INVENTORY_LEVELS_BATCH

    @pytest.mark.parametrize(
        "ids",
        [
            [],
            [f"gid://shopify/InventoryItem/{index}" for index in range(251)],
            [ITEM_A, ITEM_A],
            [ITEM_A, LOCATION_A],
            [ITEM_A, None],
            "not-a-list",
        ],
    )
    def test_an_unusable_batch_is_refused_before_anything_is_sent(
        self, ids: object, http: FakeHttp
    ) -> None:
        response = run("get_inventory_levels_batch", self._base(ids), http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_a_location_id_of_the_wrong_type_is_refused(self, http: FakeHttp) -> None:
        response = run(
            "get_inventory_levels_batch",
            {"location_id": ITEM_A, "inventory_item_ids": [ITEM_A]},
            http,
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []


class TestUnknownInputsAreRefused:
    @pytest.mark.parametrize(
        ("operation_id", "operation_input"),
        [
            ("get_shop", {"fields": "id"}),
            ("list_locations", {"query": "name:Warehouse"}),
            ("list_inventory_items", {"query": "sku:X"}),
            ("list_inventory_items", {"sort_key": "SKU"}),
            ("test_connection", {"api_version": "2024-01"}),
            (
                "get_inventory_levels_batch",
                {"location_id": LOCATION_A, "inventory_item_ids": [ITEM_A], "names": ["damaged"]},
            ),
        ],
    )
    def test_a_field_the_operation_does_not_publish_is_refused(
        self, operation_id: str, operation_input: dict, http: FakeHttp
    ) -> None:
        response = run(operation_id, operation_input, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_a_second_location_cannot_be_smuggled_into_a_batch(self, http: FakeHttp) -> None:
        response = run(
            "get_inventory_levels_batch",
            {
                "location_id": LOCATION_A,
                "location_ids": [LOCATION_A, LOCATION_B],
                "inventory_item_ids": [ITEM_A],
            },
            http,
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD
