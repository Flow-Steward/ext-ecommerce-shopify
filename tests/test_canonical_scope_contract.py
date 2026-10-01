from __future__ import annotations

from pathlib import Path

import yaml
from runtime.catalog import OPERATIONS_BY_ID

ROOT = Path(__file__).resolve().parents[1]


def _manifest() -> dict:
    return yaml.safe_load((ROOT / "contracts" / "operation_manifest.yaml").read_text())


def test_scope_requirements_have_one_canonical_operation_contract() -> None:
    manifest = _manifest()
    rows = manifest["operations"]
    connection_manifest = yaml.safe_load((ROOT / "contracts" / "connection_types.yaml").read_text())
    fresh_grant = set(connection_manifest["connection_types"][0]["auth"]["scopes"]["required"])

    assert fresh_grant == {
        "read_locations",
        "write_assigned_fulfillment_orders",
        "write_files",
        "write_inventory",
        "write_merchant_managed_fulfillment_orders",
        "write_orders",
        "write_products",
        "write_third_party_fulfillment_orders",
    }

    for row in rows:
        operation_id = row["operation_id"]
        runtime_row = OPERATIONS_BY_ID[operation_id]
        assert "scope_policy" not in row
        assert not hasattr(runtime_row, "scope_policy")
        assert row.get("required_oauth_scopes", []) == list(runtime_row.required_oauth_scopes)
        assert set(row.get("required_oauth_scopes", [])) <= fresh_grant


def test_bundle_publishes_no_legacy_scope_dialect_or_partial_grant_claims() -> None:
    forbidden = (
        "any_of_groups",
        "unsatisfied_any_of_groups",
        "missing_all_of",
        "partial-scope",
        "satisfies some of them is a working connection",
        "policies are expressed as any-of groups",
    )
    current_contract_files = [
        ROOT / "runtime" / "catalog.py",
        ROOT / "runtime" / "scopes.py",
        ROOT / "contracts" / "operation_manifest.yaml",
        ROOT / "README.md",
        ROOT / "ui" / "pages" / "inventory-api.yaml",
        ROOT / "ui" / "pages" / "setup-guide.yaml",
    ]

    for path in current_contract_files:
        text = path.read_text(encoding="utf-8").lower()
        for phrase in forbidden:
            assert phrase not in text, f"{path.name} still publishes {phrase!r}"
