"""Generate every published contract from the closed runtime registry.

The registry in ``runtime/catalog.py`` is the single source of truth. Everything
the platform reads — the operation manifest, the step UI manifest, the action
manifest, the artifact policy file and the external-effect rows in
``extension.yaml`` — is derived here, and ``tests/test_manifest_parity.py``
fails if a shipped file and this generator disagree.

Run ``python3 tests/reference/refresh_contracts.py`` from the bundle root after
changing the registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from runtime.catalog import (
    CATEGORY,
    CHANNEL,
    OPERATIONS,
    Operation,
    connection_type_for,
    ui_fields,
)

BUNDLE_ROOT = Path(__file__).resolve().parents[2]

GENERATED_HEADER = (
    "# Generated from the closed runtime registry in runtime/catalog.py.\n"
    "# Extension-owned parity tests fail if this file and the registry disagree.\n"
)

REQUIRED_SCOPES: list[str] = ["extension:invoke"]
EXPORT_PRODUCTS_OPERATION_ID = "export_products"


def _schema(value: Any) -> Any:
    """A plain, JSON-safe copy of one schema fragment."""
    if isinstance(value, dict):
        return {key: _schema(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_schema(item) for item in value]
    return value


def _inputs(row: Operation) -> list[dict[str, Any]]:
    properties = row.input_schema.get("properties") or {}
    required = set(row.required_input_field_names)
    rows: list[dict[str, Any]] = []
    for name, spec in properties.items():
        entry: dict[str, Any] = {
            "name": name,
            "value_type": "connection_ref"
            if name == "connection_ref"
            else "artifact_handle"
            if name == "artifact_handle"
            else _value_type(spec),
            "required": name in required,
        }
        if name != "connection_ref":
            entry["schema"] = _schema(spec)
        rows.append(entry)
    return rows


def _value_type(spec: dict[str, Any]) -> str:
    declared = spec.get("type")
    types = [declared] if isinstance(declared, str) else list(declared or [])
    for name, value_type in (
        ("object", "object"),
        ("array", "array"),
        ("boolean", "boolean"),
        ("integer", "integer"),
        ("number", "number"),
    ):
        if name in types:
            return value_type
    return "text"


def _outputs(row: Operation) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for output in row.outputs:
        entry: dict[str, Any] = {"name": output.name, "value_type": output.value_type}
        if output.schema is not None:
            entry["schema"] = _schema(output.schema)
        rows.append(entry)
    return rows


def operation_manifest() -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    for row in OPERATIONS:
        entry: dict[str, Any] = {
            "operation_id": row.operation_id,
            "display_name": row.display_name,
            "description": row.description,
            "operation_kind": row.kind,
            "category": CATEGORY,
        }
        connection_type = connection_type_for(row)
        if connection_type:
            entry["connection_type_ids"] = [connection_type]
        entry["contacts_shopify"] = row.contacts_shopify
        entry["workflow_visible"] = row.workflow_visible
        entry["required_oauth_scopes"] = list(row.required_oauth_scopes)
        if row.effect_kind:
            entry["effect_kind"] = row.effect_kind
        entry["inputs"] = _inputs(row)
        entry["outputs"] = _outputs(row)
        entry["result_fields"] = [f"result.{name}" for name in row.result_fields]
        entry["error_codes"] = list(row.error_codes)
        operations.append(entry)
    return {"operations": operations}


def step_ui_manifest() -> dict[str, Any]:
    forms: list[dict[str, Any]] = []
    for row in OPERATIONS:
        fields = [
            {
                "name": field.name,
                "label": field.label,
                "widget_type": field.widget_type,
                "required": field.required,
            }
            for field in ui_fields(row)
        ]
        forms.append(
            {
                "operation_id": row.operation_id,
                "title": row.display_name,
                "fields": fields,
            }
        )
    return {"forms": forms}


def action_manifest() -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    for row in OPERATIONS:
        required_scopes = list(REQUIRED_SCOPES)
        if row.operation_id == EXPORT_PRODUCTS_OPERATION_ID:
            required_scopes.append("artifact:write")
        if row.operation_id == "create_products_bulk":
            required_scopes.append("artifact:read")
        entry: dict[str, Any] = {
            "action_id": row.operation_id,
            "title": row.display_name,
            "description": row.description,
            "required_scopes": required_scopes,
            "handler": {"mode": "extension"},
        }
        if row.has_external_effect:
            entry["command_type"] = "invoke_extension_action"
        entry["mutates_platform"] = row.has_external_effect
        entry["workflow_visible"] = row.workflow_visible
        entry["parameters"] = [
            {
                "name": item["name"],
                "type": "connection_ref"
                if item["value_type"] == "connection_ref"
                else _parameter_type(item["value_type"]),
                "required": item["required"],
            }
            for item in _inputs(row)
        ]
        entry["result_fields"] = list(row.result_fields)
        entry["error_codes"] = list(row.error_codes)
        actions.append(entry)
    return {"actions": actions}


def _parameter_type(value_type: str) -> str:
    return {"text": "string", "object": "object", "array": "array"}.get(value_type, value_type)


def artifact_policies() -> dict[str, Any]:
    """The complete export streams to object storage with a configurable cap."""
    return {
        "artifact_policies": [
            {
                "operation_id": "create_products_bulk",
                "inputs": [
                    {
                        "kind": "artifact",
                        "value_type": "artifact_handle",
                        "binding_key": "bulk_products_input",
                        "field": "artifact_handle",
                        "required": False,
                        "max_size_bytes": 100000000,
                    }
                ],
            },
            {
                "operation_id": EXPORT_PRODUCTS_OPERATION_ID,
                "outputs": [
                    {
                        "kind": "artifact",
                        "value_type": "artifact_handle",
                        "binding_key": "shopify_products_export",
                        "filename": "shopify-products.jsonl",
                        "content_type": "application/x-ndjson",
                        "max_size_bytes": 209715200,
                        "max_size_env": "FS_EXTENSION_ARTIFACT_MAX_BYTES",
                        "retention_class": "run_window",
                    }
                ],
            },
        ]
    }


def external_effects() -> list[dict[str, Any]]:
    """Exactly the effects ``extension.yaml`` must declare.

    The effect kind is read from the row that owns it. Naming one here would
    mean every new mutation silently inherited the previous one's effect kind,
    and a host reading the manifest would be told a product edit changes stock.
    """
    return [
        {
            "operation_id": row.operation_id,
            "effect_kind": row.effect_kind,
            "channel": CHANNEL,
            "idempotency": "required",
            "test_mode_behavior": "suppress",
        }
        for row in OPERATIONS
        if row.has_external_effect
    ]


#: The manifest's own external-effect block, rendered in the manifest's style.
EXTERNAL_EFFECTS_KEY = "external_effects:\n"


def external_effects_block() -> str:
    """The `external_effects:` block exactly as ``extension.yaml`` carries it.

    Rendered rather than hand-maintained: every effect kind is owned by the row
    that causes the effect, so adding a mutation cannot leave the manifest
    describing the previous one.
    """
    return EXTERNAL_EFFECTS_KEY + "".join(
        "  - {" + ", ".join(f"{key}: {value}" for key, value in effect.items()) + "}\n"
        for effect in external_effects()
    )


def manifest_with_external_effects(current: str) -> str:
    """``extension.yaml`` with its effect block replaced by the generated one."""
    start = current.index(EXTERNAL_EFFECTS_KEY)
    end = current.index("runtime:\n", start)
    return current[:start] + external_effects_block() + current[end:]


def dump(payload: Any) -> str:
    return GENERATED_HEADER + yaml.safe_dump(
        payload,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=4096,
    )


GENERATED_FILES: dict[str, Any] = {
    "contracts/operation_manifest.yaml": operation_manifest,
    "contracts/step_ui_manifest.yaml": step_ui_manifest,
    "contracts/artifact_policies.yaml": artifact_policies,
    "ui/actions/actions.yaml": action_manifest,
}


__all__ = [
    "BUNDLE_ROOT",
    "EXTERNAL_EFFECTS_KEY",
    "GENERATED_FILES",
    "GENERATED_HEADER",
    "action_manifest",
    "artifact_policies",
    "dump",
    "external_effects",
    "external_effects_block",
    "manifest_with_external_effects",
    "operation_manifest",
    "step_ui_manifest",
]
