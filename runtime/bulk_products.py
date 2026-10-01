"""Submit asynchronous bulk draft creation without waiting for completion."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from flowsteward_extension_sdk import open_pinned_url, read_artifact_bytes

from . import bulk_documents, documents, errors, gids, shapes, validation
from .bulk_storage import MAX_BULK_BYTES, upload_jsonl
from .catalog import Operation, operation
from .connection import connection_from_payload
from .errors import ExtensionError
from .product_input import create_product_variables

MAX_PRODUCTS = 10000
CLIENT_PREFIX = "fs-product-create:"


def _invalid(message: str) -> ExtensionError:
    return ExtensionError(errors.INVALID_PAYLOAD, message, definitely_no_external_effect=True)


def _artifact_rows(payload: Mapping[str, Any], reader: Any) -> Any:
    try:
        body = reader(dict(payload), binding_key="bulk_products_input")
        if not isinstance(body, bytes) or len(body) > MAX_BULK_BYTES:
            raise _invalid("The products JSONL artifact exceeds 100 MB")
        lines = body.decode("utf-8-sig").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if not 1 <= len(lines) <= MAX_PRODUCTS:
            raise _invalid("The products JSONL artifact must contain 1 to 10000 lines")
        return [json.loads(line) for line in lines]
    except ExtensionError:
        raise
    except Exception as exc:
        raise _invalid("The products artifact must be valid UTF-8 JSONL") from exc


def _rows(payload: Mapping[str, Any], inputs: dict[str, Any], reader: Any) -> list[dict[str, Any]]:
    if ("products" in inputs) == ("artifact_handle" in inputs):
        raise _invalid("Supply exactly one of products or artifact_handle")
    rows = (
        _artifact_rows(payload, reader) if "artifact_handle" in inputs else inputs.get("products")
    )
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_PRODUCTS:
        raise _invalid("Supply between 1 and 10000 products")
    create = operation("create_product")
    assert create is not None
    validated = []
    handles: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or "connection_ref" in row:
            raise _invalid(
                f"Product row {index} must use create_product fields without connection_ref"
            )
        try:
            item = validation.validated_input(
                create, {"connection_ref": inputs["connection_ref"], **row}
            )
        except ExtensionError as exc:
            raise _invalid(
                f"Product row {index} does not match the create_product input contract"
            ) from exc
        handle = item["handle"].lower()
        if handle in handles:
            raise _invalid(f"Product row {index} repeats a handle in this batch")
        handles.add(handle)
        validated.append(create_product_variables(item))
    return validated


def _submission_record(node: Any, effect_id: str) -> dict[str, Any]:
    if (
        not isinstance(node, Mapping)
        or not gids.is_gid(node.get("id"), expected_type="BulkOperation")
        or not isinstance(node.get("status"), str)
        or not node["status"]
        or node.get("type") != "MUTATION"
    ):
        raise ExtensionError(
            errors.TIMEOUT_UNKNOWN,
            "Shopify did not identify this bulk product operation",
            retryable=False,
            external_effect_status="timeout_unknown",
            definitely_no_external_effect=False,
        )
    return {
        "id": node["id"],
        "status": node["status"],
        "client_identifier": CLIENT_PREFIX + effect_id,
    }


def run_bulk(
    payload: Mapping[str, Any],
    row: Operation,
    raw_input: Any,
    *,
    transport_factory: Any,
    artifact_reader: Any = None,
    storage_opener: Any = None,
) -> dict[str, Any]:
    """Submit the validated batch without waiting for Shopify processing."""
    inputs = validation.validated_input(row, raw_input)
    if ("products" in inputs) == ("artifact_handle" in inputs):
        raise _invalid("Supply exactly one of products or artifact_handle")
    if validation.test_mode(payload):
        if "products" in inputs:
            _rows(payload, inputs, None)
        return {
            "bulk_operation": None,
            "item_count": 0,
            "external_effect_status": "suppressed",
            "definitely_no_external_effect": True,
        }
    effect_id = validation.external_effect_id(payload)
    rows = _rows(payload, inputs, artifact_reader or read_artifact_bytes)
    chunks = []
    size = 0
    for variables in rows:
        chunk = json.dumps(variables, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        size += len(chunk)
        if size > MAX_BULK_BYTES:
            raise _invalid("The encoded products batch exceeds 100 MB")
        chunks.append(chunk)
    body = b"".join(chunks)
    connection = connection_from_payload(payload, connection_ref=inputs["connection_ref"])
    transport = transport_factory(connection)
    return _submit(transport, body, len(rows), effect_id, storage_opener or open_pinned_url)


def _submit(transport: Any, body: bytes, count: int, effect_id: str, opener: Any) -> dict[str, Any]:
    data = transport.execute(
        bulk_documents.STAGE, {}, mutating=False, purpose="Shopify bulk staging"
    ).data
    staged = shapes.mapping(data.get("stagedUploadsCreate"))
    targets = staged.get("stagedTargets")
    if (
        staged.get("userErrors")
        or not isinstance(targets, list)
        or len(targets) != 1
        or not isinstance(targets[0], Mapping)
    ):
        raise ExtensionError(
            errors.UPSTREAM_VALIDATION_FAILED,
            "Shopify did not provide a staged bulk upload",
            definitely_no_external_effect=True,
        )
    path = upload_jsonl(targets[0], body, opener=opener)
    # clientIdentifier helps reconciliation; Shopify does not promise deduplication.
    try:
        data = transport.execute(
            documents.CREATE_PRODUCTS_BULK,
            {
                "mutation": bulk_documents.CREATE_ROW,
                "path": path,
                "clientIdentifier": CLIENT_PREFIX + effect_id,
            },
            mutating=True,
            purpose="Shopify bulk product submission",
        ).data
    except ExtensionError as exc:
        if exc.code == errors.TIMEOUT_UNKNOWN:
            raise ExtensionError(
                errors.TIMEOUT_UNKNOWN,
                "Bulk submission outcome is unknown; reconcile before resubmitting",
                retryable=False,
                external_effect_status="timeout_unknown",
                definitely_no_external_effect=False,
            ) from exc
        raise
    accepted = data.get("bulkOperationRunMutation")
    if not isinstance(accepted, Mapping) or not isinstance(accepted.get("userErrors"), list):
        raise ExtensionError(
            errors.TIMEOUT_UNKNOWN,
            "Shopify did not confirm bulk submission",
            retryable=False,
            external_effect_status="timeout_unknown",
            definitely_no_external_effect=False,
        )
    if accepted["userErrors"]:
        raise ExtensionError(
            errors.UPSTREAM_VALIDATION_FAILED,
            "Shopify rejected the bulk submission",
            definitely_no_external_effect=True,
        )
    record = _submission_record(accepted.get("bulkOperation"), effect_id)
    return {
        "bulk_operation": record,
        "item_count": count,
        "external_effect_status": "succeeded",
        "definitely_no_external_effect": False,
    }
