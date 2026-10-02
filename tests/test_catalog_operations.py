"""What the catalog operations send, refuse, and make of Shopify's answer."""

from __future__ import annotations

import pytest
from conftest import (
    CATEGORY_A,
    LOCATION_A,
    MEDIA_A,
    PRODUCT_A,
    PRODUCT_B,
    VARIANT_A,
    VARIANT_B,
    FakeHttp,
    adjustment_group_response,
    connection,
    graphql_response,
    metafield_node,
    product_node,
    run_action,
    run_operation,
    variant_node,
)
from runtime import documents, errors
from runtime.catalog import DEFAULT_PAGE_SIZE


class TestCatalogSources:
    def test_products_come_back_in_the_published_shape(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"products": connection([product_node()])}))

        response = run_operation("list_products", {}, http)

        assert response["ok"] is True
        product = response["result"]["products"][0]
        assert product["id"] == PRODUCT_A
        assert product["category_id"] == CATEGORY_A
        assert product["seo"] == {"title": "Boots", "description": "Good boots"}
        assert product["options"] == [
            {"id": "gid://shopify/ProductOption/1", "name": "Size", "position": 1}
        ]

    def test_a_page_defaults_to_fifty_and_sends_no_cursor(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"products": connection([])}))

        run_operation("list_products", {}, http)

        assert http.variables() == {"first": DEFAULT_PAGE_SIZE, "after": None}

    @pytest.mark.parametrize(
        "operation_id",
        ["list_products", "list_product_variants", "list_orders"],
    )
    @pytest.mark.parametrize("first", [0, -1, 251, 1.5, "50", True, None])
    def test_a_page_size_outside_the_range_never_reaches_shopify(
        self, operation_id: str, first: object, http: FakeHttp
    ) -> None:
        response = run_operation(operation_id, {"first": first}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_one_page_is_one_request(self, http: FakeHttp) -> None:
        """A source never follows the cursor it just returned."""
        http.queue(
            graphql_response({"products": connection([product_node()], has_next=True, cursor="c1")})
        )

        response = run_operation("list_products", {"first": 1}, http)

        assert len(http.requests) == 1
        assert response["result"]["page_info"] == {"has_next_page": True, "end_cursor": "c1"}

    def test_a_variant_carries_its_product_and_inventory_identity(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"productVariant": variant_node()}))

        response = run_operation("get_product_variant", {"product_variant_id": VARIANT_A}, http)

        variant = response["result"]["product_variant"]
        assert variant["product_id"] == PRODUCT_A
        assert variant["price"] == "19.99"
        assert variant["inventory_item"]["sku"] == "SKU-1"

    def test_a_missing_product_is_not_found(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"product": None}))

        response = run_operation("get_product", {"product_id": PRODUCT_A}, http)

        assert response["error_code"] == errors.NOT_FOUND

    @pytest.mark.parametrize(
        ("operation_id", "field", "wrong"),
        [
            ("get_product", "product_id", VARIANT_A),
            ("get_product_variant", "product_variant_id", PRODUCT_A),
            ("list_product_media", "product_id", "gid://shopify/Order/1"),
        ],
    )
    def test_an_id_of_the_wrong_type_never_reaches_shopify(
        self, operation_id: str, field: str, wrong: str, http: FakeHttp
    ) -> None:
        response = run_operation(operation_id, {field: wrong}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []


class TestCatalogMetafieldsAreOwnerChecked:
    def test_the_owner_type_must_match_the_id(self, http: FakeHttp) -> None:
        """A product id pasted where a variant belongs is refused, not followed.

        Asking for the owner type explicitly rather than inferring it from the
        id is what makes the mismatch visible instead of quietly reading the
        wrong record's metafields.
        """
        response = run_operation(
            "list_catalog_metafields",
            {"owner_type": "product_variant", "owner_id": PRODUCT_A},
            http,
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_a_matching_owner_is_read_and_carries_its_own_id(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "node": {
                        "__typename": "Product",
                        "id": PRODUCT_A,
                        "metafields": connection([metafield_node()]),
                    }
                }
            )
        )

        response = run_operation(
            "list_catalog_metafields", {"owner_type": "product", "owner_id": PRODUCT_A}, http
        )

        assert response["result"]["owner_id"] == PRODUCT_A
        assert response["result"]["metafields"][0]["owner_id"] == PRODUCT_A

    def test_a_node_of_another_type_is_an_upstream_failure(self, http: FakeHttp) -> None:
        """Not `not_found`: the product may well exist, the answer is wrong."""
        http.queue(
            graphql_response({"node": {"__typename": "Order", "id": "gid://shopify/Order/1"}})
        )

        response = run_operation(
            "list_catalog_metafields", {"owner_type": "product", "owner_id": PRODUCT_A}, http
        )

        assert response["error_code"] == errors.UPSTREAM_FAILURE

    def test_an_absent_owner_is_still_not_found(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"node": None}))

        response = run_operation(
            "list_catalog_metafields", {"owner_type": "product", "owner_id": PRODUCT_A}, http
        )

        assert response["error_code"] == errors.NOT_FOUND

    @pytest.mark.parametrize("owner_type", ["order", "shop", "", "PRODUCT"])
    def test_only_the_two_documented_owner_types_are_accepted(
        self, owner_type: str, http: FakeHttp
    ) -> None:
        response = run_operation(
            "list_catalog_metafields", {"owner_type": owner_type, "owner_id": PRODUCT_A}, http
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD


class TestCreateProduct:
    def _answer(self, **overrides):
        overrides.setdefault("variants", connection([variant_node()]))
        return graphql_response(
            {"productCreate": {"product": product_node(**overrides), "userErrors": []}}
        )

    def test_initial_variant_array_is_ready_for_followup_price_sku_and_stock_steps(
        self, http: FakeHttp
    ) -> None:
        http.queue(
            self._answer(
                variants=connection(
                    [
                        variant_node(
                            selectedOptions=[
                                {"name": "Size", "value": "41"},
                                {"name": "Color", "value": "Black"},
                            ]
                        )
                    ]
                )
            )
        )

        response = run_action(
            "create_product",
            {
                "title": "Boots",
                "handle": "boots",
                "options": [
                    {"name": "Size", "values": ["41", "42"]},
                    {"name": "Color", "values": ["Black", "Brown"]},
                ],
            },
            http,
        )

        assert response["ok"] is True, response
        assert len(response["result"]["product_variants"]) == 1
        initial_variant = response["result"]["product_variants"][0]
        assert initial_variant["id"] == VARIANT_A
        assert initial_variant["product_id"] == PRODUCT_A
        assert initial_variant["selected_options"] == [
            {"name": "Size", "value": "41"},
            {"name": "Color", "value": "Black"},
        ]
        assert initial_variant["inventory_item"] == {
            "id": "gid://shopify/InventoryItem/1001",
            "sku": "SKU-1",
            "tracked": True,
            "requires_shipping": True,
        }
        assert http.variables()["product"]["productOptions"] == [
            {"name": "Size", "values": [{"name": "41"}, {"name": "42"}]},
            {"name": "Color", "values": [{"name": "Black"}, {"name": "Brown"}]},
        ]
        document = http.document()
        assert "variants(first: 1)" in document
        assert "inventoryItem { id sku tracked requiresShipping }" in document

    def test_created_variant_array_composes_with_update_and_stock_actions(
        self, http: FakeHttp
    ) -> None:
        http.queue(self._answer())
        created = run_action(
            "create_product",
            {"title": "Boots", "handle": "boots"},
            http,
        )

        created_variants = created["result"]["product_variants"]
        update_input = [
            {
                "variant_id": variant["id"],
                "price": "21.50",
                "inventory_item": {"sku": "NEW-SKU", "tracked": True},
            }
            for variant in created_variants
        ]
        http.queue(
            graphql_response(
                {
                    "productVariantsBulkUpdate": {
                        "productVariants": [
                            variant_node(
                                price="21.50",
                                inventoryItem={
                                    "id": "gid://shopify/InventoryItem/1001",
                                    "sku": "NEW-SKU",
                                    "tracked": True,
                                    "requiresShipping": True,
                                },
                            )
                        ],
                        "userErrors": [],
                    }
                }
            )
        )
        updated = run_action(
            "update_product_variants_batch",
            {"product_id": PRODUCT_A, "variants": update_input},
            http,
        )

        quantities = [
            {
                "inventory_item_id": variant["inventory_item"]["id"],
                "location_id": LOCATION_A,
                "quantity": 7,
                "change_from_quantity": None,
            }
            for variant in updated["result"]["product_variants"]
        ]
        http.queue(adjustment_group_response())
        stocked = run_action("set_inventory_quantities", {"quantities": quantities}, http)

        assert created["ok"] is True
        assert updated["ok"] is True
        assert stocked["ok"] is True
        assert http.variables(1) == {
            "productId": PRODUCT_A,
            "variants": [
                {
                    "id": VARIANT_A,
                    "price": "21.50",
                    "inventoryItem": {"sku": "NEW-SKU", "tracked": True},
                }
            ],
        }
        assert http.variables(2)["input"]["quantities"][0]["inventoryItemId"] == (
            "gid://shopify/InventoryItem/1001"
        )

    @pytest.mark.parametrize(
        "variants",
        [
            connection([]),
            connection([variant_node(inventoryItem={"sku": "SKU-1", "tracked": True})]),
        ],
    )
    def test_an_unusable_initial_variant_is_an_unknown_create_outcome(
        self, variants: dict, http: FakeHttp
    ) -> None:
        http.queue(self._answer(variants=variants))

        response = run_action("create_product", {"title": "Boots", "handle": "boots"}, http)

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN
        assert response["external_effect_status"] == "timeout_unknown"
        assert response["definitely_no_external_effect"] is False

    def test_a_created_product_is_always_a_draft(self, http: FakeHttp) -> None:
        """Publishing is a merchandising decision, never an import side effect."""
        http.queue(self._answer())

        run_action("create_product", {"title": "Boots", "handle": "boots"}, http)

        assert http.variables()["product"]["status"] == documents.CREATE_PRODUCT_STATUS == "DRAFT"

    def test_nothing_but_the_declared_fields_is_sent(self, http: FakeHttp) -> None:
        http.queue(self._answer())

        run_action("create_product", {"title": "Boots", "handle": "boots"}, http)

        assert set(http.variables()) == {"product"}
        assert set(http.variables()["product"]) == {"title", "handle", "status"}

    def test_media_metafields_collections_and_publications_are_unreachable(
        self, http: FakeHttp
    ) -> None:
        http.queue(self._answer())

        run_action(
            "create_product",
            {
                "title": "Boots",
                "handle": "boots",
                "description_html": "<p>x</p>",
                "vendor": "Acme",
                "product_type": "Footwear",
                "tags": ["new"],
                "category_id": CATEGORY_A,
                "seo_title": "Boots",
                "seo_description": "Good boots",
                "options": [{"name": "Size", "values": ["41", "42"]}],
            },
            http,
        )

        product = http.variables()["product"]
        assert set(product) == {
            "title",
            "handle",
            "status",
            "descriptionHtml",
            "vendor",
            "productType",
            "tags",
            "category",
            "seo",
            "productOptions",
        }
        for forbidden in (
            "media",
            "metafields",
            "collectionsToJoin",
            "publications",
            "giftCard",
            "templateSuffix",
            "sellingPlanGroups",
        ):
            assert forbidden not in product

    @pytest.mark.parametrize(
        "operation_input",
        [
            {"handle": "boots"},
            {"title": "Boots"},
            {"title": "", "handle": "boots"},
            {"title": "Boots", "handle": ""},
            {"title": "Boots", "handle": "boots", "status": "ACTIVE"},
            {"title": "Boots", "handle": "boots", "options": [{"name": "Size", "values": []}]},
            {"title": "Boots", "handle": "boots", "category_id": PRODUCT_A},
        ],
    )
    def test_an_unusable_request_never_reaches_shopify(
        self, operation_input: dict, http: FakeHttp
    ) -> None:
        response = run_action("create_product", operation_input, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_more_than_three_options_are_refused(self, http: FakeHttp) -> None:
        response = run_action(
            "create_product",
            {
                "title": "Boots",
                "handle": "boots",
                "options": [{"name": str(index), "values": ["x"]} for index in range(4)],
            },
            http,
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD

    def test_shopify_decides_whether_the_handle_is_free(self, http: FakeHttp) -> None:
        """No lookup first: Shopify's own refusal is the answer, in one request."""
        http.queue(
            graphql_response(
                {
                    "productCreate": {
                        "product": None,
                        "userErrors": [{"field": ["handle"], "message": "taken"}],
                    }
                }
            )
        )

        response = run_action("create_product", {"title": "B", "handle": "boots"}, http)

        assert response["error_code"] == errors.UPSTREAM_VALIDATION_FAILED
        assert "handle" in response["error"]
        assert "taken" not in response["error"]
        assert len(http.requests) == 1


class TestUpdateProduct:
    def _answer(self):
        return graphql_response({"productUpdate": {"product": product_node(), "userErrors": []}})

    def test_an_omitted_field_is_not_sent(self, http: FakeHttp) -> None:
        http.queue(self._answer())

        run_action("update_product", {"product_id": PRODUCT_A, "vendor": "Acme"}, http)

        assert set(http.variables()["product"]) == {"id", "vendor"}

    def test_changing_the_handle_always_asks_for_a_redirect(self, http: FakeHttp) -> None:
        """A metadata edit must not be able to break a live URL silently."""
        http.queue(self._answer())

        run_action("update_product", {"product_id": PRODUCT_A, "handle": "new"}, http)

        assert http.variables()["product"]["redirectNewHandle"] is True

    def test_changing_the_category_never_deletes_constrained_metafields(
        self, http: FakeHttp
    ) -> None:
        http.queue(self._answer())

        run_action("update_product", {"product_id": PRODUCT_A, "category_id": CATEGORY_A}, http)

        product = http.variables()["product"]
        assert product["deleteConflictingConstrainedMetafields"] is False

    def test_replace_tags_overwrites_the_whole_list(self, http: FakeHttp) -> None:
        http.queue(self._answer())

        run_action("update_product", {"product_id": PRODUCT_A, "replace_tags": ["a"]}, http)

        assert http.variables()["product"]["tags"] == ["a"]

    def test_an_empty_replace_tags_is_refused(self, http: FakeHttp) -> None:
        """Clearing every tag is more likely a mistake than an intention."""
        response = run_action("update_product", {"product_id": PRODUCT_A, "replace_tags": []}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_naming_a_product_without_a_change_is_refused(self, http: FakeHttp) -> None:
        response = run_action("update_product", {"product_id": PRODUCT_A}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    @pytest.mark.parametrize(
        "field", ["status", "published", "media", "metafields", "templateSuffix", "giftCard"]
    )
    def test_a_field_outside_the_whitelist_is_refused(self, field: str, http: FakeHttp) -> None:
        response = run_action("update_product", {"product_id": PRODUCT_A, field: "x"}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD

    def test_a_confirmation_for_another_product_is_not_success(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {"productUpdate": {"product": product_node(PRODUCT_B), "userErrors": []}}
            )
        )

        response = run_action("update_product", {"product_id": PRODUCT_A, "vendor": "A"}, http)

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN
        assert response["definitely_no_external_effect"] is False


class TestVariantBatches:
    def _create_answer(self, variants):
        return graphql_response(
            {"productVariantsBulkCreate": {"productVariants": variants, "userErrors": []}}
        )

    def _update_answer(self, variants):
        return graphql_response(
            {"productVariantsBulkUpdate": {"productVariants": variants, "userErrors": []}}
        )

    def test_create_preserves_the_standalone_variant(self) -> None:
        assert "strategy: PRESERVE_STANDALONE_VARIANT" in documents.CREATE_PRODUCT_VARIANTS_BATCH
        assert documents.VARIANTS_BULK_CREATE_STRATEGY == "PRESERVE_STANDALONE_VARIANT"

    def test_update_never_applies_a_partial_batch(self) -> None:
        assert documents.VARIANTS_BULK_UPDATE_PARTIAL in documents.UPDATE_PRODUCT_VARIANTS_BATCH

    def test_prices_travel_as_decimal_strings(self, http: FakeHttp) -> None:
        """Never as binary floats: 19.99 must not become 19.989999999999998."""
        http.queue(self._create_answer([variant_node()]))

        run_action(
            "create_product_variants_batch",
            {
                "product_id": PRODUCT_A,
                "variants": [
                    {
                        "option_values": [{"option_name": "Size", "value": "42"}],
                        "price": "19.99",
                        "inventory_item": {"cost": "9.50", "sku": "S-1"},
                    }
                ],
            },
            http,
        )

        entry = http.variables()["variants"][0]
        assert entry["price"] == "19.99"
        assert isinstance(entry["price"], str)
        assert entry["inventoryItem"]["cost"] == "9.50"

    @pytest.mark.parametrize("price", [19.99, "19,99", "abc", "", "1e5", None, True])
    def test_a_price_that_is_not_a_decimal_string_is_refused(
        self, price: object, http: FakeHttp
    ) -> None:
        response = run_action(
            "create_product_variants_batch",
            {
                "product_id": PRODUCT_A,
                "variants": [
                    {"option_values": [{"option_name": "Size", "value": "42"}], "price": price}
                ],
            },
            http,
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_quantities_and_media_cannot_be_smuggled_into_a_variant(self, http: FakeHttp) -> None:
        for field in ("quantities", "inventoryQuantities", "media", "metafields", "taxCode"):
            response = run_action(
                "create_product_variants_batch",
                {
                    "product_id": PRODUCT_A,
                    "variants": [
                        {
                            "option_values": [{"option_name": "Size", "value": "42"}],
                            field: "x",
                        }
                    ],
                },
                http,
            )
            assert response["error_code"] == errors.INVALID_PAYLOAD, field

    def test_an_update_entry_must_carry_an_actual_change(self, http: FakeHttp) -> None:
        response = run_action(
            "update_product_variants_batch",
            {"product_id": PRODUCT_A, "variants": [{"variant_id": VARIANT_A}]},
            http,
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_empty_inventory_item_is_not_an_actual_variant_change(self, http: FakeHttp) -> None:
        response = run_action(
            "update_product_variants_batch",
            {
                "product_id": PRODUCT_A,
                "variants": [{"variant_id": VARIANT_A, "inventory_item": {}}],
            },
            http,
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    @pytest.mark.parametrize("change", [{"tracked": False}, {"cost": "0.00"}, {"sku": "SKU-1"}])
    def test_inventory_item_values_are_actual_variant_changes(
        self, change: dict, http: FakeHttp
    ) -> None:
        http.queue(self._update_answer([variant_node(VARIANT_A)]))

        response = run_action(
            "update_product_variants_batch",
            {
                "product_id": PRODUCT_A,
                "variants": [{"variant_id": VARIANT_A, "inventory_item": change}],
            },
            http,
        )

        assert response["ok"] is True
        assert http.variables()["variants"] == [{"id": VARIANT_A, "inventoryItem": change}]

    def test_an_empty_inventory_item_does_not_discard_a_real_price_change(
        self, http: FakeHttp
    ) -> None:
        http.queue(self._update_answer([variant_node(VARIANT_A)]))

        response = run_action(
            "update_product_variants_batch",
            {
                "product_id": PRODUCT_A,
                "variants": [{"variant_id": VARIANT_A, "inventory_item": {}, "price": "1.00"}],
            },
            http,
        )

        assert response["ok"] is True
        assert http.variables()["variants"] == [{"id": VARIANT_A, "price": "1.00"}]

    def test_duplicate_variant_ids_are_refused_locally(self, http: FakeHttp) -> None:
        response = run_action(
            "update_product_variants_batch",
            {
                "product_id": PRODUCT_A,
                "variants": [
                    {"variant_id": VARIANT_A, "price": "1.00"},
                    {"variant_id": VARIANT_A, "price": "2.00"},
                ],
            },
            http,
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    @pytest.mark.parametrize("count", [1, 250])
    def test_the_batch_bounds_are_one_and_two_hundred_and_fifty(
        self, count: int, http: FakeHttp
    ) -> None:
        variants = [
            {"variant_id": f"gid://shopify/ProductVariant/{index}", "price": "1.00"}
            for index in range(1, count + 1)
        ]
        http.queue(
            self._update_answer(
                [
                    variant_node(f"gid://shopify/ProductVariant/{index}")
                    for index in range(1, count + 1)
                ]
            )
        )

        response = run_action(
            "update_product_variants_batch", {"product_id": PRODUCT_A, "variants": variants}, http
        )

        assert response["ok"] is True
        assert len(http.variables()["variants"]) == count

    @pytest.mark.parametrize("count", [0, 251])
    def test_a_batch_outside_the_bounds_is_refused(self, count: int, http: FakeHttp) -> None:
        variants = [
            {"variant_id": f"gid://shopify/ProductVariant/{index}", "price": "1.00"}
            for index in range(1, count + 1)
        ]

        response = run_action(
            "update_product_variants_batch", {"product_id": PRODUCT_A, "variants": variants}, http
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_updates_are_matched_by_returned_id_not_by_position(self, http: FakeHttp) -> None:
        """A reordered answer must still line up with the right request."""
        http.queue(self._update_answer([variant_node(VARIANT_B), variant_node(VARIANT_A)]))

        response = run_action(
            "update_product_variants_batch",
            {
                "product_id": PRODUCT_A,
                "variants": [
                    {"variant_id": VARIANT_A, "price": "1.00"},
                    {"variant_id": VARIANT_B, "price": "2.00"},
                ],
            },
            http,
        )

        assert [v["id"] for v in response["result"]["product_variants"]] == [VARIANT_A, VARIANT_B]

    @pytest.mark.parametrize(
        "returned",
        [
            [],
            [variant_node(VARIANT_A), variant_node(VARIANT_A)],
            [variant_node(VARIANT_A), variant_node("gid://shopify/ProductVariant/999")],
            [variant_node(PRODUCT_A)],
        ],
    )
    def test_an_answer_that_cannot_be_matched_is_an_unknown_outcome(
        self, returned: list, http: FakeHttp
    ) -> None:
        http.queue(self._update_answer(returned))

        response = run_action(
            "update_product_variants_batch",
            {
                "product_id": PRODUCT_A,
                "variants": [
                    {"variant_id": VARIANT_A, "price": "1.00"},
                    {"variant_id": VARIANT_B, "price": "2.00"},
                ],
            },
            http,
        )

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN
        assert response["definitely_no_external_effect"] is False

    def test_created_variants_are_returned_without_invented_input_indexes(
        self, http: FakeHttp
    ) -> None:
        """Shopify states no correspondence for creates, so none is fabricated."""
        http.queue(self._create_answer([variant_node(VARIANT_B), variant_node(VARIANT_A)]))

        response = run_action(
            "create_product_variants_batch",
            {
                "product_id": PRODUCT_A,
                "variants": [
                    {"option_values": [{"option_name": "Size", "value": "41"}]},
                    {"option_values": [{"option_name": "Size", "value": "42"}]},
                ],
            },
            http,
        )

        variants = response["result"]["product_variants"]
        assert [v["id"] for v in variants] == [VARIANT_B, VARIANT_A]
        assert all("index" not in v for v in variants)


class TestMediaAlt:
    def test_the_file_input_is_exactly_id_and_alt(self, http: FakeHttp) -> None:
        """`FileUpdateInput` can also move a file's source, filename, preview and
        product references. None of that is reachable from here."""
        http.queue(
            graphql_response(
                {
                    "fileUpdate": {
                        "files": [{"id": MEDIA_A, "alt": "Boots", "fileStatus": "READY"}],
                        "userErrors": [],
                    }
                }
            )
        )

        run_action("update_product_media_alt", {"media_id": MEDIA_A, "alt": "Boots"}, http)

        files = http.variables()["files"]
        assert len(files) == 1
        assert set(files[0]) == {"id", "alt"}

    @pytest.mark.parametrize(
        "media_id",
        ["gid://shopify/Video/1", "gid://shopify/Model3d/1", MEDIA_A],
    )
    def test_the_three_media_types_are_accepted(self, media_id: str, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {"fileUpdate": {"files": [{"id": media_id, "alt": "a"}], "userErrors": []}}
            )
        )

        response = run_action("update_product_media_alt", {"media_id": media_id, "alt": "a"}, http)

        assert response["ok"] is True

    @pytest.mark.parametrize("media_id", [PRODUCT_A, "gid://shopify/GenericFile/1", "1"])
    def test_anything_that_is_not_media_is_refused(self, media_id: str, http: FakeHttp) -> None:
        response = run_action("update_product_media_alt", {"media_id": media_id, "alt": "a"}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    @pytest.mark.parametrize("alt", ["", None, 42])
    def test_an_empty_alt_is_refused(self, alt: object, http: FakeHttp) -> None:
        response = run_action("update_product_media_alt", {"media_id": MEDIA_A, "alt": alt}, http)

        assert response["error_code"] == errors.INVALID_PAYLOAD

    def test_only_one_file_can_ever_be_addressed(self) -> None:
        from runtime.catalog import OPERATIONS_BY_ID

        row = OPERATIONS_BY_ID["update_product_media_alt"]
        properties = row.input_schema["properties"]

        assert properties["media_id"]["type"] == "string"
        assert "files" not in properties
