"""Canonical per-operation Admin API scope requirements.

Each registry row owns one ``required_oauth_scopes`` tuple. Every listed scope
is required; connection setup requests the union and rejects incomplete grants.
``test_connection`` uses the same tuples to diagnose stale grants.

**Eligibility is not permission.** A satisfied policy means the granted Admin
API scopes allow the call to be attempted. Shopify still decides: staff
permissions, shop state, whether a fulfillment order belongs to this app, and
the state of the resource itself all outrank anything computed here. Nothing in
this module is consulted to skip a request or to predict its outcome — it exists
so an operator can see, before building a workflow, which operations their token
could not possibly satisfy.
"""

from __future__ import annotations

from collections.abc import Sequence

WRITE_INVENTORY = "write_inventory"
READ_LOCATIONS = "read_locations"
WRITE_PRODUCTS = "write_products"
WRITE_FILES = "write_files"
WRITE_ORDERS = "write_orders"

WRITE_ASSIGNED_FULFILLMENT_ORDERS = "write_assigned_fulfillment_orders"
WRITE_MERCHANT_MANAGED_FULFILLMENT_ORDERS = "write_merchant_managed_fulfillment_orders"
WRITE_THIRD_PARTY_FULFILLMENT_ORDERS = "write_third_party_fulfillment_orders"

FULFILLMENT_ORDER_WRITE_SCOPES: tuple[str, ...] = (
    WRITE_ASSIGNED_FULFILLMENT_ORDERS,
    WRITE_MERCHANT_MANAGED_FULFILLMENT_ORDERS,
    WRITE_THIRD_PARTY_FULFILLMENT_ORDERS,
)


def capability_row(
    operation_id: str, required_scopes: Sequence[str], granted: Sequence[str]
) -> dict[str, object]:
    """One `test_connection` capability entry for one operation."""
    required = tuple(required_scopes)
    held = set(granted)
    missing = [scope for scope in required if scope not in held]
    return {
        "operation_id": operation_id,
        "scope_eligible": not missing,
        "required_oauth_scopes": list(required),
        "missing_required_oauth_scopes": missing,
    }


__all__ = [
    "FULFILLMENT_ORDER_WRITE_SCOPES",
    "READ_LOCATIONS",
    "WRITE_INVENTORY",
    "WRITE_ORDERS",
    "WRITE_PRODUCTS",
    "capability_row",
]
