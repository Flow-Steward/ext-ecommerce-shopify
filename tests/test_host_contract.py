"""The exact host envelope, the closed dispatcher, and the response shape."""

from __future__ import annotations

import pytest
from typing import Any

from conftest import (
    EXTERNAL_EFFECT_ID,
    FOR_EACH_STEP_SCOPE,
    GROUP_STEP_SCOPE,
    HOST_CONTRACT_VERSION,
    ROOT_STEP_SCOPE,
    FakeHttp,
    FakeResponse,
    connection,
    connection_payload,
    graphql_response,
    product_node,
)

from dispatcher import OPERATION_REGISTRY, dispatch_runtime
from runtime import errors
from runtime.catalog import ACTION_OPERATION_IDS, NETWORK_OPERATION_IDS, OPERATION_IDS
from runtime.operations import handle_runtime
from runtime.transport import ShopifyGraphQLTransport


#: The whole routable surface, in registry order. Written out rather than
#: derived, so adding a row to the registry has to be a deliberate edit here
#: too — which is the point of a closed surface.
def _host(body: dict[str, Any]) -> dict[str, Any]:
    """One subprocess payload as the host sends it: contract, scope and body."""
    return {
        "contract_version": HOST_CONTRACT_VERSION,
        "runtime_context": dict(ROOT_STEP_SCOPE),
        **body,
    }


EXPECTED_OPERATIONS = (
    "validate_connection_settings",
    "test_connection",
    "get_shop",
    "list_locations",
    "list_inventory_items",
    "get_inventory_item",
    "get_inventory_levels_batch",
    "set_inventory_quantities",
    "list_products",
    "export_products",
    "get_product",
    "list_product_variants",
    "get_product_variant",
    "list_catalog_metafields",
    "list_product_media",
    "create_product",
    "create_products_bulk",
    "update_product",
    "create_product_variants_batch",
    "update_product_variants_batch",
    "set_catalog_metafields",
    "update_product_media",
    "list_orders",
    "get_order",
    "list_order_line_items",
    "list_order_metafields",
    "list_order_fulfillment_orders",
    "get_fulfillment_order",
    "list_order_fulfillments",
    "update_order_metadata",
    "set_order_metafields",
    "create_fulfillment",
    "update_fulfillment_tracking",
)

EXPECTED_ACTIONS = (
    "set_inventory_quantities",
    "create_product",
    "create_products_bulk",
    "update_product",
    "create_product_variants_batch",
    "update_product_variants_batch",
    "set_catalog_metafields",
    "update_product_media",
    "update_order_metadata",
    "set_order_metafields",
    "create_fulfillment",
    "update_fulfillment_tracking",
)


class TestTheRegistryIsClosed:
    def test_it_holds_exactly_the_declared_operations(self) -> None:
        assert OPERATION_IDS == EXPECTED_OPERATIONS
        assert len(OPERATION_IDS) == 33
        assert set(OPERATION_REGISTRY) == set(EXPECTED_OPERATIONS)

    def test_exactly_thirty_two_operations_contact_shopify(self) -> None:
        assert len(NETWORK_OPERATION_IDS) == 32
        assert "validate_connection_settings" not in NETWORK_OPERATION_IDS

    def test_exactly_twelve_operations_mutate(self) -> None:
        assert ACTION_OPERATION_IDS == EXPECTED_ACTIONS
        assert len(ACTION_OPERATION_IDS) == 12

    @pytest.mark.parametrize(
        "operation_id",
        [
            "execute_graphql",
            "graphql",
            "node",
            "nodes",
            "productCreate",
            "inventoryAdjustQuantities",
            "inventoryActivate",
            "inventoryDeactivate",
            "inventoryBulkToggleActivation",
            "delete_inventory_item",
            "TEST_CONNECTION",
            "",
        ],
    )
    def test_an_operation_that_is_not_declared_is_refused(self, operation_id: str) -> None:
        response = dispatch_runtime(
            _host({"mode": "action", "action": {"action_id": operation_id, "input": {}}})
        )

        assert response["error_code"] == errors.UNSUPPORTED_OPERATION

    def test_an_unknown_operation_is_refused_before_any_transport_is_built(self) -> None:
        def explode(connection: object) -> object:  # pragma: no cover - must never run
            raise AssertionError("a transport was constructed for an unknown operation")

        response = handle_runtime(connection_payload("execute_graphql"), transport_factory=explode)

        assert response["error_code"] == errors.UNSUPPORTED_OPERATION

    def test_an_unknown_operation_is_refused_before_the_connection_is_read(self) -> None:
        payload = connection_payload("execute_graphql")
        payload["action"]["target"]["connection"]["config"] = {"shop_domain": "!! invalid !!"}

        response = dispatch_runtime(payload)

        # The domain would fail validation too; the point is which check runs first.
        assert response["error_code"] == errors.UNSUPPORTED_OPERATION


class TestTheActionEnvelopeIsExact:
    def test_the_keys_the_platform_actually_sends_are_accepted(self, http: FakeHttp) -> None:
        from runtime.transport import ShopifyGraphQLTransport

        http.queue(graphql_response({"shop": {"id": "gid://shopify/Shop/1"}}))
        payload = connection_payload(
            "get_shop",
            action_extra={
                "operation_id": "get_shop",
                "page_id": "inventory-api",
                "component_id": "operations",
                "context": {"project_id": "p1"},
            },
        )

        response = handle_runtime(
            payload, transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http)
        )

        assert response["ok"] is True

    def test_a_key_the_platform_does_not_send_is_refused(self) -> None:
        payload = connection_payload("get_shop", action_extra={"runtime_context": {}})

        response = handle_runtime(payload, transport_factory=lambda c: None)

        assert response["error_code"] == errors.INVALID_PAYLOAD

    def test_runtime_context_stays_a_top_level_host_field(self, http: FakeHttp) -> None:
        """It sits beside ``action``, not inside it, and is read from there."""
        from conftest import ITEM_A, LOCATION_A

        payload = connection_payload(
            "set_inventory_quantities",
            {
                "quantities": [
                    {
                        "inventory_item_id": ITEM_A,
                        "location_id": LOCATION_A,
                        "quantity": 1,
                        "change_from_quantity": None,
                    }
                ]
            },
            runtime_context={"test_mode": True, "external_effect_id": EXTERNAL_EFFECT_ID},
        )

        assert "runtime_context" in payload
        assert "runtime_context" not in payload["action"]

        response = handle_runtime(payload, transport_factory=lambda c: None)

        assert response["external_effect_status"] == "suppressed"
        assert http.requests == []

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"mode": "invoke", "action": {"action_id": "get_shop"}},
            {"mode": "action"},
            {"mode": "action", "action": []},
            {"mode": "action", "action": {"input": {}}},
            {"mode": "action", "action": {"action_id": "   "}},
        ],
    )
    def test_a_malformed_envelope_is_refused(self, payload: dict) -> None:
        response = handle_runtime(_host(payload), transport_factory=lambda c: None)

        assert response["ok"] is False
        assert response["error_code"] in {errors.INVALID_PAYLOAD, errors.UNSUPPORTED_OPERATION}


class TestTheResponseEnvelope:
    def test_a_success_carries_every_declared_key(self, http: FakeHttp) -> None:
        response = dispatch_runtime(
            _host(
                {
                    "mode": "action",
                    "action": {
                        "action_id": "validate_connection_settings",
                        "input": {"shop_domain": "acme"},
                    },
                }
            )
        )

        assert set(response) == {"ok", "result", "error_code", "error", "errors"}
        assert response["ok"] is True
        assert response["error_code"] is None
        assert response["error"] is None
        assert response["errors"] == []

    def test_a_failure_carries_the_same_keys_and_one_error(self) -> None:
        response = dispatch_runtime(
            _host({"mode": "action", "action": {"action_id": "nope", "input": {}}})
        )

        assert set(response) == {"ok", "result", "error_code", "error", "errors"}
        assert response["ok"] is False
        assert response["result"] == {}
        assert response["errors"] == [
            {"code": response["error_code"], "message": response["error"]}
        ]

    def test_every_error_code_a_failure_reports_is_in_the_safe_vocabulary(self) -> None:
        response = dispatch_runtime(_host({"mode": "action", "action": {"action_id": "x"}}))

        assert response["error_code"] in errors.SAFE_ERROR_CODES

    def test_an_unexpected_internal_failure_is_reduced_to_a_safe_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from runtime import operations as operations_module

        def explode(*args: object, **kwargs: object) -> None:
            raise RuntimeError("shpat_secret_leaked_in_a_traceback")

        monkeypatch.setattr(operations_module.validation, "validated_input", explode)

        response = handle_runtime(connection_payload("get_shop"), transport_factory=lambda c: None)

        assert response["error_code"] == errors.INTERNAL_ERROR
        assert "shpat_secret" not in str(response)


def _route_with(
    monkeypatch: pytest.MonkeyPatch,
    **fakes: Any,
) -> None:
    """Let ``dispatch_runtime`` reach the real runtime with fake I/O."""
    import dispatcher

    monkeypatch.setattr(
        dispatcher, "handle_runtime", lambda payload: handle_runtime(payload, **fakes)
    )


class TestTheFinalExecutionScope:
    """Every execution-scope owner reaches the operations and their artifacts."""

    @pytest.mark.parametrize(
        "scope",
        [ROOT_STEP_SCOPE, GROUP_STEP_SCOPE, FOR_EACH_STEP_SCOPE],
        ids=["root", "group", "for_each"],
    )
    def test_the_catalog_export_writes_its_artifact_for_every_owner(
        self, http: FakeHttp, monkeypatch: pytest.MonkeyPatch, scope: dict[str, Any]
    ) -> None:
        http.queue(graphql_response({"products": connection([product_node()], has_next=False)}))
        written: list[dict[str, Any]] = []

        def artifact_writer(payload: Any, chunks: Any, **kwargs: Any) -> dict[str, Any]:
            body = b"".join(chunks)
            written.append({"scope": dict(payload["runtime_context"]), "body": body})
            return {
                "artifact_handle": "artifact:art_export",
                "size_bytes": len(body),
                "sha256": "a" * 64,
            }

        _route_with(
            monkeypatch,
            transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
            artifact_writer=artifact_writer,
        )

        response = dispatch_runtime(connection_payload("export_products", {}, scope=scope))

        assert response["ok"] is True
        assert response["result"]["artifact_handle"] == "artifact:art_export"
        assert response["result"]["item_count"] == 1
        assert len(written) == 1
        assert {key: written[0]["scope"][key] for key in scope} == scope
        assert b"gid://shopify/Product/3001" in written[0]["body"]

    @pytest.mark.parametrize(
        "scope",
        [ROOT_STEP_SCOPE, GROUP_STEP_SCOPE, FOR_EACH_STEP_SCOPE],
        ids=["root", "group", "for_each"],
    )
    def test_the_bulk_import_reads_its_artifact_for_every_owner(
        self, http: FakeHttp, monkeypatch: pytest.MonkeyPatch, scope: dict[str, Any]
    ) -> None:
        from test_bulk_products import BULK_ID, accepted, staged

        storage = FakeHttp()
        storage.queue(FakeResponse(201, b""))
        http.queue(staged(), accepted())
        reads: list[str] = []

        def artifact_reader(payload: Any, **kwargs: Any) -> bytes:
            reads.append(payload["runtime_context"]["step_execution_id"])
            return b'{"title": "Boots", "handle": "boots"}\n'

        _route_with(
            monkeypatch,
            transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
            artifact_reader=artifact_reader,
            storage_opener=storage,
        )
        payload = connection_payload(
            "create_products_bulk",
            {"artifact_handle": "artifact:products_jsonl"},
            runtime_context={"external_effect_id": EXTERNAL_EFFECT_ID},
            scope=scope,
        )

        response = dispatch_runtime(payload)

        assert response["ok"] is True
        assert response["result"]["bulk_operation"]["id"] == BULK_ID
        assert reads == [scope["step_execution_id"]]
        assert len(storage.requests) == 1
        assert b'"handle":"boots"' in storage.last["body"]


class TestAForeignOrIncompleteEnvelopeIsRefused:
    """Refused before the connection, an artifact or Shopify is touched."""

    @pytest.mark.parametrize(
        ("contract_version", "scope", "reason"),
        [
            ("extension_host_v1", FOR_EACH_STEP_SCOPE, "Unsupported host contract"),
            ("", FOR_EACH_STEP_SCOPE, "Unsupported host contract"),
            (
                HOST_CONTRACT_VERSION,
                {k: v for k, v in FOR_EACH_STEP_SCOPE.items() if k != "for_each_id"},
                "misses execution scope",
            ),
            (
                HOST_CONTRACT_VERSION,
                {**FOR_EACH_STEP_SCOPE, "group_id": "prepare_catalog"},
                "both a Group and a For each",
            ),
            (
                HOST_CONTRACT_VERSION,
                {**ROOT_STEP_SCOPE, "step_execution_id": None},
                "without its logical execution",
            ),
        ],
        ids=["v1", "no_contract", "missing_key", "two_owners", "step_without_execution"],
    )
    def test_nothing_is_read_sent_or_written(
        self,
        http: FakeHttp,
        monkeypatch: pytest.MonkeyPatch,
        contract_version: str,
        scope: dict[str, Any],
        reason: str,
    ) -> None:
        touched: list[str] = []

        def forbidden(name: str) -> Any:
            def call(*args: Any, **kwargs: Any) -> Any:
                touched.append(name)
                raise AssertionError(f"{name} ran for a refused envelope")

            return call

        _route_with(
            monkeypatch,
            transport_factory=forbidden("transport"),
            artifact_reader=forbidden("artifact_reader"),
            artifact_writer=forbidden("artifact_writer"),
            storage_opener=forbidden("storage"),
        )
        payload = connection_payload(
            "create_products_bulk",
            {"artifact_handle": "artifact:products_jsonl"},
            runtime_context={"external_effect_id": EXTERNAL_EFFECT_ID},
        )
        payload["contract_version"] = contract_version
        payload["runtime_context"] = {**scope, "external_effect_id": EXTERNAL_EFFECT_ID}

        response = dispatch_runtime(payload)

        assert response["ok"] is False
        assert response["error_code"] == errors.INVALID_HOST_ENVELOPE
        assert reason in response["error"]
        assert response["definitely_no_external_effect"] is True
        assert touched == []
        assert http.requests == []
