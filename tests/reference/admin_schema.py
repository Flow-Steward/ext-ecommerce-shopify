"""The pinned slice of Shopify's official Admin GraphQL schema, and how to read it.

``admin_schema_2026_07.json`` beside this file is cut from Shopify's public
Admin GraphQL schema for API version ``2026-07`` — the same schema file the
Shopify AI Toolkit's ``validate.mjs`` and Shopify's Dev MCP validate against
(``skills/shopify-admin/assets/admin_2026-07.json.gz`` in the toolkit). It holds
every type this extension's documents touch, every input type their mutations
accept (to full depth), and the kind of every type those reach. The coverage
tests compare the extension against it, so "matches the official API" is
checked field by field rather than claimed.

The public schema is the reference on purpose. The introspection proxy behind
shopify.dev's GraphiQL also answers for fields that are not in the public
schema (``ProductOption.createdAt``, ``LineItem.createdAt``); a field the
public schema lacks is one a real store may refuse.

Regenerate it after changing a document or moving to a new API version::

    python3 tests/reference/admin_schema.py path/to/admin_2026-07.json[.gz]
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

BUNDLE_ROOT = Path(__file__).resolve().parents[2]
if str(BUNDLE_ROOT) not in sys.path:
    sys.path.insert(0, str(BUNDLE_ROOT))
REFERENCE_ROOT = Path(__file__).resolve().parent
if str(REFERENCE_ROOT) not in sys.path:
    sys.path.insert(0, str(REFERENCE_ROOT))

from graphql_selection import Field, named_type, parse  # noqa: E402

SNAPSHOT_PATH = REFERENCE_ROOT / "admin_schema_2026_07.json"
SOURCE = "Shopify AI Toolkit public Admin GraphQL schema admin_{version}.json.gz"


def all_documents() -> dict[str, str]:
    """Every fixed document the runtime can send, keyed by a readable name."""
    from runtime import bulk_documents, documents, export_documents, media_documents

    found: dict[str, str] = {}
    for module in (documents, bulk_documents, export_documents, media_documents):
        for name, value in vars(module).items():
            if (
                name.isupper()
                and isinstance(value, str)
                and value.lstrip().startswith(("query ", "mutation "))
            ):
                found[f"{module.__name__.rsplit('.', 1)[-1]}.{name}"] = value
    return found


def _type_ref(node: dict[str, Any]) -> str:
    if node["kind"] == "NON_NULL":
        return _type_ref(node["ofType"]) + "!"
    if node["kind"] == "LIST":
        return "[" + _type_ref(node["ofType"]) + "]"
    return str(node["name"])


def _live_args(field: dict[str, Any]) -> dict[str, str]:
    """A field's arguments, without the ones Shopify has deprecated."""
    return {
        arg["name"]: _type_ref(arg["type"]) for arg in field["args"] if not arg.get("isDeprecated")
    }


def build(introspection: dict[str, Any], version: str = "2026-07") -> dict[str, Any]:
    """Cut the slice this extension needs out of a full introspection result."""
    schema = introspection["data"]["__schema"]
    types = {entry["name"]: entry for entry in schema["types"]}
    roots = {"query": schema["queryType"]["name"], "mutation": schema["mutationType"]["name"]}
    objects: dict[str, dict[str, Any]] = {}
    inputs: dict[str, dict[str, str]] = {}
    enums: dict[str, list[str]] = {}
    kinds: dict[str, str] = {}
    deprecated_inputs: dict[str, list[str]] = {}
    used_root_fields: dict[str, set[str]] = {roots["query"]: set(), roots["mutation"]: set()}

    def remember(type_name: str) -> None:
        entry = types[type_name]
        kinds[type_name] = entry["kind"]
        if entry["kind"] == "ENUM" and type_name not in enums:
            enums[type_name] = [v["name"] for v in entry["enumValues"] if not v["isDeprecated"]]
        if entry["kind"] == "INPUT_OBJECT" and type_name not in inputs:
            inputs[type_name] = {}
            for field in entry["inputFields"]:
                if field.get("isDeprecated"):
                    deprecated_inputs.setdefault(type_name, []).append(field["name"])
                    continue
                inputs[type_name][field["name"]] = _type_ref(field["type"])
                remember(named_type(_type_ref(field["type"])))

    def store_object(type_name: str) -> None:
        if type_name in objects or type_name in used_root_fields:
            return
        entry = types[type_name]
        kinds[type_name] = entry["kind"]
        objects[type_name] = {}
        for field in entry["fields"] or []:
            objects[type_name][field["name"]] = {
                "type": _type_ref(field["type"]),
                "args": _live_args(field),
                "deprecated": bool(field["isDeprecated"]),
            }
            for arg in field["args"]:
                if not arg.get("isDeprecated"):
                    remember(named_type(_type_ref(arg["type"])))
            target = named_type(_type_ref(field["type"]))
            kinds[target] = types[target]["kind"]
            if types[target]["kind"] == "ENUM":
                remember(target)

    def walk(type_name: str, selections: list[Field], fragments: dict[str, list[Field]]) -> None:
        if type_name in used_root_fields:
            kinds[type_name] = "OBJECT"
        else:
            store_object(type_name)
        fields = {field["name"]: field for field in types[type_name]["fields"] or []}
        for selection in selections:
            if selection.name == "__typename":
                continue
            field = fields[selection.name]
            if type_name in used_root_fields:
                used_root_fields[type_name].add(selection.name)
                for arg in field["args"]:
                    if not arg.get("isDeprecated"):
                        remember(named_type(_type_ref(arg["type"])))
            target = named_type(_type_ref(field["type"]))
            if selection.selections or selection.fragments:
                walk(target, selection.selections, selection.fragments)
            else:
                kinds[target] = types[target]["kind"]
                if types[target]["kind"] == "ENUM":
                    remember(target)
        for condition, inner in fragments.items():
            walk(condition, inner, {})

    for document in all_documents().values():
        operation = parse(document)
        for variable_type in operation.variables.values():
            remember(named_type(variable_type))
        walk(roots[operation.kind], operation.selections, {})

    for root, names in used_root_fields.items():
        objects[root] = {}
        fields = {field["name"]: field for field in types[root]["fields"]}
        for name in sorted(names):
            field = fields[name]
            objects[root][name] = {
                "type": _type_ref(field["type"]),
                "args": _live_args(field),
                "deprecated": bool(field["isDeprecated"]),
            }

    return {
        "version": version,
        "source": SOURCE.format(version=version),
        "roots": roots,
        "kinds": dict(sorted(kinds.items())),
        "objects": {name: objects[name] for name in sorted(objects)},
        "inputs": {name: inputs[name] for name in sorted(inputs)},
        "enums": {name: enums[name] for name in sorted(enums)},
        "deprecated_input_fields": {
            name: deprecated_inputs[name] for name in sorted(deprecated_inputs)
        },
    }


def load() -> dict[str, Any]:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def input_paths(snapshot: dict[str, Any], type_name: str, prefix: str = "") -> Iterator[str]:
    """Every dotted path into one input type, leaves and branches alike."""
    for name, type_ref in snapshot["inputs"][type_name].items():
        path = f"{prefix}{name}"
        yield path
        target = named_type(type_ref)
        if snapshot["kinds"].get(target) == "INPUT_OBJECT":
            yield from input_paths(snapshot, target, f"{path}.")


def main(argv: list[str]) -> int:  # pragma: no cover - maintenance tool
    import gzip

    from runtime.documents import API_VERSION

    if len(argv) != 2:
        print(__doc__)
        return 2
    raw = Path(argv[1]).read_bytes()
    if argv[1].endswith(".gz"):
        raw = gzip.decompress(raw)
    snapshot = build(json.loads(raw), API_VERSION)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=1, sort_keys=False) + "\n", "utf-8")
    print(f"wrote {SNAPSHOT_PATH.relative_to(BUNDLE_ROOT)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
