"""Runtime, contracts, step UI, action manifest and extension.yaml say one thing.

The registry in ``runtime/catalog.py`` is the source. Every shipped file that
restates any part of it is regenerated here and compared byte for byte, so a
row added to the runtime without a manifest entry — or a manifest entry with no
row behind it — fails rather than shipping.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from build_contracts import (
    GENERATED_FILES,
    action_manifest,
    artifact_policies,
    dump,
    external_effects,
    operation_manifest,
    step_ui_manifest,
)
from runtime import schema
from runtime.catalog import (
    ACTION_OPERATION_IDS,
    NETWORK_OPERATION_IDS,
    OPERATIONS,
    OPERATIONS_BY_ID,
    connection_type_for,
)
from runtime.connection import (
    CONNECTION_TYPE_ID,
    SECRET_FIELDS,
)
from runtime.documents import DOCUMENTS

BUNDLE_ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str) -> dict:
    return yaml.safe_load((BUNDLE_ROOT / relative).read_text(encoding="utf-8"))


MANIFEST = _load("extension.yaml")
OPERATION_MANIFEST = _load("contracts/operation_manifest.yaml")
STEP_UI = _load("contracts/step_ui_manifest.yaml")
ACTIONS = _load("ui/actions/actions.yaml")
CONNECTION_TYPES = _load("contracts/connection_types.yaml")


class TestTheGeneratedFilesAreCurrent:
    @pytest.mark.parametrize("relative", sorted(GENERATED_FILES))
    def test_each_generated_file_matches_the_registry(self, relative: str) -> None:
        expected = dump(GENERATED_FILES[relative]())

        assert (BUNDLE_ROOT / relative).read_text(encoding="utf-8") == expected, (
            f"{relative} is stale; run python tests/reference/refresh_contracts.py"
        )


class TestEverySurfaceListsTheSameOperations:
    def test_the_operation_manifest_matches(self) -> None:
        assert [row["operation_id"] for row in OPERATION_MANIFEST["operations"]] == [
            row.operation_id for row in OPERATIONS
        ]

    def test_the_step_ui_manifest_matches(self) -> None:
        assert [row["operation_id"] for row in STEP_UI["forms"]] == [
            row.operation_id for row in OPERATIONS
        ]

    def test_the_action_manifest_matches(self) -> None:
        assert [row["action_id"] for row in ACTIONS["actions"]] == [
            row.operation_id for row in OPERATIONS
        ]

    def test_there_are_exactly_thirty_three_of_them(self) -> None:
        assert len(OPERATIONS) == 33
        assert len(OPERATION_MANIFEST["operations"]) == 33
        assert len(STEP_UI["forms"]) == 33
        assert len(ACTIONS["actions"]) == 33

    def test_exactly_thirty_two_contact_shopify_and_each_owns_one_document(self) -> None:
        assert len(NETWORK_OPERATION_IDS) == 32
        assert set(DOCUMENTS) == set(NETWORK_OPERATION_IDS)
        assert len(DOCUMENTS) == 32

    def test_every_document_is_owned_by_exactly_one_operation(self) -> None:
        """Two operations may not share a document, even a similar one.

        `set_catalog_metafields` and `set_order_metafields` both call
        `metafieldsSet`, and it would be tempting to give them one document.
        They own separate ones because each asks for the owner ids its own
        result correlates by, and sharing would make a change for one silently
        alter the other.
        """
        owners = [row.operation_id for row in OPERATIONS if row.contacts_shopify]

        assert len(owners) == len(set(owners)) == 32
        assert len({id(DOCUMENTS[name]) for name in owners}) == 32

    def test_exactly_twelve_mutate_across_every_surface(self) -> None:
        assert len(ACTION_OPERATION_IDS) == 12
        assert [
            row["operation_id"]
            for row in OPERATION_MANIFEST["operations"]
            if row["operation_kind"] == "action"
        ] == list(ACTION_OPERATION_IDS)
        assert [row["action_id"] for row in ACTIONS["actions"] if row["mutates_platform"]] == list(
            ACTION_OPERATION_IDS
        )


class TestTheManifestAndTheRegistryAgree:
    def test_the_declared_external_effects_are_exactly_the_mutating_operations(self) -> None:
        assert MANIFEST["external_effects"] == external_effects()
        assert len(MANIFEST["external_effects"]) == 12

    def test_every_mutation_declares_its_own_distinct_effect_kind(self) -> None:
        """A shared effect kind would tell the host a product edit moved stock."""
        effects = MANIFEST["external_effects"]
        kinds = [effect["effect_kind"] for effect in effects]

        assert len(set(kinds)) == len(kinds) == 12
        for effect in effects:
            assert effect["channel"] == "shopify_admin_graphql"
            assert effect["idempotency"] == "required"
            assert effect["test_mode_behavior"] == "suppress"

    def test_each_effect_kind_comes_from_the_row_that_owns_it(self) -> None:
        declared = {e["operation_id"]: e["effect_kind"] for e in MANIFEST["external_effects"]}

        assert declared == {
            row.operation_id: row.effect_kind for row in OPERATIONS if row.has_external_effect
        }

    def test_no_source_declares_an_effect_kind(self) -> None:
        assert not [row for row in OPERATIONS if not row.has_external_effect and row.effect_kind]

    def test_the_manifest_identity_is_the_declared_one(self) -> None:
        assert MANIFEST["extension_id"] == "flowsteward.shopify"
        assert MANIFEST["version"] == "0.3.0"
        assert MANIFEST["manifest_version"] == 2
        assert MANIFEST["kind"] == "tool_provider"
        assert MANIFEST["features"] == ["tool", "action"]
        assert MANIFEST["required_scopes"] == [
            "extension:invoke",
            "artifact:read",
            "artifact:write",
        ]
        assert MANIFEST["account_scope"]["scope_type"] == "project"
        assert MANIFEST["python_requirements"] == []

    def test_the_contract_references_point_at_shipped_files(self) -> None:
        references = MANIFEST["runtime"]["extension_contract_v2"]

        # The OAuth provider is declared inline rather than by reference: it is
        # the one part of the contract that has to be read together with the
        # callbacks and effects around it.
        assert set(references) == {
            "oauth_providers",
            "connection_types",
            "operation_manifest",
            "step_ui_manifest",
            "artifact_policies",
        }
        assert isinstance(references["oauth_providers"], list)
        for key, relative in references.items():
            if key == "oauth_providers":
                continue
            assert (BUNDLE_ROOT / relative).is_file(), relative

    def test_the_export_artifact_policy_is_declared_everywhere(self) -> None:
        expected = artifact_policies()["artifact_policies"]

        assert MANIFEST["artifact_policies"] == expected
        assert _load("contracts/artifact_policies.yaml")["artifact_policies"] == expected

    def test_the_ui_and_action_manifests_are_extension_owned(self) -> None:
        assert MANIFEST["ui_manifest"] == "ui/ui_manifest.yaml"
        assert MANIFEST["action_manifest"] == "ui/actions/actions.yaml"
        assert (BUNDLE_ROOT / MANIFEST["ui_manifest"]).is_file()
        assert (BUNDLE_ROOT / MANIFEST["action_manifest"]).is_file()


class TestTheConnectionContract:
    def test_there_is_exactly_one_connection_type(self) -> None:
        assert len(CONNECTION_TYPES["connection_types"]) == 1

    def test_it_is_the_one_the_runtime_enforces(self) -> None:
        declared = CONNECTION_TYPES["connection_types"][0]

        assert declared["connection_type_id"] == CONNECTION_TYPE_ID == "shopify_admin"
        assert declared["auth"]["type"] == "oauth2"
        assert declared["auth"]["provider_id"] == "shopify_admin_oauth"
        # The store is not declared configuration: the platform writes it as the
        # verified OAuth subject, and the runtime reads it back from there.
        assert declared["config_schema"]["properties"] == {}
        assert set(declared["secret_schema"]["properties"]) == SECRET_FIELDS

    def test_both_schemas_refuse_anything_they_do_not_declare(self) -> None:
        declared = CONNECTION_TYPES["connection_types"][0]

        assert declared["config_schema"]["additionalProperties"] is False
        assert declared["secret_schema"]["additionalProperties"] is False

    def test_the_full_operation_scope_union_is_the_declared_requirement(self) -> None:
        """The exact set validated as covering all 31 operations."""
        declared = CONNECTION_TYPES["connection_types"][0]

        assert declared["auth"]["scopes"]["required"] == [
            "write_inventory",
            "read_locations",
            "write_products",
            "write_files",
            "write_orders",
            "write_assigned_fulfillment_orders",
            "write_merchant_managed_fulfillment_orders",
            "write_third_party_fulfillment_orders",
        ]
        assert declared["auth"]["scopes"]["optional"] == []

    def test_every_operation_that_needs_a_connection_names_this_one(self) -> None:
        for row in OPERATION_MANIFEST["operations"]:
            if row.get("connection_type_ids"):
                assert row["connection_type_ids"] == [CONNECTION_TYPE_ID]

    def test_only_the_pre_save_check_runs_without_a_connection(self) -> None:
        without = [
            row["operation_id"]
            for row in OPERATION_MANIFEST["operations"]
            if not row.get("connection_type_ids")
        ]

        assert without == ["validate_connection_settings"]


class TestThePublishedSchemasAreTheEnforcedOnes:
    def test_connection_publishes_readable_capabilities_and_a_keyed_scope_matrix(self) -> None:
        published = next(
            entry
            for entry in OPERATION_MANIFEST["operations"]
            if entry["operation_id"] == "test_connection"
        )
        outputs = {output["name"]: output for output in published["outputs"]}

        assert outputs["capabilities"]["schema"] == {
            "type": "array",
            "items": {"type": "string"},
        }
        assert outputs["capability_scope_matrix"]["value_type"] == "object"
        details = outputs["capability_scope_matrix"]["schema"]["additionalProperties"]
        assert details["additionalProperties"] is False
        assert details["required"] == [
            "scope_eligible",
            "required_oauth_scopes",
            "missing_required_oauth_scopes",
        ]

    @pytest.mark.parametrize("row", OPERATIONS, ids=lambda row: row.operation_id)
    def test_the_manifest_publishes_the_schema_the_runtime_executes(self, row) -> None:
        published = next(
            entry
            for entry in OPERATION_MANIFEST["operations"]
            if entry["operation_id"] == row.operation_id
        )
        for item in published["inputs"]:
            if item["name"] == "connection_ref":
                continue
            assert item["schema"] == row.input_schema["properties"][item["name"]]

    @pytest.mark.parametrize("row", OPERATIONS, ids=lambda row: row.operation_id)
    def test_no_operation_declares_a_rule_the_platform_would_ignore(self, row) -> None:
        assert not schema.unsupported_schema_keywords(row.input_schema)
        for output in row.outputs:
            if output.schema is not None:
                assert not schema.unsupported_schema_keywords(output.schema)

    @pytest.mark.parametrize("row", OPERATIONS, ids=lambda row: row.operation_id)
    def test_every_operation_refuses_fields_it_does_not_publish(self, row) -> None:
        assert row.input_schema["additionalProperties"] is False

    def test_the_nested_quantity_object_declares_its_own_required_fields(self) -> None:
        published = next(
            entry
            for entry in OPERATION_MANIFEST["operations"]
            if entry["operation_id"] == "set_inventory_quantities"
        )
        quantities = next(item for item in published["inputs"] if item["name"] == "quantities")[
            "schema"
        ]

        assert quantities["minItems"] == 1
        assert quantities["maxItems"] == 250
        assert quantities["items"]["additionalProperties"] is False
        assert set(quantities["items"]["required"]) == {
            "inventory_item_id",
            "location_id",
            "quantity",
            "change_from_quantity",
        }

    def test_the_nullable_compare_field_is_declared_nullable_and_required(self) -> None:
        published = next(
            entry
            for entry in OPERATION_MANIFEST["operations"]
            if entry["operation_id"] == "set_inventory_quantities"
        )
        items = next(item for item in published["inputs"] if item["name"] == "quantities")[
            "schema"
        ]["items"]

        assert "change_from_quantity" in items["required"]
        assert items["properties"]["change_from_quantity"]["type"] == ["integer", "null"]


class TestTheActionManifestMirrorsTheOperations:
    def test_create_product_publishes_a_typed_initial_variant_array_for_workflow_mapping(
        self,
    ) -> None:
        row = OPERATIONS_BY_ID["create_product"]
        output = next(output for output in row.outputs if output.name == "product_variants")
        result = output.schema or {}
        variant = result["items"]
        inventory_item = variant["properties"]["inventory_item"]

        assert result["type"] == "array"
        assert result["maxItems"] == 1
        assert "minItems" not in result  # a suppressed test-mode action returns an empty list
        assert variant["type"] == "object"
        assert variant["properties"]["id"] == {"type": "string"}
        assert inventory_item["type"] == "object"
        assert inventory_item["properties"]["id"] == {"type": "string"}
        assert inventory_item["properties"]["tracked"] == {"type": ["boolean", "null"]}

        action = next(
            action for action in ACTIONS["actions"] if action["action_id"] == "create_product"
        )
        assert "product_variants" in action["result_fields"]

    @pytest.mark.parametrize("row", OPERATIONS, ids=lambda row: row.operation_id)
    def test_each_action_publishes_the_same_results_and_errors(self, row) -> None:
        action = next(
            entry for entry in ACTIONS["actions"] if entry["action_id"] == row.operation_id
        )

        assert action["result_fields"] == list(row.result_fields)
        assert action["error_codes"] == list(row.error_codes)
        expected_scopes = ["extension:invoke"]
        if row.operation_id == "export_products":
            expected_scopes.append("artifact:write")
        if row.operation_id == "create_products_bulk":
            expected_scopes.append("artifact:read")
        assert action["required_scopes"] == expected_scopes
        assert action["workflow_visible"] is row.workflow_visible

    def test_only_the_pre_save_check_is_hidden_from_workflows(self) -> None:
        hidden = [
            entry["action_id"] for entry in ACTIONS["actions"] if not entry["workflow_visible"]
        ]

        assert hidden == ["validate_connection_settings"]

    def test_every_published_error_code_is_in_the_safe_vocabulary(self) -> None:
        from runtime import errors

        for action in ACTIONS["actions"]:
            for code in action["error_codes"]:
                assert code in errors.SAFE_ERROR_CODES, code

    def test_only_mutating_actions_can_report_an_unknown_outcome(self) -> None:
        """A source never leaves an outcome in doubt: it changed nothing."""
        reporting = [
            action["action_id"]
            for action in ACTIONS["actions"]
            if "timeout_unknown" in action["error_codes"]
        ]

        assert reporting == list(ACTION_OPERATION_IDS)


class TestTheStepUiMirrorsTheInputs:
    @pytest.mark.parametrize("row", OPERATIONS, ids=lambda row: row.operation_id)
    def test_each_form_offers_exactly_the_inputs_minus_the_connection(self, row) -> None:
        form = next(
            entry for entry in STEP_UI["forms"] if entry["operation_id"] == row.operation_id
        )
        expected = [name for name in row.input_field_names if name != "connection_ref"]

        assert [field["name"] for field in form["fields"]] == expected
        assert form["title"] == row.display_name

    def test_every_widget_is_one_the_platform_renders(self) -> None:
        """Restated here rather than imported: an extension may not read core."""
        allowed = {
            "text",
            "textarea",
            "number",
            "integer",
            "boolean",
            "select",
            "multi_select",
            "radio_group",
            "checkbox_group",
            "date",
            "datetime",
            "json",
            "key_value",
            "repeater",
            "resource_picker",
            "artifact_picker",
            "dataset_picker",
            "schema_mapper",
            "mapping_table",
            "batch_policy",
        }

        for form in STEP_UI["forms"]:
            for field in form["fields"]:
                assert field["widget_type"] in allowed

    def test_a_required_input_is_marked_required_in_the_form(self) -> None:
        form = next(
            entry
            for entry in STEP_UI["forms"]
            if entry["operation_id"] == "get_inventory_levels_batch"
        )
        required = {field["name"] for field in form["fields"] if field["required"]}

        assert required == {"location_id", "inventory_item_ids"}


class TestTheShippedPagesMatchTheManifest:
    """The connection page carries the OAuth connection form.

    The platform renders the list of connections, the store field and the button
    that starts authorization from a `connection_form` component naming the OAuth
    provider. Without one the page is prose and no connection can be added — which
    is exactly what happened when the old token-collecting form was deleted rather
    than converted.
    """

    @staticmethod
    def _connection_form() -> dict:
        page = _load("ui/pages/connection.yaml")
        forms = [c for c in page["components"] if c.get("type") == "connection_form"]
        assert len(forms) == 1, "the connection page needs exactly one connection form"
        return forms[0]

    def test_the_connection_page_ships_an_oauth_connection_form(self) -> None:
        data = self._connection_form()["data"]

        assert data["oauth_provider_id"] == "shopify_admin_oauth"
        assert data["connection_type"] == CONNECTION_TYPE_ID

    def test_the_form_names_a_declared_intent_and_operation(self) -> None:
        data = self._connection_form()["data"]
        intents = {
            row["intent_id"]
            for row in MANIFEST["runtime"]["extension_contract_v2"]["oauth_providers"][0][
                "authorization_intents"
            ]
        }

        assert data["oauth_intent"] in intents
        assert data["test_action"] in {row.operation_id for row in OPERATIONS}

    def test_the_setup_page_is_project_scoped(self) -> None:
        """Without this the platform renders no project selector.

        The OAuth configuration and the callback URL both belong to one project.
        A page that declares itself unscoped gets no project, and the whole OAuth
        setup panel — redirect URI, Client ID, Client secret — is never mounted.
        The page was left unscoped from when the connection took a pasted token.
        """
        assert _load("ui/pages/setup-guide.yaml")["project_scoped"] is True

    def test_the_connection_page_is_project_scoped(self) -> None:
        page = _load("ui/pages/connection.yaml")

        assert page.get("project_scoped", True) is True

    def test_the_form_collects_no_secret_of_its_own(self) -> None:
        """Credentials come from the OAuth configuration, never from this form."""
        data = self._connection_form()["data"]

        assert "secret_fields" not in data
        assert "config_fields" not in data
        assert "pre_save_actions" not in data

    def test_every_page_the_manifest_lists_is_shipped(self) -> None:
        ui_manifest = _load("ui/ui_manifest.yaml")

        for page in ui_manifest["pages"]:
            assert (BUNDLE_ROOT / "ui" / page["ref"]).is_file(), page["ref"]


class TestTheGeneratedTreeIsStable:
    def test_running_the_generator_again_changes_nothing(self, tmp_path) -> None:
        """A generator that is not a fixed point makes every diff noise.

        The shipped files are compared against a fresh render above; this
        additionally proves a second render of the same tree is byte-identical,
        so nobody has to guess whether a diff came from a change or from the
        generator.
        """
        from build_ui_pages import GENERATED_PAGES

        first = {name: dump(builder()) for name, builder in GENERATED_FILES.items()}
        second = {name: dump(builder()) for name, builder in GENERATED_FILES.items()}
        pages_first = {path.name: render() for path, render in GENERATED_PAGES.items()}
        pages_second = {path.name: render() for path, render in GENERATED_PAGES.items()}

        assert first == second
        assert pages_first == pages_second

    def test_the_manifests_effect_block_is_generated_not_hand_written(self) -> None:
        """`extension.yaml` is hand-authored except for this block.

        Writing effect kinds by hand is how a new mutation ends up declaring the
        previous one's effect, so the block is rendered from the registry and
        the shipped file has to match it byte for byte.
        """
        from build_contracts import manifest_with_external_effects

        current = (BUNDLE_ROOT / "extension.yaml").read_text(encoding="utf-8")

        assert manifest_with_external_effects(current) == current

    def test_the_shipped_tree_is_what_the_generator_produces(self) -> None:
        from build_ui_pages import GENERATED_PAGES

        for relative, builder in GENERATED_FILES.items():
            assert (BUNDLE_ROOT / relative).read_text(encoding="utf-8") == dump(builder())
        for path, render in GENERATED_PAGES.items():
            assert path.read_text(encoding="utf-8") == render()


class TestTheGeneratorsAgreeWithThemselves:
    def test_regenerating_twice_produces_the_same_bytes(self) -> None:
        first_operation_manifest = dump(operation_manifest())
        first_step_manifest = dump(step_ui_manifest())
        first_action_manifest = dump(action_manifest())

        assert dump(operation_manifest()) == first_operation_manifest
        assert dump(step_ui_manifest()) == first_step_manifest
        assert dump(action_manifest()) == first_action_manifest

    def test_the_connection_type_a_row_declares_is_derived_not_guessed(self) -> None:
        for row in OPERATIONS:
            expected = CONNECTION_TYPE_ID if "connection_ref" in row.input_field_names else ""
            assert connection_type_for(row) == expected
