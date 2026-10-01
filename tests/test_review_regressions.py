"""Regressions from the catalog/orders review.

Each test here reproduced a defect before it was fixed. They are grouped by
what went wrong rather than by operation, because the same mistake showed up in
several places and the grouping is what makes that visible.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import (
    FULFILLMENT_ORDER_A,
    ITEM_A,
    ORDER_A,
    PRODUCT_A,
    PRODUCT_B,
    VARIANT_A,
    VARIANT_B,
    FakeHttp,
    connection,
    graphql_response,
    metafield_node,
    order_node,
    product_node,
    run_action,
    run_operation,
    variant_node,
)
from runtime import catalog, errors, gids
from runtime.catalog import OPERATIONS_BY_ID
from runtime.errors import ExtensionError

#: A real Shopify taxonomy category id. They are handle-shaped, not numeric.
REAL_CATEGORY = "gid://shopify/TaxonomyCategory/hb-1-9-6"


class TestTaxonomyCategoryIdsAreNotNumeric:
    """Shopify's taxonomy ids look like `hb-1-9-6`, not like `5001`.

    The first cut validated every GID's id as digits, so `category_id` was
    unusable in practice while the tests passed against an invented numeric id.
    A fixture that cannot occur in production proves nothing.
    """

    @pytest.mark.parametrize(
        "category_id",
        [
            "gid://shopify/TaxonomyCategory/hb-1-9-6",
            "gid://shopify/TaxonomyCategory/aa-1-13-8",
            "gid://shopify/TaxonomyCategory/na",
        ],
    )
    def test_a_real_taxonomy_id_is_accepted(self, category_id: str) -> None:
        assert (
            gids.gid(category_id, expected_type=gids.TAXONOMY_CATEGORY, field="category_id")
            == category_id
        )

    def test_create_product_accepts_a_real_category(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "productCreate": {
                        "product": product_node(variants=connection([variant_node()])),
                        "userErrors": [],
                    }
                }
            )
        )

        response = run_action(
            "create_product",
            {"title": "Boots", "handle": "boots", "category_id": REAL_CATEGORY},
            http,
        )

        assert response["ok"] is True
        assert http.variables()["product"]["category"] == REAL_CATEGORY

    @pytest.mark.parametrize(
        "category_id",
        [
            "gid://shopify/TaxonomyCategory/",
            "gid://shopify/TaxonomyCategory/HB-1",
            "gid://shopify/TaxonomyCategory/hb 1",
            "gid://shopify/TaxonomyCategory/hb/1",
            "gid://shopify/Product/hb-1-9-6",
        ],
    )
    def test_a_malformed_category_is_still_refused(self, category_id: str, http: FakeHttp) -> None:
        response = run_action(
            "create_product",
            {"title": "B", "handle": "b", "category_id": category_id},
            http,
        )

        assert response["error_code"] == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_every_other_type_still_requires_a_numeric_id(self) -> None:
        """Loosening one type must not loosen the rest."""
        for expected in (gids.PRODUCT, gids.ORDER, gids.INVENTORY_ITEM, gids.FULFILLMENT):
            with pytest.raises(ExtensionError) as raised:
                gids.gid(f"gid://shopify/{expected}/hb-1-9-6", expected_type=expected, field="x")
            assert raised.value.code == errors.INVALID_PAYLOAD


class TestLongTextIsNotSilentlyTruncated:
    """A result that quietly loses characters is worse than one that fails.

    Descriptions and metafield values are legitimately long — the schemas allow
    65535 and 512 KiB — and the shaper was clipping every string at 8192. A
    caller reading the result back would see a complete-looking product whose
    description had been cut mid-word.
    """

    def test_a_long_description_survives_a_create(self, http: FakeHttp) -> None:
        description = "<p>" + ("x" * 9000) + "</p>"
        http.queue(
            graphql_response(
                {
                    "productCreate": {
                        "product": product_node(
                            descriptionHtml=description,
                            variants=connection([variant_node()]),
                        ),
                        "userErrors": [],
                    }
                }
            )
        )

        response = run_action(
            "create_product",
            {"title": "Boots", "handle": "boots", "description_html": description},
            http,
        )

        assert response["result"]["product"]["description_html"] == description

    def test_a_long_metafield_value_survives_a_read(self, http: FakeHttp) -> None:
        value = "y" * 100_000
        http.queue(
            graphql_response(
                {
                    "node": {
                        "__typename": "Product",
                        "id": PRODUCT_A,
                        "metafields": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [dict(metafield_node(), value=value)],
                        },
                    }
                }
            )
        )

        response = run_operation(
            "list_catalog_metafields", {"owner_type": "product", "owner_id": PRODUCT_A}, http
        )

        assert response["result"]["metafields"][0]["value"] == value

    def test_a_long_order_note_survives(self, http: FakeHttp) -> None:
        note = "n" * 20_000
        http.queue(graphql_response({"order": order_node(note=note)}))

        response = run_operation("get_order", {"order_id": ORDER_A}, http)

        assert response["result"]["order"]["note"] == note

    def test_the_transport_limit_is_what_bounds_a_response(self, http: FakeHttp) -> None:
        """Size is bounded once, at the transport, not per field.

        Bounding each field separately gives no overall guarantee and silently
        edits the data; bounding the response gives a guarantee and fails loudly.
        """
        from runtime.transport import MAX_RESPONSE_BYTES

        assert MAX_RESPONSE_BYTES == 4 * 1024 * 1024


class TestPartialDataWithAnyTopLevelErrorIsUnknown:
    """A recognised error code does not make partial data trustworthy.

    `THROTTLED` normally means Shopify refused before doing anything — but not
    when it arrives *alongside* a mutation payload. Then something ran, and the
    only honest answer is that this side cannot say what.
    """

    @pytest.mark.parametrize(
        "code", ["THROTTLED", "ACCESS_DENIED", "SHOP_INACTIVE", "MAX_COST_EXCEEDED", "NEW_CODE"]
    )
    def test_a_mutation_with_partial_data_is_unknown_whatever_the_code(
        self, code: str, http: FakeHttp
    ) -> None:
        http.queue(
            graphql_response(
                {"orderUpdate": {"order": order_node(), "userErrors": []}},
                errors=[{"message": "x", "extensions": {"code": code}}],
            )
        )

        response = run_action("update_order_metadata", {"order_id": ORDER_A, "note": "x"}, http)

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN
        assert response["definitely_no_external_effect"] is False

    @pytest.mark.parametrize("code", ["THROTTLED", "ACCESS_DENIED", "SHOP_INACTIVE"])
    def test_without_partial_data_the_code_still_decides(self, code: str, http: FakeHttp) -> None:
        """A refusal with no data is still a definite refusal."""
        http.queue(graphql_response(None, errors=[{"extensions": {"code": code}}]))

        response = run_action("update_order_metadata", {"order_id": ORDER_A, "note": "x"}, http)

        assert response["error_code"] != errors.TIMEOUT_UNKNOWN

    def test_a_source_with_partial_data_still_discards_it(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {"order": order_node()}, errors=[{"extensions": {"code": "THROTTLED"}}]
            )
        )

        response = run_operation("get_order", {"order_id": ORDER_A}, http)

        assert response["ok"] is False
        assert response["error_code"] == errors.RATE_LIMITED


class TestCreatedVariantsMustBeFullyConfirmed:
    """An empty list is not a confirmation that one variant was created."""

    def test_no_returned_variants_is_not_success(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {"productVariantsBulkCreate": {"productVariants": [], "userErrors": []}}
            )
        )

        response = run_action(
            "create_product_variants_batch",
            {
                "product_id": PRODUCT_A,
                "variants": [{"option_values": [{"option_name": "Size", "value": "42"}]}],
            },
            http,
        )

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN
        assert response["definitely_no_external_effect"] is False

    def test_fewer_variants_than_requested_is_not_success(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "productVariantsBulkCreate": {
                        "productVariants": [variant_node(VARIANT_A)],
                        "userErrors": [],
                    }
                }
            )
        )

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

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN

    def test_a_duplicate_returned_id_is_not_success(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "productVariantsBulkCreate": {
                        "productVariants": [variant_node(VARIANT_A), variant_node(VARIANT_A)],
                        "userErrors": [],
                    }
                }
            )
        )

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

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN

    def test_a_variant_on_another_product_is_not_success(self, http: FakeHttp) -> None:
        """Confirmed variants must belong to the product that was addressed."""
        http.queue(
            graphql_response(
                {
                    "productVariantsBulkCreate": {
                        "productVariants": [
                            dict(variant_node(VARIANT_A), product={"id": PRODUCT_B})
                        ],
                        "userErrors": [],
                    }
                }
            )
        )

        response = run_action(
            "create_product_variants_batch",
            {
                "product_id": PRODUCT_A,
                "variants": [{"option_values": [{"option_name": "Size", "value": "42"}]}],
            },
            http,
        )

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN

    def test_an_update_confirmation_must_also_be_on_the_addressed_product(
        self, http: FakeHttp
    ) -> None:
        http.queue(
            graphql_response(
                {
                    "productVariantsBulkUpdate": {
                        "productVariants": [
                            dict(variant_node(VARIANT_A), product={"id": PRODUCT_B})
                        ],
                        "userErrors": [],
                    }
                }
            )
        )

        response = run_action(
            "update_product_variants_batch",
            {"product_id": PRODUCT_A, "variants": [{"variant_id": VARIANT_A, "price": "1.00"}]},
            http,
        )

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN

    def test_the_expected_number_is_confirmed_on_the_happy_path(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "productVariantsBulkCreate": {
                        "productVariants": [variant_node(VARIANT_A), variant_node(VARIANT_B)],
                        "userErrors": [],
                    }
                }
            )
        )

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

        assert response["ok"] is True
        assert len(response["result"]["product_variants"]) == 2


class TestCanonicalScopeRequirements:
    """Core, UI, readiness, and runtime consume one exact all-of contract."""

    def test_a_location_uses_the_supported_inventory_write_profile(self) -> None:
        assert OPERATIONS_BY_ID["list_locations"].required_oauth_scopes == (
            "write_inventory",
            "read_locations",
        )

    @pytest.mark.parametrize("operation_id", ["list_inventory_items", "get_inventory_item"])
    def test_inventory_reads_use_the_granted_write_profile(self, operation_id: str) -> None:
        assert OPERATIONS_BY_ID[operation_id].required_oauth_scopes == ("write_inventory",)

    def test_setting_stock_still_needs_the_write_scope(self) -> None:
        assert OPERATIONS_BY_ID["set_inventory_quantities"].required_oauth_scopes == (
            "write_inventory",
        )

    def test_the_capability_report_reflects_exact_canonical_requirements(
        self, http: FakeHttp
    ) -> None:
        http.queue(
            graphql_response(
                {
                    "shop": {
                        "id": "gid://shopify/Shop/1",
                        "name": "S",
                        "myshopifyDomain": "flow-steward-test.myshopify.com",
                    },
                    "currentAppInstallation": {"accessScopes": [{"handle": "write_inventory"}]},
                }
            )
        )

        response = run_operation("test_connection", {}, http)

        rows = response["result"]["capability_scope_matrix"]
        assert rows["list_locations"]["scope_eligible"] is False
        assert rows["list_locations"]["missing_required_oauth_scopes"] == ["read_locations"]
        assert rows["list_inventory_items"]["scope_eligible"] is True


class TestASourceVerifiesTheRecordItAskedFor:
    """A store answering about a different record is not a success.

    It is not `not_found` either — the record may well exist. Something between
    the request and the answer is wrong, and the honest report is an upstream
    failure rather than handing the workflow someone else's data.
    """

    @pytest.mark.parametrize(
        ("operation_id", "field", "graphql_field", "wrong_node"),
        [
            ("get_product", "product_id", "product", {"id": PRODUCT_B}),
            (
                "get_product_variant",
                "product_variant_id",
                "productVariant",
                {"id": VARIANT_B},
            ),
            ("get_order", "order_id", "order", {"id": "gid://shopify/Order/9999"}),
            (
                "get_fulfillment_order",
                "fulfillment_order_id",
                "fulfillmentOrder",
                {"id": "gid://shopify/FulfillmentOrder/9999"},
            ),
        ],
    )
    def test_an_answer_about_another_record_is_an_upstream_failure(
        self,
        operation_id: str,
        field: str,
        graphql_field: str,
        wrong_node: dict,
        http: FakeHttp,
    ) -> None:
        requested = {
            "get_product": PRODUCT_A,
            "get_product_variant": VARIANT_A,
            "get_order": ORDER_A,
            "get_fulfillment_order": FULFILLMENT_ORDER_A,
        }[operation_id]
        http.queue(graphql_response({graphql_field: wrong_node}))

        response = run_operation(operation_id, {field: requested}, http)

        assert response["error_code"] == errors.UPSTREAM_FAILURE
        assert response["ok"] is False

    @pytest.mark.parametrize(
        ("operation_id", "extra"),
        [
            ("list_order_line_items", {}),
            ("list_order_metafields", {}),
            ("list_order_fulfillment_orders", {}),
            ("list_order_fulfillments", {}),
        ],
    )
    def test_an_order_subquery_about_another_order_is_refused(
        self, operation_id: str, extra: dict, http: FakeHttp
    ) -> None:
        http.queue(
            graphql_response(
                {
                    "order": {
                        "id": "gid://shopify/Order/9999",
                        "lineItems": {"pageInfo": {}, "nodes": []},
                        "metafields": {"pageInfo": {}, "nodes": []},
                        "fulfillmentOrders": {"pageInfo": {}, "nodes": []},
                        "fulfillments": [],
                        "fulfillmentsCount": {"count": 0},
                    }
                }
            )
        )

        response = run_operation(operation_id, {"order_id": ORDER_A, **extra}, http)

        assert response["error_code"] == errors.UPSTREAM_FAILURE

    def test_a_product_subquery_about_another_product_is_refused(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response({"product": {"id": PRODUCT_B, "media": {"pageInfo": {}, "nodes": []}}})
        )

        response = run_operation("list_product_media", {"product_id": PRODUCT_A}, http)

        assert response["error_code"] == errors.UPSTREAM_FAILURE

    def test_a_catalog_metafield_owner_must_be_the_owner_that_was_asked_for(
        self, http: FakeHttp
    ) -> None:
        http.queue(
            graphql_response(
                {
                    "node": {
                        "__typename": "Product",
                        "id": PRODUCT_B,
                        "metafields": {"pageInfo": {}, "nodes": []},
                    }
                }
            )
        )

        response = run_operation(
            "list_catalog_metafields", {"owner_type": "product", "owner_id": PRODUCT_A}, http
        )

        assert response["error_code"] == errors.UPSTREAM_FAILURE

    def test_a_missing_record_is_still_not_found(self, http: FakeHttp) -> None:
        """The two cases stay distinguishable: absent is not the same as wrong."""
        http.queue(graphql_response({"product": None}))

        response = run_operation("get_product", {"product_id": PRODUCT_A}, http)

        assert response["error_code"] == errors.NOT_FOUND


class TestAnExtraMetafieldConfirmationIsNotIgnored:
    """Returning more than was asked for means the answer is not understood."""

    def test_an_unrequested_metafield_makes_the_outcome_unknown(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "metafieldsSet": {
                        "metafields": [
                            metafield_node(
                                key="care", owner={"__typename": "Product", "id": PRODUCT_A}
                            ),
                            metafield_node(
                                key="surprise", owner={"__typename": "Product", "id": PRODUCT_A}
                            ),
                        ],
                        "userErrors": [],
                    }
                }
            )
        )

        response = run_action(
            "set_catalog_metafields",
            {
                "metafields": [
                    {
                        "owner_id": PRODUCT_A,
                        "namespace": "custom",
                        "key": "care",
                        "type": "single_line_text_field",
                        "value": "hand wash",
                        "compare_digest": None,
                    }
                ]
            },
            http,
        )

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN
        assert response["definitely_no_external_effect"] is False

    def test_an_exact_match_is_still_success(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "metafieldsSet": {
                        "metafields": [
                            metafield_node(
                                key="care", owner={"__typename": "Product", "id": PRODUCT_A}
                            )
                        ],
                        "userErrors": [],
                    }
                }
            )
        )

        response = run_action(
            "set_catalog_metafields",
            {
                "metafields": [
                    {
                        "owner_id": PRODUCT_A,
                        "namespace": "custom",
                        "key": "care",
                        "type": "single_line_text_field",
                        "value": "hand wash",
                        "compare_digest": None,
                    }
                ]
            },
            http,
        )

        assert response["ok"] is True


class TestInventoryLevelsNeedTheInventoryWriteProfile:
    """The configured write grant covers inventory items and their levels."""

    def test_read_products_alone_does_not_cover_a_stock_read(self) -> None:
        assert OPERATIONS_BY_ID["get_inventory_levels_batch"].required_oauth_scopes == (
            "write_inventory",
        )

    def test_reading_the_item_itself_uses_the_same_write_profile(self) -> None:
        for operation_id in ("list_inventory_items", "get_inventory_item"):
            assert OPERATIONS_BY_ID[operation_id].required_oauth_scopes == ("write_inventory",)


class TestAVariantWithNoOwnerIsUnknown:
    """A confirmation that omits the owner cannot be checked, so it is unknown.

    The owner check skipped any record whose `product` was missing or had no
    `id`, which turned "cannot verify" into "verified". The write may already
    have happened, so the honest answer is `timeout_unknown`.
    """

    @pytest.mark.parametrize("owner", [None, {}, {"id": None}, "gid://shopify/Product/3001", 7])
    def test_create_refuses_to_confirm_an_unowned_variant(
        self, owner: object, http: FakeHttp
    ) -> None:
        node = variant_node()
        node["product"] = owner
        http.queue(
            graphql_response(
                {"productVariantsBulkCreate": {"productVariants": [node], "userErrors": []}}
            )
        )

        response = run_action(
            "create_product_variants_batch",
            {
                "product_id": PRODUCT_A,
                "variants": [{"option_values": [{"option_name": "Size", "value": "42"}]}],
            },
            http,
        )

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN
        assert response["definitely_no_external_effect"] is False

    def test_create_refuses_a_variant_with_no_product_key_at_all(self, http: FakeHttp) -> None:
        node = variant_node()
        del node["product"]
        http.queue(
            graphql_response(
                {"productVariantsBulkCreate": {"productVariants": [node], "userErrors": []}}
            )
        )

        response = run_action(
            "create_product_variants_batch",
            {
                "product_id": PRODUCT_A,
                "variants": [{"option_values": [{"option_name": "Size", "value": "42"}]}],
            },
            http,
        )

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN

    def test_update_refuses_an_unowned_variant_too(self, http: FakeHttp) -> None:
        node = variant_node()
        node["product"] = {}
        http.queue(
            graphql_response(
                {"productVariantsBulkUpdate": {"productVariants": [node], "userErrors": []}}
            )
        )

        response = run_action(
            "update_product_variants_batch",
            {"product_id": PRODUCT_A, "variants": [{"variant_id": VARIANT_A, "price": "1.00"}]},
            http,
        )

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN

    def test_a_properly_owned_variant_still_succeeds(self, http: FakeHttp) -> None:
        http.queue(
            graphql_response(
                {
                    "productVariantsBulkCreate": {
                        "productVariants": [variant_node()],
                        "userErrors": [],
                    }
                }
            )
        )

        response = run_action(
            "create_product_variants_batch",
            {
                "product_id": PRODUCT_A,
                "variants": [{"option_values": [{"option_name": "Size", "value": "42"}]}],
            },
            http,
        )

        assert response["ok"] is True
        assert response["result"]["product_variants"][0]["product_id"] == PRODUCT_A


class TestOnlyAnExplicitNullMeansNotFound:
    """Absence and malformedness are different answers and get different codes.

    `product: null` is Shopify saying the record is not there. A missing key, a
    non-object, or an object with no `id` is Shopify answering badly — reporting
    that as `not_found` tells a workflow the record was deleted when nothing of
    the sort is known.
    """

    def test_an_explicit_null_is_not_found(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"product": None}))

        response = run_operation("get_product", {"product_id": PRODUCT_A}, http)

        assert response["error_code"] == errors.NOT_FOUND

    @pytest.mark.parametrize(
        "node",
        [{"title": "Boots"}, {"id": None}, {}, "Boots", 7, [], [{"id": PRODUCT_A}]],
    )
    def test_a_malformed_node_is_an_upstream_failure(self, node: object, http: FakeHttp) -> None:
        http.queue(graphql_response({"product": node}))

        response = run_operation("get_product", {"product_id": PRODUCT_A}, http)

        assert response["error_code"] == errors.UPSTREAM_FAILURE

    def test_a_missing_field_is_an_upstream_failure(self, http: FakeHttp) -> None:
        """No `product` key at all is a malformed answer, not an absent record."""
        http.queue(graphql_response({}))

        response = run_operation("get_product", {"product_id": PRODUCT_A}, http)

        assert response["error_code"] == errors.UPSTREAM_FAILURE

    def test_the_same_holds_for_every_get_by_id(self, http: FakeHttp) -> None:
        for operation_id, payload, field in (
            ("get_order", {"order_id": ORDER_A}, "order"),
            ("get_inventory_item", {"inventory_item_id": ITEM_A}, "inventoryItem"),
        ):
            http.queue(graphql_response({field: None}))
            assert run_operation(operation_id, payload, http)["error_code"] == errors.NOT_FOUND

            http.queue(graphql_response({field: {"title": "x"}}))
            assert (
                run_operation(operation_id, payload, http)["error_code"] == errors.UPSTREAM_FAILURE
            )


class TestTheProseDescribesTheCurrentSurface:
    """Prose frozen at the previous release misdescribes the extension.

    The counts were corrected in the README once and then turned up again in
    `catalog.py`'s own first line, which is why this checks the number rather
    than the wording: a stale count is a claim about the registry, so the
    registry is what it is checked against.
    """

    def test_the_readme_never_claims_the_first_release_counts(self) -> None:
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")

        assert "eight rows" not in readme
        assert "eight declared operations" not in readme
        assert "seven GraphQL documents" not in readme

    def test_the_registry_docstring_states_the_real_number_of_rows(self) -> None:
        summary = (catalog.__doc__ or "").splitlines()[0]
        spelled = {
            8: "eight",
            30: "thirty",
            31: "thirty-one",
            32: "thirty-two",
            33: "thirty-three",
        }[len(OPERATIONS_BY_ID)]

        assert spelled in summary, summary
