"""The boundaries that must hold whatever else changes.

What the bundle may import, what may reach the network, what may appear in
output, and what may survive an invocation.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from conftest import (
    ACCESS_TOKEN,
    ITEM_A,
    LOCATION_A,
    FakeHttp,
    adjustment_group_response,
    connection_payload,
    graphql_response,
    quantity,
    set_quantities_payload,
)
from runtime import documents
from runtime.operations import handle_runtime

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = sorted(
    [
        BUNDLE_ROOT / "main.py",
        BUNDLE_ROOT / "dispatcher.py",
        BUNDLE_ROOT / "health.py",
        *(BUNDLE_ROOT / "runtime").glob("*.py"),
    ]
)
ALL_PYTHON_FILES = sorted(
    path
    for path in BUNDLE_ROOT.rglob("*.py")
    if "__pycache__" not in path.parts and "dev-wheels" not in path.parts
)

#: Anything that would open a socket, or reach around the public SDK.
FORBIDDEN_MODULES = {
    "requests",
    "httpx",
    "aiohttp",
    "urllib3",
    "shopify",
    "ShopifyAPI",
    "shopifyapi",
    "shopifyapp",
    "pyactiveresource",
    "socket",
    "ssl",
    "http.client",
    "urllib.request",
}

#: Only these names may be imported from the public SDK namespace.
ALLOWED_SDK_NAMES = {
    "PinnedPeerError",
    "assert_safe_remote_http_url",
    "open_pinned_url",
    "parse_retry_after",
    "write_artifact_stream",
    "read_artifact_bytes",
}

#: The public SDK is the one ``flowsteward_*`` import the bundle may make.
SDK_MODULE = "flowsteward_extension_sdk"

#: Identifiers that would open a connection, or touch the filesystem. Matched
#: against names actually used in code, so a docstring may still discuss them.
FORBIDDEN_CALLS = {
    "urlopen",
    "build_opener",
    "install_opener",
    "open",
    "write_text",
    "write_bytes",
    "mkdir",
    "makedirs",
    "mkstemp",
    "mkdtemp",
    "NamedTemporaryFile",
    "TemporaryFile",
    "remove",
    "unlink",
    "rmtree",
    "socket",
    "create_connection",
}


def _imports(path: Path) -> list[tuple[str, tuple[str, ...]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, ()))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.module, tuple(alias.name for alias in node.names)))
    return found


def _identifiers(path: Path) -> set[str]:
    """Every identifier the module actually uses, ignoring strings and comments."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
    return used


class TestWhatTheBundleMayImport:
    @pytest.mark.parametrize("path", ALL_PYTHON_FILES, ids=lambda p: p.name)
    def test_no_file_reaches_into_core(self, path: Path) -> None:
        for module, _names in _imports(path):
            assert not module.startswith("core"), f"{path.name} imports {module}"

    @pytest.mark.parametrize("path", ALL_PYTHON_FILES, ids=lambda p: p.name)
    def test_no_file_reaches_into_another_extension(self, path: Path) -> None:
        for module, _names in _imports(path):
            assert not module.startswith("extensions"), f"{path.name} imports {module}"
            if module.startswith("flowsteward_"):
                assert module == SDK_MODULE, f"{path.name} imports {module}"

    @pytest.mark.parametrize("path", RUNTIME_FILES, ids=lambda p: p.name)
    def test_no_runtime_file_uses_a_forbidden_transport(self, path: Path) -> None:
        for module, names in _imports(path):
            if module == "urllib.request":
                # ``Request`` describes a request; the SDK is what opens it.
                assert set(names) == {"Request"}, f"{path.name} imports {names}"
                continue
            assert module not in FORBIDDEN_MODULES, f"{path.name} imports {module}"
            assert module.split(".")[0] not in FORBIDDEN_MODULES, f"{path.name} imports {module}"

    @pytest.mark.parametrize("path", RUNTIME_FILES, ids=lambda p: p.name)
    def test_only_the_public_sdk_surface_is_imported(self, path: Path) -> None:
        for module, names in _imports(path):
            if not module.startswith("flowsteward_extension_sdk"):
                continue
            assert module == "flowsteward_extension_sdk", f"{path.name} imports {module}"
            assert set(names) <= ALLOWED_SDK_NAMES, f"{path.name} imports {names}"

    def test_the_only_thing_that_opens_a_connection_is_the_sdk(self) -> None:
        """``Request`` is a value object; ``open_pinned_url`` is what opens it."""
        transport = BUNDLE_ROOT / "runtime" / "transport.py"

        assert ("urllib.request", ("Request",)) in _imports(transport)
        assert (
            SDK_MODULE,
            ("PinnedPeerError", "open_pinned_url", "parse_retry_after"),
        ) in _imports(transport)
        assert "open_pinned_url" in _identifiers(transport)
        assert not FORBIDDEN_CALLS & _identifiers(transport)

    @pytest.mark.parametrize("path", RUNTIME_FILES, ids=lambda p: p.name)
    def test_nothing_in_the_runtime_touches_the_filesystem(self, path: Path) -> None:
        assert not FORBIDDEN_CALLS & _identifiers(path), path.name

    @pytest.mark.parametrize("path", RUNTIME_FILES, ids=lambda p: p.name)
    def test_nothing_in_the_runtime_imports_a_filesystem_module(self, path: Path) -> None:
        for module, _names in _imports(path):
            assert module.split(".")[0] not in {"tempfile", "shutil", "pathlib", "os"}, (
                f"{path.name} imports {module}"
            )


class TestNothingSurvivesAnInvocation:
    @pytest.mark.parametrize("path", RUNTIME_FILES, ids=lambda p: p.name)
    def test_no_module_holds_mutable_state(self, path: Path) -> None:
        """A cached client or an "active connection" is how two stores get mixed up."""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name) and t.id != "__all__"]
            if not names:
                continue
            value = node.value
            if isinstance(value, (ast.List, ast.Set)):
                pytest.fail(f"{path.name} holds mutable module state: {names}")
            if isinstance(value, ast.Dict):
                # Declared lookup tables are fine as long as they are constants.
                assert all(name.isupper() or name.startswith("_") for name in names), names

    def test_no_module_exposes_an_active_connection(self) -> None:
        import runtime.connection as connection_module
        import runtime.operations as operations_module
        import runtime.transport as transport_module

        for module in (connection_module, operations_module, transport_module):
            for name in dir(module):
                assert "active" not in name.lower() or name.startswith("__")
                assert "_session" not in name.lower()
                assert not name.lower().startswith("current_")

    def test_a_second_invocation_does_not_inherit_the_first(self, http: FakeHttp) -> None:
        from runtime.transport import ShopifyGraphQLTransport

        def factory(connection):
            return ShopifyGraphQLTransport(connection, opener=http)

        http.queue(
            graphql_response({"shop": {"id": "gid://shopify/Shop/1"}}),
            graphql_response({"shop": {"id": "gid://shopify/Shop/2"}}),
        )
        token_a = "shpat_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # pragma: allowlist secret
        token_b = "shpat_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"  # pragma: allowlist secret

        handle_runtime(
            connection_payload("get_shop", shop_domain="a", access_token=token_a),
            transport_factory=factory,
        )
        handle_runtime(
            connection_payload("get_shop", shop_domain="b", access_token=token_b),
            transport_factory=factory,
        )

        assert http.requests[1]["headers"]["x-shopify-access-token"] == token_b
        assert token_a not in json.dumps(http.requests[1], default=repr)


class TestTheTokenIsNeverObservable:
    def test_the_connection_repr_does_not_carry_it(self) -> None:
        from runtime.connection import connection_from_payload

        connection = connection_from_payload(
            connection_payload("get_shop"), connection_ref="conn-1"
        )

        assert ACCESS_TOKEN not in repr(connection)
        assert ACCESS_TOKEN not in str(connection)
        assert ACCESS_TOKEN not in f"{connection}"
        assert ACCESS_TOKEN not in f"{connection!r}"

    def test_an_exception_that_carries_the_connection_does_not_carry_it(self) -> None:
        from runtime.connection import connection_from_payload

        connection = connection_from_payload(
            connection_payload("get_shop"), connection_ref="conn-1"
        )

        assert ACCESS_TOKEN not in str(RuntimeError(f"failed for {connection}"))

    @pytest.mark.parametrize(
        "operation_id",
        ["test_connection", "get_shop", "list_locations", "list_inventory_items"],
    )
    def test_no_successful_result_carries_it(self, operation_id: str, http: FakeHttp) -> None:
        from runtime.transport import ShopifyGraphQLTransport

        http.default = graphql_response(
            {
                "shop": {"id": "gid://shopify/Shop/1", "myshopifyDomain": "x"},
                "currentAppInstallation": {"accessScopes": [{"handle": "write_inventory"}]},
                "locations": {"pageInfo": {}, "nodes": []},
                "inventoryItems": {"pageInfo": {}, "nodes": []},
            }
        )

        response = handle_runtime(
            connection_payload(operation_id),
            transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
        )

        assert ACCESS_TOKEN not in json.dumps(response)

    def test_no_failure_carries_it(self, http: FakeHttp) -> None:
        from urllib.error import HTTPError

        from runtime.transport import ShopifyGraphQLTransport

        http.queue(HTTPError("https://x", 401, "no", {}, None))

        response = handle_runtime(
            connection_payload("get_shop"),
            transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
        )

        assert response["ok"] is False
        assert ACCESS_TOKEN not in json.dumps(response)

    def test_the_suppressed_test_mode_result_carries_nothing_at_all(self) -> None:
        response = handle_runtime(
            set_quantities_payload([quantity()], test_mode=True),
            transport_factory=lambda c: None,
        )

        assert ACCESS_TOKEN not in json.dumps(response)


class TestThereIsNoRawGraphqlSurface:
    def test_no_operation_accepts_a_document_or_a_query(self) -> None:
        from runtime.catalog import OPERATIONS

        forbidden = {
            "query",
            "graphql",
            "document",
            "mutation",
            "operation",
            "search",
            "variables",
            "fields",
            "node_id",
            "gid",
        }
        for row in OPERATIONS:
            assert not forbidden & set(row.input_field_names), row.operation_id

    def test_there_are_exactly_thirty_two_documents_and_they_are_literals(self) -> None:
        assert len(documents.DOCUMENTS) == 32
        source = (BUNDLE_ROOT / "runtime" / "documents.py").read_text(encoding="utf-8")
        for marker in (".format(", "f'''", 'f"""', "% (", "+ query", "join("):
            assert marker not in source, marker

    def test_no_document_is_built_at_runtime(self) -> None:
        for path in RUNTIME_FILES:
            source = path.read_text(encoding="utf-8")
            assert "query {" not in source or path.name == "documents.py"
            assert "mutation {" not in source or path.name == "documents.py"

    def test_the_caller_cannot_choose_the_quantity_name_or_the_reason(self, http: FakeHttp) -> None:
        from runtime.transport import ShopifyGraphQLTransport

        http.queue(adjustment_group_response())

        handle_runtime(
            set_quantities_payload([quantity()]),
            transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
        )

        assert http.variables()["input"]["name"] == documents.SET_QUANTITIES_NAME == "available"
        assert (
            http.variables()["input"]["reason"] == documents.SET_QUANTITIES_REASON == "correction"
        )

    def test_nothing_a_caller_supplies_ever_appears_in_a_document(self, http: FakeHttp) -> None:
        from runtime.transport import ShopifyGraphQLTransport

        http.queue(graphql_response({"nodes": []}))

        handle_runtime(
            connection_payload(
                "get_inventory_levels_batch",
                {"location_id": LOCATION_A, "inventory_item_ids": [ITEM_A]},
            ),
            transport_factory=lambda c: ShopifyGraphQLTransport(c, opener=http),
        )

        document = http.document()
        assert document == documents.GET_INVENTORY_LEVELS_BATCH
        assert LOCATION_A not in document
        assert ITEM_A not in document


class TestTheApiVersionIsPinnedInOnePlace:
    def test_the_version_appears_only_where_it_is_declared(self) -> None:
        for path in RUNTIME_FILES:
            source = path.read_text(encoding="utf-8")
            if path.name == "documents.py":
                continue
            assert documents.API_VERSION not in source, path.name

    def test_the_endpoint_path_carries_it(self) -> None:
        from runtime.connection import connection_from_payload

        connection = connection_from_payload(
            connection_payload("get_shop"), connection_ref="conn-1"
        )

        assert f"/admin/api/{documents.API_VERSION}/graphql.json" in connection.graphql_endpoint
