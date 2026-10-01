"""The documentation a user actually reads, checked against the runtime.

A setup guide that omits what setting stock to zero does, or a reference page
that lists an operation the registry no longer has, is a defect: it is the only
description most people will ever see of what this extension will do to their
store.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from build_ui_pages import GENERATED_PAGES, changelog_page, inventory_page
from runtime.catalog import MAX_BATCH_ITEMS, MIN_BATCH_ITEMS, OPERATIONS
from runtime.documents import API_VERSION

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
README = (BUNDLE_ROOT / "README.md").read_text(encoding="utf-8")
CHANGELOG = (BUNDLE_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
SETUP_GUIDE = yaml.safe_load((BUNDLE_ROOT / "ui/pages/setup-guide.yaml").read_text())
CONNECTION_PAGE = yaml.safe_load((BUNDLE_ROOT / "ui/pages/connection.yaml").read_text())


def _page_text(page: dict) -> str:
    return "\n".join(str(component.get("body", "")) for component in page.get("components", []))


SETUP_TEXT = _page_text(SETUP_GUIDE)
#: The exact set the connection type declares as required.
REQUIRED_SCOPES = {
    "read_locations",
    "write_inventory",
    "write_products",
    "write_files",
    "write_orders",
    "write_assigned_fulfillment_orders",
    "write_merchant_managed_fulfillment_orders",
    "write_third_party_fulfillment_orders",
}
CONNECTION_TEXT = _page_text(CONNECTION_PAGE)


class TestTheGeneratedPagesAreCurrent:
    @pytest.mark.parametrize("path", sorted(GENERATED_PAGES), ids=lambda p: p.name)
    def test_each_generated_page_matches_its_source(self, path: Path) -> None:
        expected = GENERATED_PAGES[path]()

        assert path.read_text(encoding="utf-8") == expected, (
            f"{path.name} is stale; run python tests/reference/refresh_contracts.py"
        )

    def test_the_changelog_page_renders_the_changelog(self) -> None:
        rendered = changelog_page()

        assert "0.1.0" in rendered
        assert "inventorySetQuantities" in rendered

    def test_the_reference_page_is_valid_yaml_with_one_markdown_body(self) -> None:
        page = yaml.safe_load(inventory_page())

        assert page["page_id"] == "inventory-api"
        assert len(page["components"]) == 1
        assert page["components"][0]["type"] == "markdown"


class TestTheReferencePageListsExactlyWhatTheRuntimeHas:
    def test_every_operation_appears(self) -> None:
        page = yaml.safe_load(
            (BUNDLE_ROOT / "ui/pages/inventory-api.yaml").read_text(encoding="utf-8")
        )
        body = _page_text(page)

        for row in OPERATIONS:
            assert f"`{row.operation_id}`" in body, row.operation_id
            assert row.display_name in body, row.operation_id

    def test_no_operation_that_does_not_exist_appears(self) -> None:
        page = yaml.safe_load(
            (BUNDLE_ROOT / "ui/pages/inventory-api.yaml").read_text(encoding="utf-8")
        )
        body = _page_text(page)

        for absent in (
            "execute_graphql",
            "inventoryActivate",
            "inventoryAdjustQuantities",
            "productCreate",
            "webhook",
        ):
            assert absent not in body, absent

    def test_it_names_the_pinned_api_version_and_the_required_scope(self) -> None:
        page = yaml.safe_load(
            (BUNDLE_ROOT / "ui/pages/inventory-api.yaml").read_text(encoding="utf-8")
        )
        body = _page_text(page)

        assert API_VERSION in body
        assert "write_inventory" in body
        assert "write_products" in body
        assert "write_orders" in body


class TestTheSetupGuideExplainsWhatTheTaskRequires:
    @pytest.mark.parametrize(
        ("topic", "needles"),
        [
            ("who sets the app up", ["Dev Dashboard", "standalone"]),
            ("choosing custom distribution", ["Custom distribution", "install link"]),
            ("that custom distribution is permanent", ["cannot be undone"]),
            ("releasing a version for scopes", ["release a version"]),
            ("where the client credentials go", ["Client ID", "Client secret"]),
            ("the exact redirect URL", ["redirect URL", "character-for-character"]),
            ("that a merchant needs no developer account", ["not** need a Shopify developer"]),
            (
                "the exact Shopify permission a merchant needs",
                ["Manage and install apps and channels"],
            ),
            ("where the callback URL is shown", ["OAuth Redirect URI", "Setup Guide"]),
            (
                "that the callback is per project",
                ["per Flow Steward project, not one per deployment"],
            ),
            ("the real Dev Dashboard navigation", ["Start from Dev Dashboard", "Create a version"]),
            ("that the app must not be embedded", ["Embed app in Shopify admin"]),
            ("that custom distribution takes a store domain", ["store's domain"]),
            ("the default standalone App URL", ["shopify.dev/apps/default-app-home"]),
            ("that approval may not be shown twice", ["if Shopify shows"]),
            ("the tunnel for local testing", ["Cloudflare Tunnel", "FS_PUBLIC_BASE_URL"]),
            (
                "that a tunnel change needs a new release",
                ["release a new", "Editing without releasing"],
            ),
            ("reconnecting", ["reconnect the existing connection"]),
            ("that local disconnect is not an uninstall", ["does not uninstall the app"]),
            ("the required scope", ["write_inventory"]),
            ("that location reads use their distinct scope", ["read_locations", "distinct"]),
            ("that the full set is required", ["full set", "not a menu"]),
            ("that scopes need a release", ["take effect on", "release, not on save"]),
            ("that this is not a read-only integration", ["not a read-only integration"]),
            ("both supported domain forms", ["store-name", "store-name.myshopify.com"]),
            ("that a custom domain is not accepted", ["custom storefront domain"]),
            ("that stock is absolute", ["absolute, not changes", "It does not add"]),
            ("that zero makes an item out of stock", ["out of stock at that location"]),
            ("compare-and-swap", ["change_from_quantity", "someone else changed"]),
            ("the explicit null opt-out", ["explicit `null`", "opt out of the check"]),
            (
                "the unchanged stock-feed result",
                ["Repeating an unchanged stock feed succeeds", "CAS-proven no-op"],
            ),
            ("the synchronous batch limit", ["1 to 250", "waits for Shopify"]),
            ("that it does not chunk", ["does not split a larger list"]),
            ("several connections per project", ["as many Shopify connections as it needs"]),
            ("what an unknown outcome means", ["timeout_unknown"]),
        ],
    )
    def test_it_covers(self, topic: str, needles: list[str]) -> None:
        for needle in needles:
            assert needle in SETUP_TEXT, f"the setup guide does not explain {topic}: {needle}"

    def test_it_lists_every_rejected_address_form(self) -> None:
        for rejected in ("https://", "/admin", ":443", "user:pass@", "?x=1", "*."):
            assert rejected in SETUP_TEXT, rejected

    def test_it_names_the_batch_limits_the_runtime_enforces(self) -> None:
        assert str(MAX_BATCH_ITEMS) in SETUP_TEXT
        assert f"{MIN_BATCH_ITEMS} to {MAX_BATCH_ITEMS}" in SETUP_TEXT

    def test_it_does_not_pretend_setting_stock_is_harmless(self) -> None:
        """Nothing is deleted, but the store's behaviour changes. Say so."""
        assert "real business effect" in SETUP_TEXT
        assert "not a harmless no-op" in SETUP_TEXT

    def test_it_never_asks_anyone_to_create_or_paste_an_admin_token(self) -> None:
        """The old flow is gone, and the guide must not describe it any more."""
        assert "Admin API access token" not in SETUP_TEXT
        assert "Develop apps" not in SETUP_TEXT
        assert "do not create or" in SETUP_TEXT
        assert "copy any token" in SETUP_TEXT

    def test_it_explains_that_access_is_renewed_rather_than_permanent(self) -> None:
        assert "expires" in CONNECTION_TEXT
        assert "refresh token" in CONNECTION_TEXT

    def test_the_connection_page_explains_isolation_and_the_scope_report(self) -> None:
        assert "One connection per store" in CONNECTION_TEXT
        assert "All eight scopes are required" in CONNECTION_TEXT
        assert "discarded when it ends" in CONNECTION_TEXT

    def test_no_page_offers_a_partial_scope_grant(self) -> None:
        """The contract requires the full union, so nothing may suggest picking some."""
        for text in (CONNECTION_TEXT, SETUP_TEXT, README):
            assert "Grant only the scopes you need" not in text
            assert "only the scopes" not in text
        assert "not a menu" in SETUP_TEXT
        assert "not a menu" in CONNECTION_TEXT
        assert "no connection" in CONNECTION_TEXT

    def test_the_connection_page_says_no_token_is_asked_for(self) -> None:
        assert "You are not asked for a token" in CONNECTION_TEXT
        assert "signed" in CONNECTION_TEXT

    def test_the_connection_page_explains_why_a_duplicate_is_refused(self) -> None:
        assert "one token per app and store" in CONNECTION_TEXT


class TestTheSetupGuideNoLongerSaysOneScopeIsEnough:
    """The instruction a user follows must lead to a working integration.

    While the guide said "grant `write_inventory`, it covers everything here",
    anyone following it built a token that could not touch a product or an
    order, and the failure arrived at the first workflow step rather than at
    setup.
    """

    def test_it_does_not_claim_one_scope_covers_the_surface(self) -> None:
        assert "This extension needs exactly one scope" not in SETUP_TEXT
        assert "covers everything here" not in SETUP_TEXT
        assert "missing_required_scope" not in SETUP_TEXT

    @pytest.mark.parametrize("scope", sorted(REQUIRED_SCOPES))
    def test_every_required_scope_is_documented(self, scope: str) -> None:
        assert scope in SETUP_TEXT, scope

    def test_the_guide_documents_the_contract_and_not_a_menu(self) -> None:
        """The connection type requires the complete set, not a selectable subset."""
        assert "write_themes" not in SETUP_TEXT
        assert "not a menu" in SETUP_TEXT

    def test_the_guide_and_the_connection_type_declare_the_same_scopes(self) -> None:
        declared = yaml.safe_load(
            (BUNDLE_ROOT / "contracts/connection_types.yaml").read_text(encoding="utf-8")
        )
        required = declared["connection_types"][0]["auth"]["scopes"]["required"]

        assert set(required) == REQUIRED_SCOPES
        assert declared["connection_types"][0]["auth"]["scopes"]["optional"] == []

    def test_it_explains_what_the_capability_report_does_and_does_not_promise(self) -> None:
        assert "capability_scope_matrix" in SETUP_TEXT
        assert "readable list of eligible operation IDs" in SETUP_TEXT
        assert "scope_eligible" in SETUP_TEXT
        assert "required_oauth_scopes" in SETUP_TEXT
        assert "missing_required_oauth_scopes" in SETUP_TEXT
        assert "**not** as a promise the operation will succeed" in SETUP_TEXT
        assert "staff permissions" in SETUP_TEXT

    def test_it_says_an_incomplete_new_grant_is_rejected(self) -> None:
        assert "missing scope is rejected during OAuth callback" in SETUP_TEXT
        assert "older stale connection" in SETUP_TEXT

    def test_only_the_inventory_mutation_claims_shopify_idempotency(self) -> None:
        """Saying every action is de-duplicated would be a promise Shopify never made."""
        assert "No other action in this extension has that protection" in SETUP_TEXT
        assert "Treat a retry of those as a second write" in SETUP_TEXT

    def test_the_connection_page_and_contract_agree_with_the_guide(self) -> None:
        contract = (BUNDLE_ROOT / "contracts/connection_types.yaml").read_text()

        assert "It must grant write_inventory" not in contract
        assert "The token needs `write_inventory`" not in CONNECTION_TEXT


class TestTheReadmeMatchesTheRuntime:
    def test_it_states_the_operation_counts_the_registry_holds(self) -> None:
        network = [row for row in OPERATIONS if row.contacts_shopify]
        mutating = [row for row in OPERATIONS if row.kind == "action"]

        assert len(OPERATIONS) == 33
        assert len(network) == 32
        assert len(mutating) == 12
        assert (
            "**Thirty-three operations, thirty-two of which contact Shopify, twelve of which change "
            "anything.**" in README
        )

    def test_every_operation_is_in_its_table(self) -> None:
        for row in OPERATIONS:
            assert f"`{row.operation_id}`" in README, row.operation_id

    def test_it_records_the_toolkit_validation_evidence(self) -> None:
        assert "Shopify AI Toolkit validation evidence" in README
        assert "OPT_OUT_INSTRUMENTATION=true" in README
        assert "--version 2026-07" in README
        assert README.count("✅ VALID") == 32

    def test_it_names_the_pinned_api_version(self) -> None:
        assert API_VERSION in README

    def test_it_no_longer_offers_one_scope_for_the_whole_surface(self) -> None:
        assert "that one scope covers the whole surface here" not in README
        assert "The eight scopes below cover all 33 operations" in README

    def test_it_describes_the_oauth_connection_rather_than_a_pasted_token(self) -> None:
        assert "admin_api_access_token" not in README
        assert "authorization code grant" in README
        assert "connection_config.oauth.subject" in README

    def test_the_user_agent_matches_the_shipped_version(self) -> None:
        import yaml as _yaml
        from runtime.transport import _USER_AGENT

        version = _yaml.safe_load((BUNDLE_ROOT / "extension.yaml").read_text())["version"]

        assert f"FlowSteward-Shopify/{version.rsplit('.', 1)[0]}" == _USER_AGENT

    def test_it_states_what_the_bundle_does_not_contain(self) -> None:
        for absent in ("ShopifyAPI", "shopifyapp", "httpx", "requests", "urlopen"):
            assert absent in README, absent

    def test_it_names_every_document_that_was_validated(self) -> None:
        """The evidence table must cover the registry, not a snapshot of it."""
        for row in OPERATIONS:
            if row.contacts_shopify:
                prefix = (
                    "fs-bulk-products-"
                    if row.operation_id == "create_products_bulk"
                    else "fs-shopify-"
                )
                assert f"| `{row.operation_id}` | `{prefix}" in README, row.operation_id


class TestTheChangelogDescribesThisRelease:
    def test_it_records_the_version_the_manifest_declares(self) -> None:
        manifest = yaml.safe_load((BUNDLE_ROOT / "extension.yaml").read_text())

        assert f"## {manifest['version']}" in CHANGELOG

    def test_it_names_every_operation_this_release_adds(self) -> None:
        for row in OPERATIONS:
            assert row.operation_id in CHANGELOG, row.operation_id

    def test_it_names_the_shopify_operations_behind_them(self) -> None:
        for shopify_operation in (
            "inventorySetQuantities",
            "inventoryItems",
            "inventoryItem",
            "locations",
            "currentAppInstallation.accessScopes",
            "shop",
        ):
            assert shopify_operation in CHANGELOG, shopify_operation

    def test_it_has_a_security_section_that_names_the_real_guarantees(self) -> None:
        assert "### Security" in CHANGELOG
        for guarantee in (
            "never leaves the extension",
            "never accepted from workflow input",
            "No operation accepts GraphQL",
            "timeout_unknown",
            "no network request",
        ):
            assert guarantee in CHANGELOG, guarantee
