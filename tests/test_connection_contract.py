"""The store address rules, the token rules, and connection isolation."""

from __future__ import annotations

import pytest
from conftest import (
    ACCESS_TOKEN,
    SHOP_DOMAIN,
    FakeHttp,
    connection_payload,
    graphql_response,
)
from runtime import errors
from runtime.connection import (
    CONFIG_FIELDS,
    CONNECTION_TYPE_ID,
    SECRET_FIELDS,
    connection_from_payload,
    normalize_shop_domain,
)
from runtime.documents import API_VERSION
from runtime.errors import ExtensionError
from runtime.operations import handle_runtime

ACCEPTED = [
    ("acme", "acme.myshopify.com"),
    ("acme.myshopify.com", "acme.myshopify.com"),
    ("ACME", "acme.myshopify.com"),
    ("Acme.MyShopify.Com", "acme.myshopify.com"),
    ("  acme.myshopify.com  ", "acme.myshopify.com"),
    ("a", "a.myshopify.com"),
    ("acme-store-01", "acme-store-01.myshopify.com"),
]

REJECTED = [
    ("a scheme", "https://acme.myshopify.com"),
    ("a bare scheme", "http://acme"),
    ("a protocol-relative address", "//acme.myshopify.com"),
    ("a path", "acme.myshopify.com/admin"),
    ("a trailing slash", "acme.myshopify.com/"),
    ("a port", "acme.myshopify.com:443"),
    ("credentials", "user:pass@acme.myshopify.com"),
    ("an at sign", "acme@myshopify.com"),
    ("a query string", "acme.myshopify.com?x=1"),
    ("a fragment", "acme.myshopify.com#top"),
    ("inner whitespace", "acme store.myshopify.com"),
    ("a tab", "acme\t.myshopify.com"),
    ("a wildcard", "*.myshopify.com"),
    ("a custom storefront domain", "shop.example.com"),
    ("a lookalike domain", "acme.myshopify.com.evil.test"),
    ("a nested subdomain", "eu.acme.myshopify.com"),
    ("a trailing dot", "acme.myshopify.com."),
    ("a leading hyphen", "-acme"),
    ("a trailing hyphen", "acme-"),
    ("an underscore", "acme_store"),
    ("a control character", "acme\x00"),
    ("an empty value", ""),
    ("only the suffix", ".myshopify.com"),
    ("a name that is too long", "a" * 61),
]


class TestTheStoreAddressIsNormalized:
    @pytest.mark.parametrize(("entered", "stored"), ACCEPTED)
    def test_both_forms_a_merchant_has_to_hand_are_accepted(
        self, entered: str, stored: str
    ) -> None:
        assert normalize_shop_domain(entered) == stored

    @pytest.mark.parametrize(("description", "entered"), REJECTED)
    def test_anything_more_than_a_hostname_is_refused(self, description: str, entered: str) -> None:
        with pytest.raises(ExtensionError) as raised:
            normalize_shop_domain(entered)

        assert raised.value.code == errors.INVALID_CONFIGURATION, description

    @pytest.mark.parametrize("entered", [None, 42, True, ["acme"], {"shop": "acme"}])
    def test_a_value_that_is_not_a_string_is_refused(self, entered: object) -> None:
        with pytest.raises(ExtensionError) as raised:
            normalize_shop_domain(entered)

        assert raised.value.code == errors.INVALID_CONFIGURATION


class TestTheEndpointHasExactlyOneSource:
    def test_it_is_derived_from_the_stored_domain_and_the_pinned_version(self) -> None:
        connection = connection_from_payload(
            connection_payload("get_shop", shop_domain="ACME"), connection_ref="conn-1"
        )

        assert connection.shop_domain == "acme.myshopify.com"
        assert connection.graphql_endpoint == (
            f"https://acme.myshopify.com/admin/api/{API_VERSION}/graphql.json"
        )

    def test_no_operation_publishes_an_endpoint_input(self) -> None:
        from runtime.catalog import OPERATIONS

        forbidden = {"endpoint", "url", "graphql_url", "api_version", "host", "base_url"}
        for row in OPERATIONS:
            assert not forbidden & set(row.input_field_names), row.operation_id


class TestTheConnectionReferenceMustNameTheHydratedConnection:
    def test_a_mismatch_is_refused_before_any_request(self, http: FakeHttp) -> None:
        payload = connection_payload("get_shop", connection_ref="some-other-connection")

        response = handle_runtime(payload, transport_factory=lambda c: None)

        assert response["error_code"] == errors.INVALID_CONNECTION
        assert http.requests == []

    def test_a_connection_of_another_type_is_refused(self) -> None:
        payload = connection_payload("get_shop", connection_type_id="wordpress_site")

        response = handle_runtime(payload, transport_factory=lambda c: None)

        assert response["error_code"] == errors.INVALID_CONNECTION

    def test_a_missing_connection_is_refused(self) -> None:
        payload = connection_payload("get_shop")
        del payload["action"]["target"]

        response = handle_runtime(payload, transport_factory=lambda c: None)

        assert response["error_code"] == errors.INVALID_CONNECTION

    def test_the_declared_connection_type_is_the_one_the_contract_publishes(self) -> None:
        """The store arrives as the verified OAuth subject, not as configuration."""
        assert CONNECTION_TYPE_ID == "shopify_admin"
        assert {"oauth"} == CONFIG_FIELDS
        assert {"access_token"} == SECRET_FIELDS


class TestTheConnectionCarriesOnlyWhatItDeclares:
    def test_an_unsupported_config_field_is_refused(self) -> None:
        payload = connection_payload(
            "get_shop",
            config={"oauth": {"subject": SHOP_DOMAIN}, "api_version": "2024-01"},
        )

        response = handle_runtime(payload, transport_factory=lambda c: None)

        assert response["error_code"] == errors.INVALID_CONNECTION

    def test_an_unsupported_secret_field_is_refused(self) -> None:
        payload = connection_payload(
            "get_shop",
            secrets={"admin_api_access_token": ACCESS_TOKEN, "api_secret_key": "x"},
        )

        response = handle_runtime(payload, transport_factory=lambda c: None)

        assert response["error_code"] == errors.INVALID_CONNECTION

    @pytest.mark.parametrize(
        "token", ["", "   ", "short", "with space", "with\nnewline", "a" * 513, None, 42]
    )
    def test_an_unusable_token_is_refused(self, token: object) -> None:
        payload = connection_payload("get_shop", secrets={"admin_api_access_token": token})

        response = handle_runtime(payload, transport_factory=lambda c: None)

        assert response["error_code"] == errors.INVALID_CONNECTION

    def test_the_refusal_never_quotes_the_value_it_refused(self) -> None:
        """A rejected token is still a secret: the message may not repeat it."""
        rejected = "shpat_this_value_must_never_be_echoed_back"  # pragma: allowlist secret
        payload = connection_payload(
            "get_shop", secrets={"admin_api_access_token": f"{rejected} with a space"}
        )

        response = handle_runtime(payload, transport_factory=lambda c: None)

        assert response["error_code"] == errors.INVALID_CONNECTION
        assert rejected not in str(response)


class TestTwoConnectionsInOneProjectStayIsolated:
    def test_each_invocation_uses_only_its_own_connection(self, http: FakeHttp) -> None:
        from runtime.transport import ShopifyGraphQLTransport

        def factory(connection):
            return ShopifyGraphQLTransport(connection, opener=http)

        first_token = "shpat_1111111111111111111111111111"  # pragma: allowlist secret
        second_token = "shpat_2222222222222222222222222222"  # pragma: allowlist secret
        http.queue(
            graphql_response({"shop": {"id": "gid://shopify/Shop/1"}}),
            graphql_response({"shop": {"id": "gid://shopify/Shop/2"}}),
        )

        handle_runtime(
            connection_payload(
                "get_shop",
                shop_domain="first-store",
                access_token=first_token,
                connection_id="conn-first",
            ),
            transport_factory=factory,
        )
        handle_runtime(
            connection_payload(
                "get_shop",
                shop_domain="second-store",
                access_token=second_token,
                connection_id="conn-second",
            ),
            transport_factory=factory,
        )

        assert http.requests[0]["url"].startswith("https://first-store.myshopify.com/")
        assert http.requests[0]["headers"]["x-shopify-access-token"] == first_token
        assert http.requests[1]["url"].startswith("https://second-store.myshopify.com/")
        assert http.requests[1]["headers"]["x-shopify-access-token"] == second_token

    def test_a_failed_invocation_leaves_nothing_behind_for_the_next_one(
        self, http: FakeHttp
    ) -> None:
        from runtime.transport import ShopifyGraphQLTransport

        def factory(connection):
            return ShopifyGraphQLTransport(connection, opener=http)

        http.queue(graphql_response({"shop": {"id": "gid://shopify/Shop/2"}}))

        # The first invocation never reaches the transport at all.
        failed = handle_runtime(
            connection_payload("get_shop", connection_ref="wrong"), transport_factory=factory
        )
        assert failed["ok"] is False

        second = handle_runtime(
            connection_payload("get_shop", shop_domain="second-store", connection_id="c2"),
            transport_factory=factory,
        )

        assert second["ok"] is True
        assert len(http.requests) == 1
        assert http.requests[0]["url"].startswith("https://second-store.myshopify.com/")
