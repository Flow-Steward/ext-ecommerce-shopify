"""Execute the published input schema, rather than re-stating it in code.

Each operation publishes one JSON Schema in ``contracts/operation_manifest.yaml``
and the runtime validates against that same object. Writing the rules twice is
how a manifest and a runtime drift: a nested ``required`` list that reads well in
the manifest but is never executed leaves ``quantities: [{}]`` accepted here and
rejected only by Shopify, which is exactly the failure this module exists to
prevent.

Only the keyword subset the Flow Steward host itself executes is supported —
``type``, ``enum``, ``const``, ``required``, ``properties``,
``additionalProperties``, ``items``, ``minLength``, ``maxLength``, ``minimum``,
``maximum``, ``minItems``, ``maxItems`` — so an operation cannot declare a rule
in its manifest that the platform would silently ignore. A schema reaching this
module with any other assertive keyword is a packaging error and is refused.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from . import errors
from .errors import ExtensionError

EXECUTED_KEYWORDS: frozenset[str] = frozenset(
    {
        "type",
        "enum",
        "const",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
    }
)

#: Keywords that carry no assertion. This set mirrors the host's, ``format``
#: included: JSON Schema itself defines ``format`` as annotation-only unless a
#: format-assertion vocabulary is enabled, so allowing it without executing it
#: is what the specification says rather than a loophole.
ANNOTATION_KEYWORDS: frozenset[str] = frozenset(
    {
        "$schema",
        "$id",
        "$comment",
        "title",
        "description",
        "default",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
        "format",
    }
)

MAX_PAYLOAD_DEPTH = 8


def unsupported_schema_keywords(schema: Any, path: str = "schema") -> list[str]:
    """Every keyword in ``schema`` this module would not execute."""
    findings: list[str] = []
    if not isinstance(schema, Mapping):
        return findings
    for key in schema:
        if key in EXECUTED_KEYWORDS or key in ANNOTATION_KEYWORDS:
            continue
        findings.append(f"{path}.{key}")
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        for name, child in properties.items():
            findings.extend(unsupported_schema_keywords(child, f"{path}.properties.{name}"))
    items = schema.get("items")
    if isinstance(items, Mapping):
        findings.extend(unsupported_schema_keywords(items, f"{path}.items"))
    additional = schema.get("additionalProperties")
    if isinstance(additional, Mapping):
        findings.extend(unsupported_schema_keywords(additional, f"{path}.additionalProperties"))
    return findings


def validate(value: Any, schema: Mapping[str, Any], *, path: str = "input") -> None:
    """Raise ``ExtensionError(invalid_payload)`` unless ``value`` matches ``schema``."""
    _validate(value, schema, path=path, depth=0)


def _fail(message: str) -> None:
    raise ExtensionError(errors.INVALID_PAYLOAD, message)


def _validate(value: Any, schema: Mapping[str, Any], *, path: str, depth: int) -> None:
    if depth > MAX_PAYLOAD_DEPTH:
        _fail(f"{path} is nested too deeply")
    declared = schema.get("type")
    types = []
    if isinstance(declared, str):
        types = [declared]
    elif isinstance(declared, Sequence) and not isinstance(declared, (str, bytes)):
        types = list(declared)
    if types and not any(_type_matches(name, value) for name in types):
        _fail(f"{path} must be {_readable_types(types)}")

    if "const" in schema and value != schema["const"]:
        _fail(f"{path} must be {schema['const']!r}")
    enum = schema.get("enum")
    if isinstance(enum, Sequence) and not isinstance(enum, (str, bytes)) and value not in enum:
        _fail(f"{path} must be one of the documented values")

    if isinstance(value, str):
        _validate_string(value, schema, path=path)
    elif isinstance(value, bool):
        pass  # a boolean carries no numeric or length bound
    elif isinstance(value, (int, float)):
        _validate_number(value, schema, path=path)
    elif isinstance(value, Mapping):
        _validate_object(value, schema, path=path, depth=depth)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        _validate_array(value, schema, path=path, depth=depth)


def _validate_string(value: str, schema: Mapping[str, Any], *, path: str) -> None:
    minimum = schema.get("minLength")
    maximum = schema.get("maxLength")
    if isinstance(minimum, int) and len(value) < minimum:
        _fail(f"{path} must be at least {minimum} characters")
    if isinstance(maximum, int) and len(value) > maximum:
        _fail(f"{path} must be at most {maximum} characters")


def _validate_number(value: float, schema: Mapping[str, Any], *, path: str) -> None:
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if isinstance(minimum, (int, float)) and not isinstance(minimum, bool) and value < minimum:
        _fail(f"{path} must be at least {minimum}")
    if isinstance(maximum, (int, float)) and not isinstance(maximum, bool) and value > maximum:
        _fail(f"{path} must be at most {maximum}")


def _validate_object(
    value: Mapping[str, Any], schema: Mapping[str, Any], *, path: str, depth: int
) -> None:
    properties = schema.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    required = schema.get("required")
    if isinstance(required, Sequence) and not isinstance(required, (str, bytes)):
        for name in required:
            if name not in value:
                _fail(f"{path}.{name} is required")
    additional = schema.get("additionalProperties")
    if additional is False:
        for name in value:
            if name not in properties:
                _fail(f"{path}.{name} is not a supported field")
    elif isinstance(additional, Mapping):
        for name, item in value.items():
            if name not in properties:
                _validate(item, additional, path=f"{path}.{name}", depth=depth + 1)
    for name, child_schema in properties.items():
        if name in value and isinstance(child_schema, Mapping):
            _validate(value[name], child_schema, path=f"{path}.{name}", depth=depth + 1)


def _validate_array(
    value: Sequence[Any], schema: Mapping[str, Any], *, path: str, depth: int
) -> None:
    minimum = schema.get("minItems")
    maximum = schema.get("maxItems")
    if isinstance(minimum, int) and len(value) < minimum:
        _fail(f"{path} must contain at least {minimum} item(s)")
    if isinstance(maximum, int) and len(value) > maximum:
        _fail(f"{path} must contain at most {maximum} item(s)")
    items = schema.get("items")
    if isinstance(items, Mapping):
        for index, item in enumerate(value):
            _validate(item, items, path=f"{path}[{index}]", depth=depth + 1)


def _type_matches(name: Any, value: Any) -> bool:
    if name == "object":
        return isinstance(value, Mapping)
    if name == "array":
        return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    return False


def _readable_types(types: Sequence[Any]) -> str:
    names = [str(name) for name in types]
    if len(names) == 1:
        return f"a {names[0]}"
    return " or ".join(names)


__all__ = [
    "ANNOTATION_KEYWORDS",
    "EXECUTED_KEYWORDS",
    "MAX_PAYLOAD_DEPTH",
    "unsupported_schema_keywords",
    "validate",
]
