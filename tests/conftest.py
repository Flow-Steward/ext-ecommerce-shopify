from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
if str(BUNDLE_ROOT) not in sys.path:
    sys.path.insert(0, str(BUNDLE_ROOT))
# The offline generators live beside the tests that cover them.
GENERATOR_ROOT = BUNDLE_ROOT / "tests" / "reference"
if str(GENERATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(GENERATOR_ROOT))

from runtime import connection as connection_module  # noqa: E402
from runtime.transport import ShopifyGraphQLTransport  # noqa: E402

SHOP_DOMAIN = "flow-steward-test.myshopify.com"
CONNECTION_ID = "conn-1"
ACCESS_TOKEN = "shpat_fixture_token_1"  # pragma: allowlist secret
EXTERNAL_EFFECT_ID = "6a3f1c2e-7b45-4d0a-9c11-2f8e5b7a0d31"

PRODUCT_A = "gid://shopify/Product/3001"
PRODUCT_B = "gid://shopify/Product/3002"
VARIANT_A = "gid://shopify/ProductVariant/4001"
VARIANT_B = "gid://shopify/ProductVariant/4002"
#: A real Shopify taxonomy id. They are handle-shaped, never numeric,
#: and a numeric fixture here hid the fact that `category_id` did not work.
CATEGORY_A = "gid://shopify/TaxonomyCategory/hb-1-9-6"
MEDIA_A = "gid://shopify/MediaImage/6001"
ORDER_A = "gid://shopify/Order/7001"
FULFILLMENT_ORDER_A = "gid://shopify/FulfillmentOrder/8001"
FULFILLMENT_ORDER_LINE_A = "gid://shopify/FulfillmentOrderLineItem/8101"
FULFILLMENT_ORDER_LINE_B = "gid://shopify/FulfillmentOrderLineItem/8102"
FULFILLMENT_A = "gid://shopify/Fulfillment/9001"

ITEM_A = "gid://shopify/InventoryItem/1001"
ITEM_B = "gid://shopify/InventoryItem/1002"
LOCATION_A = "gid://shopify/Location/2001"
LOCATION_B = "gid://shopify/Location/2002"


class FakeResponse:
    """A deterministic stand-in for one urllib response."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.code = status
        self._buffer = body

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk, self._buffer = self._buffer, b""
            return chunk
        chunk, self._buffer = self._buffer[:size], self._buffer[size:]
        return chunk

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeHttp:
    """Records every outbound request and replays scripted responses."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses: list[Any] = []
        self.default: Any = FakeResponse(200, b'{"data":{}}')

    def queue(self, *responses: Any) -> None:
        self.responses.extend(responses)

    def __call__(self, request: Any, *, timeout_seconds: float, purpose: str) -> Any:
        data = request.data
        if data is not None and not isinstance(data, (bytes, bytearray)):
            data = b"".join(bytes(chunk) for chunk in data)
        self.requests.append(
            {
                "method": request.get_method(),
                "url": request.full_url,
                "headers": {key.lower(): value for key, value in request.header_items()},
                "body": bytes(data) if data is not None else None,
                "timeout_seconds": timeout_seconds,
                "purpose": purpose,
            }
        )
        response = self.responses.pop(0) if self.responses else self.default
        if isinstance(response, BaseException):
            raise response
        return response

    @property
    def last(self) -> dict[str, Any]:
        return self.requests[-1]

    def json_body(self, index: int = -1) -> Any:
        raw = self.requests[index]["body"]
        return json.loads(raw.decode("utf-8")) if raw else None

    def document(self, index: int = -1) -> str:
        return str(self.json_body(index)["query"])

    def variables(self, index: int = -1) -> dict[str, Any]:
        return dict(self.json_body(index)["variables"])


def graphql_response(data: Any, *, status: int = 200, errors: Any = None) -> FakeResponse:
    payload: dict[str, Any] = {}
    if data is not None:
        payload["data"] = data
    if errors is not None:
        payload["errors"] = errors
    return FakeResponse(status, json.dumps(payload).encode("utf-8"))


@pytest.fixture(autouse=True)
def no_test_may_reach_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing in this suite resolves a name, so nothing can reach a real store.

    Every test drives the transport through a scripted opener. This guard is
    what catches the one that forgets: without it, a missing ``opener`` would
    quietly fall back to the real SDK and try to contact whatever domain the
    fixture happened to name.
    """
    import socket

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a test tried to resolve a hostname; the suite is offline")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture(autouse=True)
def offline_host_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite offline without weakening the shipped host policy.

    The runtime always calls the SDK guard; only the test double is swapped, and
    ``test_security_boundaries.py`` exercises the real guard against a loopback
    address, which needs no name resolution.
    """
    monkeypatch.setattr(
        connection_module, "assert_safe_remote_http_url", lambda url, purpose="": url
    )


@pytest.fixture
def http() -> FakeHttp:
    return FakeHttp()


@pytest.fixture
def transport_factory(http: FakeHttp):
    def factory(connection: Any) -> ShopifyGraphQLTransport:
        return ShopifyGraphQLTransport(connection, opener=http)

    return factory


def connection_payload(
    operation_id: str,
    operation_input: dict[str, Any] | None = None,
    *,
    shop_domain: str = SHOP_DOMAIN,
    access_token: str = ACCESS_TOKEN,
    connection_id: str = CONNECTION_ID,
    connection_ref: str | None = None,
    connection_type_id: str = "shopify_admin",
    runtime_context: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    secrets: dict[str, Any] | None = None,
    action_extra: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action_input: dict[str, Any] = {
        "connection_ref": connection_id if connection_ref is None else connection_ref,
        **(operation_input or {}),
    }
    payload: dict[str, Any] = {
        "mode": "action",
        "action": {
            "action_id": operation_id,
            "input": action_input,
            "target": {
                "connection": {
                    "connection_id": connection_id,
                    "connection_type_id": connection_type_id,
                    # The platform projects an OAuth connection as the verified
                    # subject plus the hydrated token, so the fixture is shaped
                    # the same way the host actually hydrates one.
                    "config": (
                        {"oauth": {"subject": shop_domain, "lifecycle_status": "connected"}}
                        if config is None
                        else config
                    ),
                    "secrets": ({"access_token": access_token} if secrets is None else secrets),
                }
            },
            **(action_extra or {}),
        },
    }
    if runtime_context is not None:
        payload["runtime_context"] = runtime_context
    if extra:
        payload.update(extra)
    return payload


def set_quantities_payload(
    quantities: list[dict[str, Any]],
    *,
    external_effect_id: str | None = EXTERNAL_EFFECT_ID,
    test_mode: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    runtime_context: dict[str, Any] = {"test_mode": test_mode}
    if external_effect_id is not None:
        runtime_context["external_effect_id"] = external_effect_id
    return connection_payload(
        "set_inventory_quantities",
        {"quantities": quantities},
        runtime_context=runtime_context,
        **kwargs,
    )


def action_payload(
    operation_id: str,
    operation_input: dict[str, Any],
    *,
    external_effect_id: str | None = EXTERNAL_EFFECT_ID,
    test_mode: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """One action invocation, with the runtime context the host supplies."""
    runtime_context: dict[str, Any] = {"test_mode": test_mode}
    if external_effect_id is not None:
        runtime_context["external_effect_id"] = external_effect_id
    return connection_payload(
        operation_id, operation_input, runtime_context=runtime_context, **kwargs
    )


def run_operation(
    operation_id: str,
    operation_input: dict[str, Any],
    http: FakeHttp,
    **kwargs: Any,
) -> dict[str, Any]:
    """Drive one source operation through the real runtime and fake transport."""
    from runtime.operations import handle_runtime
    from runtime.transport import ShopifyGraphQLTransport

    return handle_runtime(
        connection_payload(operation_id, operation_input, **kwargs),
        transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
    )


def run_action(
    operation_id: str,
    operation_input: dict[str, Any],
    http: FakeHttp,
    **kwargs: Any,
) -> dict[str, Any]:
    """Drive one action through the real runtime and fake transport."""
    from runtime.operations import handle_runtime
    from runtime.transport import ShopifyGraphQLTransport

    return handle_runtime(
        action_payload(operation_id, operation_input, **kwargs),
        transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
    )


def product_node(identifier: str = PRODUCT_A, **overrides: Any) -> dict[str, Any]:
    node = {
        "id": identifier,
        "title": "Boots",
        "handle": "boots",
        "descriptionHtml": "<p>Boots</p>",
        "vendor": "Acme",
        "productType": "Footwear",
        "status": "DRAFT",
        "tags": ["new"],
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z",
        "category": {"id": CATEGORY_A},
        "seo": {"title": "Boots", "description": "Good boots"},
        "options": [{"id": "gid://shopify/ProductOption/1", "name": "Size", "position": 1}],
    }
    node.update(overrides)
    return node


def variant_node(identifier: str = VARIANT_A, **overrides: Any) -> dict[str, Any]:
    node = {
        "id": identifier,
        "title": "42",
        "barcode": "0001",
        "price": "19.99",
        "compareAtPrice": "24.99",
        "inventoryPolicy": "DENY",
        "taxable": True,
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z",
        "product": {"id": PRODUCT_A},
        "selectedOptions": [{"name": "Size", "value": "42"}],
        "inventoryItem": {
            "id": ITEM_A,
            "sku": "SKU-1",
            "tracked": True,
            "requiresShipping": True,
        },
    }
    node.update(overrides)
    return node


def metafield_node(
    *, namespace: str = "custom", key: str = "care", owner: dict[str, Any] | None = None
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": "gid://shopify/Metafield/1",
        "namespace": namespace,
        "key": key,
        "type": "single_line_text_field",
        "value": "hand wash",
        "compareDigest": "digest-2",
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z",
    }
    if owner is not None:
        node["owner"] = owner
    return node


def order_node(identifier: str = ORDER_A, **overrides: Any) -> dict[str, Any]:
    node = {
        "id": identifier,
        "name": "#1001",
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z",
        "processedAt": "2026-08-01T00:00:00Z",
        "cancelledAt": None,
        "closedAt": None,
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "UNFULFILLED",
        "currencyCode": "EUR",
        "tags": ["priority"],
        "note": "leave at door",
        "poNumber": "PO-7",
        "customAttributes": [{"key": "gift", "value": "yes"}],
        "totalPriceSet": {"shopMoney": {"amount": "19.99", "currencyCode": "EUR"}},
        "subtotalPriceSet": {"shopMoney": {"amount": "16.52", "currencyCode": "EUR"}},
        "totalTaxSet": {"shopMoney": {"amount": "3.47", "currencyCode": "EUR"}},
        "totalShippingPriceSet": {"shopMoney": {"amount": "0.00", "currencyCode": "EUR"}},
        "totalDiscountsSet": {"shopMoney": {"amount": "0.00", "currencyCode": "EUR"}},
    }
    node.update(overrides)
    return node


def fulfillment_node(identifier: str = FULFILLMENT_A, **overrides: Any) -> dict[str, Any]:
    node = {
        "id": identifier,
        "status": "SUCCESS",
        "createdAt": "2026-08-03T00:00:00Z",
        "updatedAt": "2026-08-03T00:00:00Z",
        "trackingInfo": [{"company": "DHL", "number": "TRK1", "url": "https://track.test/1"}],
    }
    node.update(overrides)
    return node


def connection(nodes: list[dict[str, Any]], *, has_next: bool = False, cursor=None):
    """One GraphQL connection payload."""
    return {"pageInfo": {"hasNextPage": has_next, "endCursor": cursor}, "nodes": nodes}


def quantity(
    *,
    inventory_item_id: str = ITEM_A,
    location_id: str = LOCATION_A,
    value: int = 7,
    change_from_quantity: int | None = None,
) -> dict[str, Any]:
    return {
        "inventory_item_id": inventory_item_id,
        "location_id": location_id,
        "quantity": value,
        "change_from_quantity": change_from_quantity,
    }


def adjustment_group_response(changes: list[dict[str, Any]] | None = None) -> FakeResponse:
    return graphql_response(
        {
            "inventorySetQuantities": {
                "inventoryAdjustmentGroup": {
                    "id": "gid://shopify/InventoryAdjustmentGroup/3001",
                    "createdAt": "2026-08-28T09:00:00Z",
                    "reason": "Inventory correction",
                    "referenceDocumentUri": (
                        f"gid://flow-steward/ExternalEffect/{EXTERNAL_EFFECT_ID}"
                    ),
                    "changes": changes
                    if changes is not None
                    else [
                        {
                            "name": "available",
                            "delta": 2,
                            "quantityAfterChange": 7,
                            "item": {"id": ITEM_A},
                            "location": {"id": LOCATION_A},
                        }
                    ],
                },
                "userErrors": [],
            }
        }
    )


def inventory_item_node(
    identifier: str = ITEM_A, *, sku: str | None = "SKU-1", tracked: bool = True
) -> dict[str, Any]:
    return {
        "__typename": "InventoryItem",
        "id": identifier,
        "sku": sku,
        "tracked": tracked,
        "requiresShipping": True,
        "updatedAt": "2026-08-27T12:00:00Z",
    }


def inventory_level(
    *,
    location_id: str = LOCATION_A,
    is_active: bool = True,
    available: int = 4,
    on_hand: int = 6,
) -> dict[str, Any]:
    return {
        "id": "gid://shopify/InventoryLevel/9001?inventory_item_id=1001",
        "location": {"id": location_id, "isActive": is_active},
        "quantities": [
            {"name": "available", "quantity": available},
            {"name": "on_hand", "quantity": on_hand},
        ],
    }
