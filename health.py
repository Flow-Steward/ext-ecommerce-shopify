"""Health command for the Shopify extension."""

from __future__ import annotations

import json


def check_health() -> dict[str, object]:
    from runtime.catalog import NETWORK_OPERATION_IDS, OPERATIONS
    from runtime.documents import API_VERSION

    return {
        "extension_id": "flowsteward.shopify",
        "ok": True,
        "status": "healthy",
        "api_version": API_VERSION,
        "declared_operations": len(OPERATIONS),
        "network_operations": len(NETWORK_OPERATION_IDS),
    }


if __name__ == "__main__":
    print(json.dumps(check_health(), separators=(",", ":"), sort_keys=True))
