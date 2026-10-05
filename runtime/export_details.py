"""Complete optional export relations, batched within one product page."""

from __future__ import annotations

from collections.abc import Mapping
from time import sleep
from typing import Any

from . import errors, export_documents, shapes
from .errors import ExtensionError

# Keep requested GraphQL cost bounded even when each parent has a full child page.
PARENT_BATCH_SIZE = 5
MAX_RELATION_PAGES = 100_000


def _failure() -> ExtensionError:
    return ExtensionError(
        errors.UPSTREAM_FAILURE, "Shopify did not provide complete export details"
    )


def read_export(
    transport: Any, document: str, variables: Mapping[str, Any], *, purpose: str
) -> Any:
    """Retry only throttled export reads, retaining the same query and cursor."""
    for attempt in range(6):
        try:
            return transport.execute(document, variables, mutating=False, purpose=purpose)
        except ExtensionError as exc:
            if exc.code != errors.RATE_LIMITED or attempt == 5:
                raise
            delay = max(float(2**attempt), exc.retry_after_seconds or 0.0)
            if delay > 30.0:
                raise
            sleep(delay)
    raise _failure()  # pragma: no cover


def _relation_page(
    node: Any, expected: str, field: str
) -> tuple[list[Mapping[str, Any]], str | None]:
    if not isinstance(node, Mapping) or node.get("id") != expected:
        raise _failure()
    connection = node.get(field)
    if not isinstance(connection, Mapping):
        raise _failure()
    children, info = connection.get("nodes"), connection.get("pageInfo")
    if (
        not isinstance(children, list)
        or not isinstance(info, Mapping)
        or not isinstance(info.get("hasNextPage"), bool)
        or any(not isinstance(child, Mapping) for child in children)
    ):
        raise _failure()
    if not info["hasNextPage"]:
        return children, None
    cursor = info.get("endCursor")
    if not isinstance(cursor, str) or not cursor:
        raise _failure()
    return children, cursor


def _relation_batch(
    transport: Any, document: str, ids: list[str], field: str, **variables: Any
) -> dict[str, list[Mapping[str, Any]]]:
    result: dict[str, list[Mapping[str, Any]]] = {id_: [] for id_ in ids}
    pending: list[tuple[list[str], str | None]] = [(ids, None)]
    seen: dict[str, set[str]] = {}
    pages = 0
    while pending:
        batch, after = pending.pop()
        pages += 1
        if pages > MAX_RELATION_PAGES:
            raise _failure()
        data = read_export(
            transport,
            document,
            {"ids": batch, "after": after, **variables},
            purpose="Shopify product export details",
        ).data
        nodes = data.get("nodes")
        if not isinstance(nodes, list) or len(nodes) != len(batch):
            raise _failure()
        for expected, node in zip(batch, nodes, strict=True):
            children, cursor = _relation_page(node, expected, field)
            result[expected].extend(children)
            if cursor is not None:
                visited = seen.setdefault(expected, set())
                if cursor in visited:
                    raise _failure()
                visited.add(cursor)
                pending.append(([expected], cursor))
    return result


def _relations(
    transport: Any, document: str, ids: list[str], field: str, **variables: Any
) -> dict[str, list[Mapping[str, Any]]]:
    result: dict[str, list[Mapping[str, Any]]] = {id_: [] for id_ in ids}
    for start in range(0, len(ids), PARENT_BATCH_SIZE):
        batch = _relation_batch(
            transport, document, ids[start : start + PARENT_BATCH_SIZE], field, **variables
        )
        # Retain accumulation if the caller supplies the same parent in several batches.
        for id_, children in batch.items():
            result[id_].extend(children)
    return result


def enrich_products(
    transport: Any,
    products: list[dict[str, Any]],
    *,
    include_images: bool,
    include_variants: bool,
    include_inventory: bool,
) -> None:
    """Enrich a bounded product page in place; omit all unrequested fields."""
    ids = [p["id"] for p in products]
    if include_images:
        images = _relations(transport, export_documents.IMAGES, ids, "media")
        for product in products:
            product["images"] = [
                {
                    "id": shapes.text(n.get("id")),
                    "alt": shapes.optional_text(n.get("alt")),
                    "status": shapes.optional_text(n.get("status")),
                    "url": shapes.optional_text(shapes.mapping(n.get("image")).get("url")),
                    "width": shapes.optional_int(shapes.mapping(n.get("image")).get("width")),
                    "height": shapes.optional_int(shapes.mapping(n.get("image")).get("height")),
                }
                for n in images[product["id"]]
            ]
            product["image_count"] = len(product["images"])
    if not (include_variants or include_inventory):
        return
    variants = _relations(transport, export_documents.VARIANTS, ids, "variants")
    items: dict[str, dict[str, Any]] = {}
    for product in products:
        product["variants"] = [shapes.product_variant(node) for node in variants[product["id"]]]
        if not include_inventory:
            continue
        for variant in product["variants"]:
            item = variant.get("inventory_item")
            if not isinstance(item, dict) or not item.get("id"):
                raise _failure()
            items[item["id"]] = item
    if include_inventory:
        levels = _relations(transport, export_documents.INVENTORY, list(items), "inventoryLevels")
        for item_id, item in items.items():
            item["levels"] = [
                {
                    "id": shapes.text(n.get("id")),
                    "location_id": shapes.nested_id(n.get("location")),
                    "location_name": shapes.optional_text(
                        shapes.mapping(n.get("location")).get("name")
                    ),
                    "quantities": {q["name"]: q["quantity"] for q in n.get("quantities", [])},
                }
                for n in levels[item_id]
            ]
