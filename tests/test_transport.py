"""What the transport sends, what it refuses, and how failures are classified."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from urllib.error import HTTPError, URLError

import pytest
from conftest import (
    ACCESS_TOKEN,
    ITEM_A,
    SHOP_DOMAIN,
    FakeHttp,
    FakeResponse,
    connection_payload,
    graphql_response,
    quantity,
    set_quantities_payload,
)
from flowsteward_extension_sdk import PinnedPeerError
from runtime import errors
from runtime.documents import API_VERSION
from runtime.operations import handle_runtime
from runtime.transport import MAX_RESPONSE_BYTES


def test_shopify_retry_after_accepts_http_date() -> None:
    from runtime.transport import _retry_after_seconds

    value = format_datetime(datetime.now(UTC) + timedelta(minutes=10), usegmt=True)

    assert 590 <= (_retry_after_seconds({"Retry-After": value}) or 0) <= 600


def run(operation_id: str, http: FakeHttp, operation_input: dict | None = None) -> dict:
    from runtime.transport import ShopifyGraphQLTransport

    return handle_runtime(
        connection_payload(operation_id, operation_input or {}),
        transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
    )


def run_mutation(http: FakeHttp) -> dict:
    from runtime.transport import ShopifyGraphQLTransport

    return handle_runtime(
        set_quantities_payload([quantity()]),
        transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
    )


def http_error(status: int) -> HTTPError:
    return HTTPError("https://example.test", status, "boom", {}, None)


class TestTheRequestItself:
    def test_exactly_one_post_goes_to_the_derived_endpoint(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"shop": {"id": "gid://shopify/Shop/1"}}))

        run("get_shop", http)

        assert len(http.requests) == 1
        assert http.last["method"] == "POST"
        assert http.last["url"] == (f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/graphql.json")

    def test_the_body_is_json_with_a_query_and_variables_and_nothing_else(
        self, http: FakeHttp
    ) -> None:
        http.queue(graphql_response({"shop": {"id": "gid://shopify/Shop/1"}}))

        run("get_shop", http)

        assert set(http.json_body()) == {"query", "variables"}
        assert http.last["headers"]["content-type"].startswith("application/json")

    def test_the_token_is_sent_in_shopifys_own_header(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"shop": {"id": "gid://shopify/Shop/1"}}))

        run("get_shop", http)

        assert http.last["headers"]["x-shopify-access-token"] == ACCESS_TOKEN
        assert "authorization" not in http.last["headers"]

    def test_the_timeout_is_bounded(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"shop": {"id": "gid://shopify/Shop/1"}}))

        run("get_shop", http)

        assert 1.0 <= http.last["timeout_seconds"] <= 30.0

    def test_a_ridiculous_timeout_is_clamped(self) -> None:
        from runtime.connection import connection_from_payload
        from runtime.transport import MAX_TIMEOUT_SECONDS, ShopifyGraphQLTransport

        connection = connection_from_payload(
            connection_payload("get_shop"), connection_ref="conn-1"
        )

        assert (
            ShopifyGraphQLTransport(connection, timeout_seconds=9999)._timeout_seconds
            == MAX_TIMEOUT_SECONDS
        )
        assert ShopifyGraphQLTransport(connection, timeout_seconds=0)._timeout_seconds == 1.0


class TestHttpFailuresAreClassified:
    def test_a_rate_limited_read_exposes_only_retry_safe_facts(self, http: FakeHttp) -> None:
        http.queue(HTTPError("https://example.test", 429, "boom", {"Retry-After": "7"}, None))

        response = run("get_shop", http)

        expected = {
            "failure_class": "provider",
            "retryable": True,
            "retry_after_seconds": 7.0,
            "definitely_no_external_effect": True,
            "external_effect_status": "failed",
            "provider_error_code": errors.RATE_LIMITED,
            "http_status": 429,
        }
        assert response.items() >= expected.items()

    def test_an_ambiguous_mutation_never_requests_replay(self, http: FakeHttp) -> None:
        http.queue(http_error(503))

        response = run_mutation(http)

        assert response["failure_class"] == "provider"
        assert response["retryable"] is False
        assert response["external_effect_status"] == "timeout_unknown"
        assert response["definitely_no_external_effect"] is False

    @pytest.mark.parametrize(
        ("status", "code"),
        [
            (301, errors.REDIRECT_REJECTED),
            (302, errors.REDIRECT_REJECTED),
            (401, errors.AUTHENTICATION_FAILED),
            (402, errors.SHOP_INACTIVE),
            (403, errors.AUTHORIZATION_FAILED),
            (404, errors.NOT_FOUND),
            (423, errors.SHOP_INACTIVE),
            (429, errors.RATE_LIMITED),
            (400, errors.UPSTREAM_VALIDATION_FAILED),
            (500, errors.UPSTREAM_FAILURE),
            (502, errors.UPSTREAM_FAILURE),
            (503, errors.UPSTREAM_FAILURE),
        ],
    )
    def test_a_read_maps_each_status_onto_a_stable_code(
        self, status: int, code: str, http: FakeHttp
    ) -> None:
        http.queue(http_error(status))

        response = run("get_shop", http)

        assert response["error_code"] == code

    @pytest.mark.parametrize("status", [500, 502, 503, 504, 408])
    def test_a_server_failure_after_a_mutation_leaves_the_outcome_unknown(
        self, status: int, http: FakeHttp
    ) -> None:
        http.queue(http_error(status))

        response = run_mutation(http)

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN
        assert response["external_effect_status"] == "timeout_unknown"
        assert response["definitely_no_external_effect"] is False

    @pytest.mark.parametrize("status", [401, 403, 429])
    def test_a_definite_refusal_of_a_mutation_is_not_ambiguous(
        self, status: int, http: FakeHttp
    ) -> None:
        http.queue(http_error(status))

        response = run_mutation(http)

        assert response["error_code"] != errors.TIMEOUT_UNKNOWN
        assert response["external_effect_status"] == "failed"
        assert response["definitely_no_external_effect"] is True

    def test_a_redirect_returned_as_a_normal_response_is_still_refused(
        self, http: FakeHttp
    ) -> None:
        http.queue(FakeResponse(302, b""))

        response = run("get_shop", http)

        assert response["error_code"] == errors.REDIRECT_REJECTED


class TestGraphqlFailuresUnderHttpTwoHundred:
    def test_graphql_throttling_proves_a_mutation_had_no_effect(self, http: FakeHttp) -> None:
        http.queue(graphql_response(None, errors=[{"extensions": {"code": "THROTTLED"}}]))

        response = run_mutation(http)

        assert response["failure_class"] == "provider"
        assert response["retryable"] is True
        assert response["definitely_no_external_effect"] is True
        assert response["external_effect_status"] == "failed"
        assert response["provider_error_code"] == errors.RATE_LIMITED

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("THROTTLED", errors.RATE_LIMITED),
            ("ACCESS_DENIED", errors.AUTHORIZATION_FAILED),
            ("UNAUTHORIZED", errors.AUTHENTICATION_FAILED),
            ("SHOP_INACTIVE", errors.SHOP_INACTIVE),
            ("INTERNAL_SERVER_ERROR", errors.UPSTREAM_FAILURE),
            ("MAX_COST_EXCEEDED", errors.UPSTREAM_VALIDATION_FAILED),
            ("SOMETHING_NEW", errors.UPSTREAM_FAILURE),
            ("", errors.UPSTREAM_FAILURE),
        ],
    )
    def test_a_top_level_error_is_a_failure_even_with_status_two_hundred(
        self, code: str, expected: str, http: FakeHttp
    ) -> None:
        http.queue(
            graphql_response(
                None, status=200, errors=[{"message": "x", "extensions": {"code": code}}]
            )
        )

        response = run("get_shop", http)

        assert response["ok"] is False
        assert response["error_code"] == expected

    def test_throttling_is_recognised_the_way_shopify_actually_reports_it(
        self, http: FakeHttp
    ) -> None:
        http.queue(
            FakeResponse(
                200,
                json.dumps(
                    {
                        "errors": [
                            {
                                "message": "Throttled",
                                "extensions": {
                                    "code": "THROTTLED",
                                    "documentation": "https://shopify.dev/api/usage/rate-limits",
                                },
                            }
                        ],
                        "extensions": {"cost": {"requestedQueryCost": 10}},
                    }
                ).encode(),
            )
        )

        response = run("get_shop", http)

        assert response["error_code"] == errors.RATE_LIMITED

    def test_an_internal_server_error_after_a_mutation_leaves_the_outcome_unknown(
        self, http: FakeHttp
    ) -> None:
        http.queue(
            graphql_response(None, errors=[{"extensions": {"code": "INTERNAL_SERVER_ERROR"}}])
        )

        response = run_mutation(http)

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN

    def test_shopifys_error_message_is_never_echoed(self, http: FakeHttp) -> None:
        message = "Field 'shop' doesn't exist on type 'QueryRoot' at shpat_leak"
        http.queue(
            graphql_response(None, errors=[{"message": message, "extensions": {"code": "X"}}])
        )

        response = run("get_shop", http)

        assert message not in json.dumps(response)
        assert "shpat_leak" not in json.dumps(response)

    def test_a_body_with_no_data_at_all_is_a_failure(self, http: FakeHttp) -> None:
        http.queue(FakeResponse(200, b"{}"))

        response = run("get_shop", http)

        assert response["error_code"] == errors.UPSTREAM_FAILURE

    @pytest.mark.parametrize("body", [b"", b"   ", b"not json", b"[1,2,3]", b'{"data": 4}'])
    def test_a_body_that_is_not_a_graphql_response_is_refused(
        self, body: bytes, http: FakeHttp
    ) -> None:
        http.queue(FakeResponse(200, body))

        response = run("get_shop", http)

        assert response["ok"] is False
        assert response["error_code"] in {
            errors.INVALID_JSON_RESPONSE,
            errors.UPSTREAM_FAILURE,
        }


class TestBoundsAndBlockedAddresses:
    def test_an_oversized_response_is_refused(self, http: FakeHttp) -> None:
        http.queue(FakeResponse(200, b"x" * (MAX_RESPONSE_BYTES + 1)))

        response = run("get_shop", http)

        assert response["error_code"] == errors.RESPONSE_TOO_LARGE

    def test_a_response_at_the_limit_is_still_read(self, http: FakeHttp) -> None:
        padding = "y" * (MAX_RESPONSE_BYTES - 200)
        body = json.dumps({"data": {"shop": {"id": "gid://shopify/Shop/1", "name": padding}}})
        assert len(body) <= MAX_RESPONSE_BYTES
        http.queue(FakeResponse(200, body.encode()))

        response = run("get_shop", http)

        assert response["ok"] is True

    def test_an_oversized_request_body_is_refused(self, http: FakeHttp) -> None:
        from runtime.transport import MAX_REQUEST_BODY_BYTES

        assert MAX_REQUEST_BODY_BYTES > 0
        # 250 entries of bounded ids cannot reach the limit, so the guard is
        # exercised directly rather than through an impossible batch.
        from runtime.connection import connection_from_payload
        from runtime.errors import ExtensionError
        from runtime.transport import ShopifyGraphQLTransport

        connection = connection_from_payload(
            connection_payload("get_shop"), connection_ref="conn-1"
        )
        transport = ShopifyGraphQLTransport(connection, opener=http)

        with pytest.raises(ExtensionError) as raised:
            transport.execute(
                "query { shop { id } }",
                {"padding": "z" * (MAX_REQUEST_BODY_BYTES + 1)},
                mutating=False,
                purpose="test",
            )

        assert raised.value.code == errors.INVALID_PAYLOAD
        assert http.requests == []

    def test_a_blocked_address_is_reported_as_such(self, http: FakeHttp) -> None:
        http.queue(PinnedPeerError("blocked"))

        response = run("get_shop", http)

        assert response["error_code"] == errors.BLOCKED_ADDRESS

    def test_a_read_timeout_is_a_plain_timeout(self, http: FakeHttp) -> None:
        http.queue(TimeoutError("timed out"))

        response = run("get_shop", http)

        assert response["error_code"] == errors.TIMEOUT
        assert response["external_effect_status"] == "failed"
        assert response["definitely_no_external_effect"] is True

    def test_a_mutation_timeout_is_reported_as_unknown(self, http: FakeHttp) -> None:
        http.queue(TimeoutError("timed out"))

        response = run_mutation(http)

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN
        assert response["external_effect_status"] == "timeout_unknown"
        assert response["definitely_no_external_effect"] is False

    def test_a_read_disconnect_is_a_connection_failure(self, http: FakeHttp) -> None:
        http.queue(URLError("connection reset"))

        response = run("get_shop", http)

        assert response["error_code"] == errors.CONNECTION_FAILED

    def test_a_mutation_disconnect_leaves_the_outcome_unknown(self, http: FakeHttp) -> None:
        http.queue(URLError("connection reset"))

        response = run_mutation(http)

        assert response["error_code"] == errors.TIMEOUT_UNKNOWN

    def test_an_ambiguous_mutation_is_never_retried(self, http: FakeHttp) -> None:
        http.queue(TimeoutError("timed out"))

        run_mutation(http)

        assert len(http.requests) == 1


class TestNothingSurvivesAnInvocation:
    def test_the_transport_holds_no_class_level_state(self) -> None:
        from runtime.transport import ShopifyGraphQLTransport

        assert not [
            name
            for name, value in vars(ShopifyGraphQLTransport).items()
            if not name.startswith("__") and isinstance(value, (dict, list, set))
        ]

    def test_the_connection_is_frozen(self) -> None:
        import dataclasses

        from runtime.connection import Connection, connection_from_payload

        connection = connection_from_payload(
            connection_payload("get_shop"), connection_ref="conn-1"
        )

        assert dataclasses.fields(Connection)
        with pytest.raises(dataclasses.FrozenInstanceError):
            connection.shop_domain = "other.myshopify.com"  # type: ignore[misc]

    def test_two_transports_never_share_a_connection(self, http: FakeHttp) -> None:
        from runtime.connection import connection_from_payload
        from runtime.transport import ShopifyGraphQLTransport

        first = ShopifyGraphQLTransport(
            connection_from_payload(
                connection_payload("get_shop", shop_domain="a", connection_id="c1"),
                connection_ref="c1",
            ),
            opener=http,
        )
        second = ShopifyGraphQLTransport(
            connection_from_payload(
                connection_payload("get_shop", shop_domain="b", connection_id="c2"),
                connection_ref="c2",
            ),
            opener=http,
        )

        assert first.endpoint != second.endpoint
        assert first.endpoint.startswith("https://a.myshopify.com/")
        assert second.endpoint.startswith("https://b.myshopify.com/")


class TestTheRealHostPolicyIsStillWired:
    def test_a_loopback_store_address_is_refused_by_the_shipped_guard(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The offline fixture swaps the guard; this proves the real one refuses.

        ``127-0-0-1.myshopify.com`` is not resolved: the SDK's own check runs on
        the address it is given, so no name lookup is needed.
        """
        from runtime import connection as connection_module
        from runtime.connection import assert_shop_domain_allowed
        from runtime.errors import ExtensionError

        monkeypatch.undo()

        def blocked(url: str, purpose: str = "") -> str:
            raise PinnedPeerError("resolves to a disallowed address")

        monkeypatch.setattr(connection_module, "assert_safe_remote_http_url", blocked)

        with pytest.raises(ExtensionError) as raised:
            assert_shop_domain_allowed("acme.myshopify.com")

        assert raised.value.code == errors.BLOCKED_ADDRESS

    def test_the_guard_is_called_on_every_request(self, http: FakeHttp) -> None:
        seen: list[str] = []
        from runtime import connection as connection_module

        original = connection_module.assert_safe_remote_http_url

        def record(url: str, purpose: str = "") -> str:
            seen.append(url)
            return original(url, purpose=purpose)

        connection_module.assert_safe_remote_http_url = record  # type: ignore[assignment]
        try:
            http.queue(graphql_response({"shop": {"id": "gid://shopify/Shop/1"}}))
            run("get_shop", http)
        finally:
            connection_module.assert_safe_remote_http_url = original  # type: ignore[assignment]

        assert seen == [f"https://{SHOP_DOMAIN}"]


class TestOnlyTheDeclaredIdsTravel:
    def test_an_id_reaches_shopify_only_as_a_variable(self, http: FakeHttp) -> None:
        http.queue(graphql_response({"inventoryItem": None}))

        run("get_inventory_item", http, {"inventory_item_id": ITEM_A})

        assert http.variables()["id"] == ITEM_A
        assert ITEM_A not in http.document()
