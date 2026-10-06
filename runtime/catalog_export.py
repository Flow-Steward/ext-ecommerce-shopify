"""Shopify-owned complete product export.

The regular list operation intentionally represents one GraphQL request. This
operation owns Shopify cursor pagination inside the extension and streams the
complete matching catalog to object storage, keeping provider rules and large
payloads out of Core and workflow state.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from flowsteward_extension_sdk import write_artifact_stream

try:
    from flowsteward_extension_sdk import report_progress
except ImportError:  # a Core with an SDK older than 0.3.0 shows no progress

    def report_progress(
        message: str = "", *, done: int | None = None, total: int | None = None
    ) -> None:
        return None


from . import catalog_quality, errors, shapes, validation
from .catalog import DEFAULT_PAGE_SIZE, Operation, operation
from .connection import connection_from_payload
from .errors import ExtensionError
from .export_details import enrich_products, read_export
from .transport import ShopifyGraphQLTransport

EXPORT_PRODUCTS_OPERATION_ID = "export_products"
EXPORT_PRODUCTS_BINDING_KEY = "shopify_products_export"
EXPORT_PRODUCTS_FILENAME = "shopify-products.jsonl"
EXPORT_PRODUCTS_CONTENT_TYPE = "application/x-ndjson"
MAX_EXPORT_PAGES = 100_000
_ARTIFACT_SAVE_ERROR = "The product catalog artifact could not be saved"


def export_products(
    payload: Mapping[str, Any],
    raw_input: Any,
    *,
    transport_factory: Any = ShopifyGraphQLTransport,
    artifact_writer: Callable[..., dict[str, Any]] = write_artifact_stream,
) -> dict[str, Any]:
    """Write every matching Shopify product as one bounded JSONL artifact."""
    if not isinstance(raw_input, Mapping):
        raise ExtensionError(errors.INVALID_PAYLOAD, "action.input must be an object")
    if "after" in raw_input:
        raise ExtensionError(
            errors.INVALID_PAYLOAD,
            "A complete catalog export does not accept an after cursor",
        )

    row = _export_operation()
    operation_input = validation.validated_input(row, raw_input)
    connection = connection_from_payload(payload, connection_ref=operation_input["connection_ref"])
    transport = transport_factory(connection)
    state = {"item_count": 0, "scanned_count": 0, "page_count": 0}
    quality = operation_input.get("quality_filter")
    chunks = _product_jsonl_chunks(
        transport,
        row,
        variables={
            "first": operation_input.get("first", DEFAULT_PAGE_SIZE),
            "query": operation_input.get("filter"),
            "sortKey": operation_input["sort_key"],
            "reverse": bool(operation_input.get("reverse", False)),
            "savedSearchId": operation_input.get("saved_search_id"),
        },
        state=state,
        include_images=operation_input["include_images"]
        or bool(quality and catalog_quality.needs_images(quality)),
        include_variants=operation_input["include_variants"]
        or bool(quality and catalog_quality.needs_variants(quality)),
        include_inventory=operation_input["include_inventory"],
        quality=quality,
    )
    try:
        written = artifact_writer(
            dict(payload),
            chunks,
            binding_key=EXPORT_PRODUCTS_BINDING_KEY,
            content_type=EXPORT_PRODUCTS_CONTENT_TYPE,
            timeout_seconds=300.0,
        )
    except ExtensionError:
        raise
    except Exception as exc:
        raise ExtensionError(
            errors.ARTIFACT_OUTPUT_UNAVAILABLE,
            _ARTIFACT_SAVE_ERROR,
        ) from exc
    if not isinstance(written, Mapping):
        raise ExtensionError(
            errors.ARTIFACT_OUTPUT_UNAVAILABLE,
            _ARTIFACT_SAVE_ERROR,
        )
    handle = str(written.get("artifact_handle") or "").strip()
    size_bytes = written.get("size_bytes")
    sha256 = str(written.get("sha256") or "").strip()
    if not handle or isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or not sha256:
        raise ExtensionError(
            errors.ARTIFACT_OUTPUT_UNAVAILABLE,
            _ARTIFACT_SAVE_ERROR,
        )

    artifact = {
        "artifact_handle": handle,
        "mime_type": EXPORT_PRODUCTS_CONTENT_TYPE,
        "size_bytes": size_bytes,
        "sha256": sha256,
    }
    return {
        "artifact_handle": handle,
        "filename": EXPORT_PRODUCTS_FILENAME,
        "content_type": EXPORT_PRODUCTS_CONTENT_TYPE,
        "item_count": state["item_count"],
        "scanned_count": state["scanned_count"],
        "page_count": state["page_count"],
        "size_bytes": size_bytes,
        "sha256": sha256,
        "artifacts": {EXPORT_PRODUCTS_FILENAME: artifact},
    }


def _progress_message(state: Mapping[str, int], *, filtered: bool) -> str:
    """Name what the export has done so far; Shopify does not say how many will match."""
    exported = state["item_count"]
    noun = "product" if exported == 1 else "products"
    if filtered:
        return f"Exported {exported} matching {noun} of {state['scanned_count']} checked"
    return f"Exported {exported} {noun}"


def _product_jsonl_chunks(
    transport: Any,
    row: Operation,
    *,
    variables: Mapping[str, Any],
    state: dict[str, int],
    include_images: bool,
    include_variants: bool,
    include_inventory: bool,
    quality: Mapping[str, Any] | None,
) -> Iterable[bytes]:
    after: str | None = None
    page = 1
    while page <= MAX_EXPORT_PAGES:
        data = read_export(
            transport,
            row.document or "",
            {**variables, "after": after},
            purpose=f"Shopify Admin GraphQL {EXPORT_PRODUCTS_OPERATION_ID} page {page}",
        ).data
        connection = shapes.mapping(data.get("products"))
        nodes = shapes.nodes(connection)
        page_info = shapes.page_info(connection.get("pageInfo"))
        state["page_count"] += 1
        products = [shapes.product(node) for node in nodes]
        enrich_products(
            transport,
            products,
            include_images=include_images,
            include_variants=include_variants,
            include_inventory=include_inventory,
        )
        for product in products:
            state["scanned_count"] += 1
            if quality:
                found = catalog_quality.issues(product, quality)
                if not catalog_quality.matches(found, quality):
                    continue
                product["quality_issues"] = found
            state["item_count"] += 1
            yield (
                json.dumps(product, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                + b"\n"
            )
        report_progress(
            _progress_message(state, filtered=bool(quality)),
            done=state["scanned_count"],
        )
        if not page_info["has_next_page"]:
            return
        next_cursor = page_info["end_cursor"]
        if not next_cursor or next_cursor == after:
            raise ExtensionError(
                errors.UPSTREAM_FAILURE,
                "Shopify did not provide a usable next product cursor",
            )
        after = next_cursor
        page += 1
    raise ExtensionError(
        errors.UPSTREAM_FAILURE,
        "The product catalog exceeded the safe pagination limit",
    )


def _export_operation() -> Operation:
    row = operation(EXPORT_PRODUCTS_OPERATION_ID)
    if row is None:  # pragma: no cover - guarded by closed-catalog tests
        raise ExtensionError(errors.INTERNAL_ERROR, "The product export is unavailable")
    return row


__all__ = [
    "EXPORT_PRODUCTS_BINDING_KEY",
    "EXPORT_PRODUCTS_CONTENT_TYPE",
    "EXPORT_PRODUCTS_FILENAME",
    "EXPORT_PRODUCTS_OPERATION_ID",
    "export_products",
]
