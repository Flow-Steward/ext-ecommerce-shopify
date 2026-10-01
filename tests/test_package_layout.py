"""Bundle layout, the subprocess entrypoint, and the health command."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml
from health import check_health
from runtime.catalog import NETWORK_OPERATION_IDS, OPERATIONS
from runtime.documents import API_VERSION

BUNDLE_ROOT = Path(__file__).resolve().parents[1]


def _run_entrypoint(payload: object) -> tuple[int, dict]:
    process = subprocess.run(
        [sys.executable, "main.py"],
        cwd=str(BUNDLE_ROOT),
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        check=False,
    )
    return process.returncode, json.loads(process.stdout.decode("utf-8"))


def test_every_task_owned_file_lives_inside_this_bundle() -> None:
    expected_top_level = {
        "README.md",
        "CHANGELOG.md",
        "__init__.py",
        "contracts",
        "dev-wheels",
        "dispatcher.py",
        "health.py",
        "main.py",
        "requirements-dev.txt",
        "runtime",
        "tests",
        "ui",
    }
    # ``logs`` is the repository-wide, git-ignored tool cache: running ruff or
    # mypy from this directory creates it. It is not part of the bundle.
    tooling = {"__pycache__", "logs"}
    actual = {
        entry.name
        for entry in BUNDLE_ROOT.iterdir()
        if not entry.name.startswith(".") and entry.name not in tooling
    }
    assert actual - {"extension.yaml"} == expected_top_level
    assert (BUNDLE_ROOT / "extension.yaml").is_file()


def test_the_health_command_reports_the_declared_surface() -> None:
    health = check_health()

    assert health["extension_id"] == "flowsteward.shopify"
    assert health["ok"] is True
    assert health["status"] == "healthy"
    assert health["api_version"] == API_VERSION
    assert health["declared_operations"] == len(OPERATIONS) == 33
    assert health["network_operations"] == len(NETWORK_OPERATION_IDS) == 32


def test_the_health_command_runs_as_a_subprocess() -> None:
    process = subprocess.run(
        [sys.executable, "health.py"],
        cwd=str(BUNDLE_ROOT),
        capture_output=True,
        check=True,
    )

    assert json.loads(process.stdout.decode("utf-8"))["ok"] is True


def test_the_entrypoint_refuses_an_unknown_operation() -> None:
    code, response = _run_entrypoint(
        {"mode": "action", "action": {"action_id": "execute_graphql", "input": {}}}
    )

    assert code == 2
    assert response["ok"] is False
    assert response["error_code"] == "unsupported_operation"


def test_the_entrypoint_reports_success_with_exit_code_zero() -> None:
    code, response = _run_entrypoint(
        {
            "mode": "action",
            "action": {
                "action_id": "validate_connection_settings",
                "input": {"shop_domain": "Example-Store"},
            },
        }
    )

    assert code == 0
    assert response["ok"] is True
    assert response["result"]["normalized_shop_domain"] == "example-store.myshopify.com"


def test_the_entrypoint_refuses_a_non_json_request() -> None:
    process = subprocess.run(
        [sys.executable, "main.py"],
        cwd=str(BUNDLE_ROOT),
        input=b"{not json",
        capture_output=True,
        check=False,
    )
    response = json.loads(process.stdout.decode("utf-8"))

    assert process.returncode == 2
    assert response["ok"] is False
    assert response["error_code"] == "invalid_payload"


def test_the_entrypoint_refuses_an_oversized_request() -> None:
    from main import MAX_INPUT_BYTES

    process = subprocess.run(
        [sys.executable, "main.py"],
        cwd=str(BUNDLE_ROOT),
        input=b"[" + b"0," * MAX_INPUT_BYTES,
        capture_output=True,
        check=False,
    )
    response = json.loads(process.stdout.decode("utf-8"))

    assert process.returncode == 2
    assert response["error_code"] == "invalid_payload"


def test_the_entrypoint_and_health_commands_match_the_manifest() -> None:
    manifest = yaml.safe_load((BUNDLE_ROOT / "extension.yaml").read_text())

    assert manifest["entrypoint"]["command"] == ["python3", "main.py"]
    assert manifest["health"]["command"] == ["python3", "health.py"]
    assert manifest["python_requirements"] == []


def test_no_shipped_file_is_missing_from_the_bundle() -> None:
    for relative in (
        "contracts/connection_types.yaml",
        "contracts/operation_manifest.yaml",
        "contracts/step_ui_manifest.yaml",
        "contracts/artifact_policies.yaml",
        "runtime/catalog.py",
        "runtime/documents.py",
        "tests/reference/build_contracts.py",
        "tests/reference/build_ui_pages.py",
        "tests/reference/refresh_contracts.py",
        "ui/ui_manifest.yaml",
        "ui/actions/actions.yaml",
        "ui/pages/setup-guide.yaml",
        "ui/pages/connection.yaml",
        "ui/pages/inventory-api.yaml",
        "ui/pages/changelog.yaml",
    ):
        assert (BUNDLE_ROOT / relative).is_file(), relative
