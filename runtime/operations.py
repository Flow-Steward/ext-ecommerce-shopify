"""Execute exactly one declared operation, or refuse before any outbound I/O.

Each operation has its own handler, its own fixed GraphQL document and its own
result shape. Nothing is shared between two invocations: the connection, the
transport and every intermediate value live in the call frame and are gone when
it returns, so two Shopify connections used one after another in the same worker
process cannot see each other's store or token.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import catalog, documents, errors, gids, scopes, shapes, validation
from .catalog import (
    SET_QUANTITIES_OPERATION_ID,
    TEST_CONNECTION_OPERATION_ID,
    VALIDATE_SETTINGS_OPERATION_ID,
    Operation,
    operation,
)
from .catalog_export import EXPORT_PRODUCTS_OPERATION_ID, export_products
from .connection import connection_from_payload, normalize_shop_domain
from .errors import ExtensionError, error_response
from .media_upload import stage_images
from .product_input import (
    create_media_input,
    create_product_variables,
    metafield_input,
    product_update_variables,
    variant_bulk_input,
)
from .transport import ShopifyGraphQLTransport

_MESSAGE_THAT_OPERATION_IS_NOT_PART_OF_THIS_EXTENSION = (
    "That operation is not part of this extension"
)

#: Exactly the keys the host puts in an action envelope. Rejecting the ones it
#: adds for provenance — which page and component invoked the action, and the
#: host context — made every operation fail with `invalid_payload` when it was
#: called through the platform rather than in a test. ``runtime_context`` is not
#: among them: it is a top-level host field, alongside ``action``, not inside it.
_ALLOWED_ACTION_KEYS = frozenset(
    {
        "action_id",
        "operation_id",
        "page_id",
        "component_id",
        "context",
        "input",
        "target",
    }
)

MAX_GRANTED_SCOPES = 500
MAX_RETURNED_NODES = 250

#: Shopify's user error codes are a documented enum, never free-form text. The
#: first one is surfaced so an operator can tell a stock-out refusal from a bad
#: id, and the pattern is what keeps an upstream string from riding along.
_USER_ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_USER_ERROR_FIELD_SEGMENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")

#: The two operations that serve the connection itself rather than a workflow.
#: They are excluded from the capability report: nothing schedules them.
_CONNECTION_OPERATION_IDS: frozenset[str] = frozenset(
    {VALIDATE_SETTINGS_OPERATION_ID, TEST_CONNECTION_OPERATION_ID}
)

#: Result fields the runtime sets itself on every action.
_EXTERNAL_EFFECT_FIELDS: frozenset[str] = frozenset(
    {"external_effect_status", "definitely_no_external_effect"}
)


def handle_runtime(
    payload: Mapping[str, Any],
    *,
    transport_factory: Any = ShopifyGraphQLTransport,
    artifact_writer: Any = None,
    artifact_reader: Any = None,
    storage_opener: Any = None,
) -> dict[str, Any]:
    """Dispatch one runtime invocation through the closed registry."""
    try:
        operation_id, raw_input = _envelope(payload)
        row = operation(operation_id)
        if row is None:
            raise ExtensionError(
                errors.UNSUPPORTED_OPERATION, _MESSAGE_THAT_OPERATION_IS_NOT_PART_OF_THIS_EXTENSION
            )
        if row.operation_id == VALIDATE_SETTINGS_OPERATION_ID:
            return _run_validate_settings(row, raw_input)
        if row.operation_id == EXPORT_PRODUCTS_OPERATION_ID:
            kwargs = {"transport_factory": transport_factory}
            if artifact_writer is not None:
                kwargs["artifact_writer"] = artifact_writer
            return _ok(export_products(payload, raw_input, **kwargs))
        if row.operation_id == "create_products_bulk":
            from .bulk_products import run_bulk

            return _ok(
                run_bulk(
                    payload,
                    row,
                    raw_input,
                    transport_factory=transport_factory,
                    artifact_reader=artifact_reader,
                    storage_opener=storage_opener,
                )
            )
        return _run_shopify_operation(
            payload,
            row,
            raw_input,
            transport_factory,
            artifact_reader=artifact_reader,
            storage_opener=storage_opener,
        )
    except ExtensionError as exc:
        return error_response(exc.code, exc.message, retry_facts=exc.retry_facts())
    except Exception:
        return error_response(errors.INTERNAL_ERROR, "The operation could not be completed")


def _envelope(payload: Mapping[str, Any]) -> tuple[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("mode") != "action":
        raise ExtensionError(errors.INVALID_PAYLOAD, "Request mode must be action")
    action = payload.get("action")
    if not isinstance(action, Mapping) or set(action) - _ALLOWED_ACTION_KEYS:
        raise ExtensionError(errors.INVALID_PAYLOAD, "The action envelope is invalid")
    operation_id = action.get("action_id") or action.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id.strip():
        raise ExtensionError(errors.INVALID_PAYLOAD, "An operation id is required")
    return operation_id.strip(), action.get("input")


@dataclass(frozen=True)
class _Context:
    """Everything one operation may touch, and nothing more.

    The connection, the transport and the typed input live here for the length
    of a single call. There is no module-level client, no cached session and no
    way to reach another integration: an invocation sees one connection because
    that is the only one it was given.
    """

    row: Operation
    operation_input: Mapping[str, Any]
    transport: Any
    document: str
    payload: Mapping[str, Any]
    artifact_reader: Any = None
    storage_opener: Any = None

    def staged_images(self) -> list[dict[str, Any]]:
        """Upload the call's artifact images to Shopify's staging, if it has any.

        The only requests besides the operation's own document: staging is
        Shopify's documented first step for a file it does not fetch by URL,
        and it changes nothing in the store.
        """
        return stage_images(
            self.payload,
            self.transport,
            self.operation_input.get("image_files") or [],
            reader=self.artifact_reader,
            opener=self.storage_opener,
        )

    def execute(self, variables: Mapping[str, Any], *, mutating: bool = False) -> Mapping[str, Any]:
        """Send this operation's own fixed document, once.

        Exactly one request for the operation itself. No preflight lookup, no
        scope discovery, no retry: a second request would double the cost of
        every workflow step and, for a mutation, make "did it happen?"
        unanswerable. Image staging, when a call carries artifact images, is
        the one documented exception and happens before this.
        """
        return self.transport.execute(
            self.document,
            variables,
            mutating=mutating,
            purpose=f"Shopify Admin GraphQL {self.row.operation_id}",
        ).data


def _is_type(node: Mapping[str, Any], expected: str) -> bool:
    """Whether a node Shopify returned really is the type that was asked for."""
    typename = node.get("__typename")
    if isinstance(typename, str) and typename != expected:
        return False
    return gids.is_gid(node.get("id"), expected_type=expected)


def _media_type_of(media_id: str) -> str:
    """The concrete media type of an already-validated media GID."""
    for name in gids.FILE_GID_TYPES:
        if gids.is_gid(media_id, expected_type=name):
            return name
    raise ExtensionError(  # pragma: no cover - validation ran first
        errors.INTERNAL_ERROR, "The operation could not be completed"
    )


def _neutral_result(row: Operation) -> dict[str, Any]:
    """A schema-valid result for an action that was suppressed before sending.

    Derived from the operation's own published outputs rather than written out
    per operation, so a rehearsal always hands the workflow the same shape a
    real run would — an empty one.
    """
    result: dict[str, Any] = {}
    for output in row.outputs:
        if output.name in _EXTERNAL_EFFECT_FIELDS:
            continue
        declared = (output.schema or {}).get("type")
        types = [declared] if isinstance(declared, str) else list(declared or [])
        if "array" in types:
            result[output.name] = []
        elif "null" in types:
            result[output.name] = None
        elif "boolean" in types:
            result[output.name] = False
        elif "integer" in types or "number" in types:
            result[output.name] = 0
        else:  # pragma: no cover - every action output is nullable or a list
            result[output.name] = ""
    result["external_effect_status"] = "suppressed"
    result["definitely_no_external_effect"] = True
    return result


# -- Capability reporting ---------------------------------------------------


def _capabilities(granted: Sequence[str]) -> list[dict[str, Any]]:
    """What the granted scopes allow, one row per business operation.

    Registry order, so the list reads the same way the documentation does.
    ``validate_connection_settings`` and ``test_connection`` are excluded: they
    are the connection's own machinery, not something a workflow schedules.

    A row says only that the *scopes* permit the attempt. Shopify still decides
    everything else — staff permissions, shop state, whether a fulfillment order
    belongs to this app, the state of the record — so a scope-eligible operation
    can still be refused, and this is never consulted to skip a request.
    """
    return [
        scopes.capability_row(row.operation_id, row.required_oauth_scopes, granted)
        for row in catalog.OPERATIONS
        if row.operation_id not in _CONNECTION_OPERATION_IDS
    ]


# -- Mutation confirmation --------------------------------------------------


def _payload(data: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    """The payload of one mutation, or an unknown outcome.

    A mutation that answered without its payload has not told us whether it
    ran. Reporting a plain failure here would claim more than the response
    supports, so the outcome is reported as unknown instead.
    """
    found = data.get(field)
    if not isinstance(found, Mapping):
        raise ExtensionError(errors.TIMEOUT_UNKNOWN, "Shopify answered without the mutation result")
    return found


def _raise_for_user_errors(user_errors: Any) -> None:
    """Any non-empty ``userErrors`` fails the action.

    Shopify's user error codes are a documented enum, never free-form text, so
    the first one is surfaced to tell a stock-out refusal from a bad id. The
    pattern is what stops an upstream string riding along with it.
    """
    if not isinstance(user_errors, Sequence) or isinstance(user_errors, (str, bytes)):
        return
    entries = [entry for entry in user_errors if isinstance(entry, Mapping)]
    if not entries:
        return
    first = entries[0]
    code = first.get("code")
    details: list[str] = []
    if isinstance(code, str) and _USER_ERROR_CODE_RE.fullmatch(code):
        details.append(code)
    field = first.get("field")
    if isinstance(field, Sequence) and not isinstance(field, (str, bytes)):
        field_path = ".".join(
            segment
            for segment in field
            if isinstance(segment, str) and _USER_ERROR_FIELD_SEGMENT_RE.fullmatch(segment)
        )
        if field_path:
            details.append(field_path)
    detail = f" ({'; '.join(details)})" if details else ""
    raise ExtensionError(
        errors.UPSTREAM_VALIDATION_FAILED,
        f"Shopify rejected {len(entries)} of the requested changes{detail}",
    )


def _confirmed(data: Mapping[str, Any], field: str, resource: str) -> Mapping[str, Any]:
    """The confirmed resource of one mutation, or an unknown outcome.

    Order matters. ``userErrors`` is read first, because an explicit rejection
    is a definite answer; only then is a missing resource treated as unknown.
    """
    payload = _payload(data, field)
    _raise_for_user_errors(payload.get("userErrors"))
    found = payload.get(resource)
    if not isinstance(found, Mapping):
        raise ExtensionError(
            errors.TIMEOUT_UNKNOWN, "Shopify accepted the request without confirming the result"
        )
    return found


def _confirmed_list(data: Mapping[str, Any], field: str, resource: str) -> list[Mapping[str, Any]]:
    payload = _payload(data, field)
    _raise_for_user_errors(payload.get("userErrors"))
    found = payload.get(resource)
    if not isinstance(found, list):
        raise ExtensionError(
            errors.TIMEOUT_UNKNOWN, "Shopify accepted the request without confirming the result"
        )
    return [entry for entry in found if isinstance(entry, Mapping)]


def _confirmed_id(record: Mapping[str, Any], *, expected_type: str, expected: str = "") -> str:
    """The id Shopify returned, checked for type and, when known, for identity.

    A returned id of the wrong type, or of a record nobody asked about, means
    this side can no longer say what was changed. That is reported as unknown
    rather than as success with a surprising id attached.
    """
    returned = record.get("id")
    if not gids.is_gid(returned, expected_type=expected_type):
        raise ExtensionError(
            errors.TIMEOUT_UNKNOWN, "Shopify confirmed a result this operation cannot identify"
        )
    if expected and returned != expected:
        raise ExtensionError(
            errors.TIMEOUT_UNKNOWN, "Shopify confirmed a different record than the one requested"
        )
    return str(returned)


def _confirmed_by_id(
    records: Sequence[Mapping[str, Any]], *, expected_type: str, requested: Sequence[str]
) -> list[Mapping[str, Any]]:
    """Match returned records to requested ids, never by array position.

    Shopify returns these in whatever order it likes. Reading them positionally
    would attach one variant's confirmation to another's request, and the result
    would look entirely well-formed while being wrong about every row.
    """
    wanted = list(requested)
    by_id: dict[str, Mapping[str, Any]] = {}
    for record in records:
        identifier = _confirmed_id(record, expected_type=expected_type)
        if identifier in by_id:
            raise ExtensionError(errors.TIMEOUT_UNKNOWN, "Shopify confirmed the same record twice")
        if identifier not in wanted:
            raise ExtensionError(
                errors.TIMEOUT_UNKNOWN, "Shopify confirmed a record that was not requested"
            )
        by_id[identifier] = record
    missing = [identifier for identifier in wanted if identifier not in by_id]
    if missing:
        raise ExtensionError(
            errors.TIMEOUT_UNKNOWN, "Shopify did not confirm every requested record"
        )
    return [by_id[identifier] for identifier in wanted]


def _assert_same_product(records: Sequence[Mapping[str, Any]], product_id: str) -> None:
    """Every confirmed variant must sit on the product that was addressed.

    A variant confirmed against another product means this side is reading a
    different record than it wrote, and reporting that as success would attach
    one product's variants to another product's request.

    An owner that cannot be read at all is the same answer, not a lesser one.
    Both documents select `product { id }`, so a record arriving without it is
    Shopify answering in a shape this side does not understand — and since the
    write may already have been applied, "cannot verify the owner" has to be
    reported as unknown rather than waved through as success.
    """
    for record in records:
        owner = shapes.nested_id(record.get("product"))
        if owner != product_id:
            raise ExtensionError(
                errors.TIMEOUT_UNKNOWN,
                "Shopify did not confirm the variant against the product that was requested",
            )


def _confirmed_count(
    records: Sequence[Mapping[str, Any]],
    *,
    expected_type: str,
    expected: int,
    product_id: str,
) -> None:
    """As many distinct, well-typed records as were asked for, and no more."""
    identifiers = {_confirmed_id(record, expected_type=expected_type) for record in records}
    if len(identifiers) != len(records) or len(records) != expected:
        raise ExtensionError(
            errors.TIMEOUT_UNKNOWN, "Shopify did not confirm exactly the requested records"
        )
    _assert_same_product(records, product_id)


def _confirmed_metafields(
    data: Mapping[str, Any], requested: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Correlate set metafields by their natural key, not by position.

    A metafield has no caller-supplied id, so owner, namespace and key are what
    identifies it. Every requested tuple must come back exactly once; anything
    else means this side cannot say which values now hold.
    """
    records = _confirmed_list(data, "metafieldsSet", "metafields")
    by_key: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for record in records:
        owner = shapes.optional_text(shapes.mapping(record.get("owner")).get("id"))
        identity = (
            owner or "",
            str(record.get("namespace") or ""),
            str(record.get("key") or ""),
        )
        if identity in by_key:
            raise ExtensionError(
                errors.TIMEOUT_UNKNOWN, "Shopify confirmed the same metafield twice"
            )
        by_key[identity] = record
    wanted = {
        (str(entry["owner_id"]), str(entry["namespace"]), str(entry["key"])) for entry in requested
    }
    # Set equality, not containment. An extra confirmation used to be dropped on
    # the way out, which meant Shopify had reported changing something this side
    # never asked about and the caller was told everything went to plan.
    if set(by_key) != wanted:
        raise ExtensionError(
            errors.TIMEOUT_UNKNOWN,
            "Shopify confirmed a different set of metafields than the one requested",
        )
    shaped: list[dict[str, Any]] = []
    for entry in requested:
        owner_id = str(entry["owner_id"])
        identity = (owner_id, str(entry["namespace"]), str(entry["key"]))
        shaped.append(shapes.metafield(by_key[identity], owner_id=owner_id))
    return shaped


# -- Operations without a network call ------------------------------------


def _run_validate_settings(row: Operation, raw_input: Any) -> dict[str, Any]:
    """Normalize the store address before the connection form saves it.

    Runs entirely in-process: no request is made and no secret is received.
    """
    operation_input = validation.validated_input(row, raw_input)
    normalized = normalize_shop_domain(operation_input["shop_domain"])
    return _ok({"valid": True, "normalized_shop_domain": normalized})


# -- Operations that contact Shopify --------------------------------------


def _run_shopify_operation(
    payload: Mapping[str, Any],
    row: Operation,
    raw_input: Any,
    transport_factory: Any,
    *,
    artifact_reader: Any = None,
    storage_opener: Any = None,
) -> dict[str, Any]:
    operation_input = validation.validated_input(row, raw_input)
    idempotency_key = ""
    if row.has_external_effect:
        # Suppression happens before the connection is hydrated and before any
        # transport exists, so a rehearsal cannot reach the store even by
        # accident. The input is still validated first: a rehearsal that accepts
        # a batch the real run would refuse teaches the wrong lesson.
        if validation.test_mode(payload):
            return _ok(_neutral_result(row))
        idempotency_key = validation.external_effect_id(payload)

    connection = connection_from_payload(payload, connection_ref=operation_input["connection_ref"])
    transport = transport_factory(connection)
    document = row.document
    if document is None:  # pragma: no cover - every network row declares one
        raise ExtensionError(
            errors.UNSUPPORTED_OPERATION, _MESSAGE_THAT_OPERATION_IS_NOT_PART_OF_THIS_EXTENSION
        )
    context = _Context(
        row=row,
        operation_input=operation_input,
        transport=transport,
        document=document,
        payload=payload,
        artifact_reader=artifact_reader,
        storage_opener=storage_opener,
    )

    if row.operation_id == TEST_CONNECTION_OPERATION_ID:
        return _ok(_test_connection_result(context.execute({}), connection.shop_domain))
    if row.operation_id == SET_QUANTITIES_OPERATION_ID:
        return _ok(_set_inventory_quantities(context, idempotency_key))
    handler = _HANDLERS.get(row.operation_id)
    if handler is None:  # pragma: no cover - the registry has no other row
        raise ExtensionError(
            errors.UNSUPPORTED_OPERATION, _MESSAGE_THAT_OPERATION_IS_NOT_PART_OF_THIS_EXTENSION
        )
    result = handler(context)
    if row.has_external_effect:
        result["external_effect_status"] = "succeeded"
        result["definitely_no_external_effect"] = False
    return _ok(result)


def _get_shop(context: _Context) -> dict[str, Any]:
    return {"shop": shapes.shop(context.execute({}).get("shop"))}


def _test_connection_result(data: Mapping[str, Any], shop_domain: str) -> dict[str, Any]:
    """Prove the token works and belongs to this store, then report what it can do.

    Two things still fail the connection: a token Shopify rejects, and a token
    that belongs to a different store than the one configured. A missing
    business scope does not. A token scoped only for catalog work is a perfectly
    good connection — it simply cannot set stock — and refusing it here would
    make the operator delete a working integration to fix a problem they do not
    have. Instead every business operation is reported with whether the granted
    scopes cover it.
    """
    shop = data.get("shop")
    shop = shop if isinstance(shop, Mapping) else {}
    returned_domain = _text(shop.get("myshopifyDomain"))
    if returned_domain.lower() != shop_domain.lower():
        raise ExtensionError(
            errors.SHOP_DOMAIN_MISMATCH,
            "The access token belongs to a different Shopify store than this connection names",
        )
    granted = _granted_scopes(data.get("currentAppInstallation"))
    rows = _capabilities(granted)
    return {
        "shop_id": _optional_text(shop.get("id")),
        "shop_name": _optional_text(shop.get("name")),
        "myshopify_domain": returned_domain,
        "api_version": documents.API_VERSION,
        "granted_scopes": granted,
        "capability_summary": _capability_summary(rows),
        "capabilities": [str(row["operation_id"]) for row in rows if row["scope_eligible"] is True],
        "capability_scope_matrix": {
            str(row["operation_id"]): {
                "scope_eligible": row["scope_eligible"],
                "required_oauth_scopes": row["required_oauth_scopes"],
                "missing_required_oauth_scopes": row["missing_required_oauth_scopes"],
            }
            for row in rows
        },
    }


def _capability_summary(rows: Sequence[Mapping[str, Any]]) -> str:
    """One sentence a person can read, beside the keyed matrix a workflow can use.

    The platform summarises a result by formatting each field as text, and an
    array of objects has no text form — it renders as a row of separators. The
    full matrix still matters to a workflow, while the readable capability list
    carries only operation IDs.
    """
    total = len(rows)
    eligible = sum(1 for row in rows if row.get("scope_eligible") is True)
    if not total:
        return "No operations declared"
    if eligible == total:
        return f"All {total} operations are covered by the granted scopes"
    blocked = sorted(
        str(row.get("operation_id") or "") for row in rows if row.get("scope_eligible") is not True
    )
    named = ", ".join(blocked[:5])
    if len(blocked) > 5:
        named = f"{named}, and {len(blocked) - 5} more"
    return f"{eligible} of {total} operations are covered; not covered: {named}"


def _granted_scopes(installation: Any) -> list[str]:
    if not isinstance(installation, Mapping):
        return []
    scopes = installation.get("accessScopes")
    if not isinstance(scopes, Sequence) or isinstance(scopes, (str, bytes)):
        return []
    handles: list[str] = []
    for entry in scopes[:MAX_GRANTED_SCOPES]:
        handle = entry.get("handle") if isinstance(entry, Mapping) else None
        if isinstance(handle, str) and handle.strip():
            handles.append(handle.strip())
    return handles


def _list_locations(context: _Context) -> dict[str, Any]:
    operation_input = context.operation_input
    variables = {
        "first": operation_input["first"],
        "after": operation_input.get("after"),
        "includeInactive": bool(operation_input.get("include_inactive", False)),
        "includeLegacy": bool(operation_input.get("include_legacy", False)),
        "query": operation_input.get("filter"),
        "sortKey": operation_input["sort_key"],
        "reverse": bool(operation_input.get("reverse", False)),
    }
    data = context.execute(variables)
    connection = data.get("locations")
    connection = connection if isinstance(connection, Mapping) else {}
    return {
        "locations": [shapes.location(node) for node in _nodes(connection)],
        "page_info": _page_info(connection.get("pageInfo")),
    }


def _list_inventory_items(context: _Context) -> dict[str, Any]:
    operation_input = context.operation_input
    sku = operation_input.get("sku")
    # The Shopify search string is built here and travels as a variable, so a
    # SKU can never become part of a document. A caller's own filter is
    # combined with it, never spliced into it.
    terms = [term for term in (
        _sku_query(sku) if isinstance(sku, str) else None,
        f"({operation_input['filter']})" if "filter" in operation_input else None,
    ) if term]  # fmt: skip
    variables = {
        "first": operation_input["first"],
        "after": operation_input.get("after"),
        "query": " AND ".join(terms) if terms else None,
        "reverse": bool(operation_input.get("reverse", False)),
    }
    data = context.execute(variables)
    connection = data.get("inventoryItems")
    connection = connection if isinstance(connection, Mapping) else {}
    return {
        "inventory_items": [shapes.inventory_item(node) for node in _nodes(connection)],
        "page_info": _page_info(connection.get("pageInfo")),
    }


def _sku_query(sku: str) -> str:
    """One quoted Shopify search term. The value is data, never syntax."""
    escaped = sku.replace("\\", "\\\\").replace('"', '\\"')
    return f'sku:"{escaped}"'


def _get_inventory_item(context: _Context) -> dict[str, Any]:
    operation_input = context.operation_input
    variables = {"id": operation_input["inventory_item_id"]}
    data = context.execute(variables)
    node = _requested_node(
        data,
        "inventoryItem",
        expected_type=gids.INVENTORY_ITEM,
        expected=operation_input["inventory_item_id"],
        what="inventory item",
    )
    return {"inventory_item": shapes.inventory_item(node)}


def _inventory_levels_batch(context: _Context) -> dict[str, Any]:
    operation_input = context.operation_input
    requested: list[str] = list(operation_input["inventory_item_ids"])
    location_id = operation_input["location_id"]
    include_inactive = bool(operation_input.get("include_inactive", False))
    # Shopify omits an inactive level entirely unless the query asks for it, so
    # the flag has to travel with the request. Filtering only the response would
    # make `include_inactive: true` look supported while never returning
    # anything it was meant to reveal.
    variables = {
        "ids": requested,
        "locationId": location_id,
        "includeInactive": include_inactive,
    }
    data = context.execute(variables)
    returned = data.get("nodes")
    returned = list(returned) if isinstance(returned, list) else []
    if len(returned) > MAX_RETURNED_NODES:
        raise ExtensionError(errors.UPSTREAM_FAILURE, "Shopify returned more nodes than requested")

    # Shopify returns `nodes` in the order the ids were given, but the rows are
    # keyed by the id each node reports rather than by its position. Trusting
    # the position would mean that a single ordering change upstream silently
    # attributes one product's stock to another — and a stock sync acting on
    # that would set the wrong quantities without anything looking wrong.
    by_id: dict[str, Mapping[str, Any]] = {}
    for node in returned:
        if isinstance(node, Mapping) and _is_inventory_item(node):
            by_id.setdefault(_text(node.get("id")), node)

    rows: list[dict[str, Any]] = []
    for inventory_item_id in requested:
        node = by_id.get(inventory_item_id)
        # A node Shopify could not resolve is data, not a failure: a batch of
        # 250 must not be lost because one id was retired.
        if node is None:
            rows.append(
                {
                    "inventory_item_id": inventory_item_id,
                    "found": False,
                    "sku": None,
                    "tracked": None,
                    "level": None,
                }
            )
            continue
        rows.append(
            {
                "inventory_item_id": inventory_item_id,
                "found": True,
                "sku": _optional_text(node.get("sku")),
                "tracked": _optional_bool(node.get("tracked")),
                "level": _inventory_level(
                    node.get("inventoryLevel"), include_inactive=include_inactive
                ),
            }
        )
    return {"location_id": location_id, "items": rows}


def _set_inventory_quantities(context: _Context, idempotency_key: str) -> dict[str, Any]:
    operation_input = context.operation_input
    """Send one synchronous absolute-quantity write and wait for its answer.

    The batch is sent exactly as given: no chunking, no retry, and no Shopify
    bulk operation. ``changeFromQuantity`` is always present, carrying an
    explicit ``null`` when the caller intentionally opted out of the
    compare-and-swap check.
    """
    variables = {
        "input": {
            "name": operation_input.get("name", documents.SET_QUANTITIES_NAME),
            "reason": operation_input.get("reason", documents.SET_QUANTITIES_REASON),
            "referenceDocumentUri": (f"{documents.REFERENCE_DOCUMENT_URI_PREFIX}{idempotency_key}"),
            "quantities": [
                {
                    "inventoryItemId": entry["inventory_item_id"],
                    "locationId": entry["location_id"],
                    "quantity": entry["quantity"],
                    "changeFromQuantity": entry["change_from_quantity"],
                }
                for entry in operation_input["quantities"]
            ],
        },
        "idempotencyKey": idempotency_key,
    }
    data = context.execute(variables, mutating=True)
    result = data.get("inventorySetQuantities")
    result = result if isinstance(result, Mapping) else {}
    _raise_for_user_errors(result.get("userErrors"))
    group = result.get("inventoryAdjustmentGroup")
    if not isinstance(group, Mapping):
        confirmed_noop = (
            "inventoryAdjustmentGroup" in result
            and group is None
            and all(
                entry["change_from_quantity"] is not None
                and entry["quantity"] == entry["change_from_quantity"]
                for entry in operation_input["quantities"]
            )
        )
        if confirmed_noop:
            return {
                "inventory_adjustment_group": None,
                "external_effect_status": "succeeded",
                "definitely_no_external_effect": False,
            }
        # Shopify neither reported an error nor returned the adjustment, so the
        # write cannot be confirmed unless compare-and-swap proves that every
        # requested absolute quantity was already the current value. Saying
        # "succeeded" for any other absent receipt would be a guess.
        raise ExtensionError(
            errors.TIMEOUT_UNKNOWN,
            "Shopify accepted the request without confirming the adjustment",
        )
    return {
        "inventory_adjustment_group": shapes.adjustment_group(group),
        "external_effect_status": "succeeded",
        "definitely_no_external_effect": False,
    }


# -- Catalog sources --------------------------------------------------------


#: Optional list arguments and the Shopify variable each one fills.
_PAGE_VARIABLES: tuple[tuple[str, str], ...] = (
    ("filter", "query"),
    ("sort_key", "sortKey"),
    ("saved_search_id", "savedSearchId"),
    ("namespace", "namespace"),
    ("keys", "keys"),
)


def _page(operation_input: Mapping[str, Any]) -> dict[str, Any]:
    """The forward page variables, plus whichever list arguments the row declares.

    An optional argument the caller left out is not sent at all, which GraphQL
    reads as ``null``; the non-null ones always arrive with their published
    default, applied during validation.
    """
    page = {"first": operation_input["first"], "after": operation_input.get("after")}
    for name, variable in _PAGE_VARIABLES:
        if name in operation_input:
            page[variable] = operation_input[name]
    if "reverse" in operation_input:
        page["reverse"] = bool(operation_input["reverse"])
    return page


def _requested_node(
    data: Mapping[str, Any], field: str, *, expected_type: str, expected: str, what: str
) -> Mapping[str, Any]:
    """The record that was asked for, or a refusal that says which kind.

    Three outcomes, kept apart on purpose.

    An explicit `null` is Shopify saying the record is not there — `not_found`,
    and a workflow may reasonably branch on it.

    Anything else that is not a usable record — the field missing entirely, a
    string or a list where an object belongs, an object carrying no `id` — is
    Shopify answering in a shape this side does not understand. That is not
    evidence of absence, and reporting it as `not_found` would tell a workflow a
    record was deleted when nothing of the sort is known. It is an upstream
    failure.

    A node of another type or another id means the store answered about
    something else, which is neither absence nor success: handing a workflow a
    different product than it asked for is the failure that would go unnoticed
    longest, so it is reported the same way.
    """
    if field in data and data[field] is None:
        raise ExtensionError(errors.NOT_FOUND, f"That {what} does not exist in this store")
    node = data.get(field)
    if not isinstance(node, Mapping) or node.get("id") is None:
        raise ExtensionError(
            errors.UPSTREAM_FAILURE, f"Shopify did not answer with a usable {what}"
        )
    if not _is_type(node, expected_type) or node.get("id") != expected:
        raise ExtensionError(errors.UPSTREAM_FAILURE, f"Shopify answered about a different {what}")
    return node


def _list_products(context: _Context) -> dict[str, Any]:
    data = context.execute(_page(context.operation_input))
    connection = shapes.mapping(data.get("products"))
    return {
        "products": [shapes.product(node) for node in shapes.nodes(connection)],
        "page_info": shapes.page_info(connection.get("pageInfo")),
    }


def _get_product(context: _Context) -> dict[str, Any]:
    requested = context.operation_input["product_id"]
    node = _requested_node(
        context.execute({"id": requested}),
        "product",
        expected_type=gids.PRODUCT,
        expected=requested,
        what="product",
    )
    return {"product": shapes.product(node)}


def _list_product_variants(context: _Context) -> dict[str, Any]:
    data = context.execute(_page(context.operation_input))
    connection = shapes.mapping(data.get("productVariants"))
    return {
        "product_variants": [shapes.product_variant(n) for n in shapes.nodes(connection)],
        "page_info": shapes.page_info(connection.get("pageInfo")),
    }


def _get_product_variant(context: _Context) -> dict[str, Any]:
    requested = context.operation_input["product_variant_id"]
    node = _requested_node(
        context.execute({"id": requested}),
        "productVariant",
        expected_type=gids.PRODUCT_VARIANT,
        expected=requested,
        what="product variant",
    )
    return {"product_variant": shapes.product_variant(node)}


def _list_catalog_metafields(context: _Context) -> dict[str, Any]:
    operation_input = context.operation_input
    owner_id = operation_input["owner_id"]
    owner_type = operation_input["owner_type"]
    data = context.execute({"id": owner_id, **_page(operation_input)})
    _requested_node(
        data,
        "node",
        expected_type=gids.CATALOG_METAFIELD_OWNERS[owner_type],
        expected=owner_id,
        what="record",
    )
    node = shapes.mapping(data.get("node"))
    connection = shapes.mapping(node.get("metafields"))
    return {
        "owner_id": owner_id,
        "owner_type": owner_type,
        "metafields": [
            shapes.metafield(entry, owner_id=owner_id) for entry in shapes.nodes(connection)
        ],
        "page_info": shapes.page_info(connection.get("pageInfo")),
    }


def _list_product_media(context: _Context) -> dict[str, Any]:
    operation_input = context.operation_input
    product_id = operation_input["product_id"]
    data = context.execute({"id": product_id, **_page(operation_input)})
    node = _requested_node(
        data, "product", expected_type=gids.PRODUCT, expected=product_id, what="product"
    )
    connection = shapes.mapping(node.get("media"))
    return {
        "product_id": product_id,
        "media": [shapes.product_media(entry) for entry in shapes.nodes(connection)],
        "page_info": shapes.page_info(connection.get("pageInfo")),
    }


# -- Order sources ----------------------------------------------------------


def _list_orders(context: _Context) -> dict[str, Any]:
    data = context.execute(_page(context.operation_input))
    connection = shapes.mapping(data.get("orders"))
    return {
        "orders": [shapes.order(node) for node in shapes.nodes(connection)],
        "page_info": shapes.page_info(connection.get("pageInfo")),
    }


def _get_order(context: _Context) -> dict[str, Any]:
    requested = context.operation_input["order_id"]
    node = _requested_node(
        context.execute({"id": requested}),
        "order",
        expected_type=gids.ORDER,
        expected=requested,
        what="order",
    )
    return {"order": shapes.order(node)}


def _order_connection(context: _Context, field: str, extra: Mapping[str, Any] | None = None):
    """One paginated sub-connection of one order, or ``not_found``."""
    operation_input = context.operation_input
    order_id = operation_input["order_id"]
    variables = {"id": order_id, **_page(operation_input), **(extra or {})}
    node = _requested_node(
        context.execute(variables),
        "order",
        expected_type=gids.ORDER,
        expected=order_id,
        what="order",
    )
    return order_id, node, shapes.mapping(node.get(field))


def _list_order_line_items(context: _Context) -> dict[str, Any]:
    order_id, _node, connection = _order_connection(context, "lineItems")
    return {
        "order_id": order_id,
        "line_items": [shapes.order_line_item(n) for n in shapes.nodes(connection)],
        "page_info": shapes.page_info(connection.get("pageInfo")),
    }


def _list_order_metafields(context: _Context) -> dict[str, Any]:
    order_id, _node, connection = _order_connection(context, "metafields")
    return {
        "order_id": order_id,
        "metafields": [
            shapes.metafield(entry, owner_id=order_id) for entry in shapes.nodes(connection)
        ],
        "page_info": shapes.page_info(connection.get("pageInfo")),
    }


def _list_order_fulfillment_orders(context: _Context) -> dict[str, Any]:
    order_id, _node, connection = _order_connection(
        context,
        "fulfillmentOrders",
        {
            "lineItemsFirst": context.operation_input["line_items_first"],
            "displayable": bool(context.operation_input.get("displayable", False)),
        },
    )
    return {
        "order_id": order_id,
        "fulfillment_orders": [shapes.fulfillment_order(n) for n in shapes.nodes(connection)],
        "page_info": shapes.page_info(connection.get("pageInfo")),
    }


def _get_fulfillment_order(context: _Context) -> dict[str, Any]:
    operation_input = context.operation_input
    data = context.execute(
        {
            "id": operation_input["fulfillment_order_id"],
            "lineItemsFirst": operation_input["line_items_first"],
            "lineItemsAfter": operation_input.get("line_items_after"),
        }
    )
    node = _requested_node(
        data,
        "fulfillmentOrder",
        expected_type=gids.FULFILLMENT_ORDER,
        expected=operation_input["fulfillment_order_id"],
        what="fulfillment order",
    )
    return {"fulfillment_order": shapes.fulfillment_order(node)}


def _list_order_fulfillments(context: _Context) -> dict[str, Any]:
    """Return the page asked for, plus the store's own total.

    `Order.fulfillments` is a plain list with a `first` ceiling rather than a
    cursor connection, so a caller cannot page through it. Reporting the store's
    own count alongside the returned rows is what lets them tell a complete
    answer from a clipped one instead of guessing.
    """
    operation_input = context.operation_input
    order_id = operation_input["order_id"]
    data = context.execute(
        {
            "id": order_id,
            "first": operation_input["first"],
            "query": operation_input.get("filter"),
            "trackingFirst": documents.TRACKING_INFO_LIMIT,
        }
    )
    node = _requested_node(data, "order", expected_type=gids.ORDER, expected=order_id, what="order")
    entries = node.get("fulfillments")
    entries = entries if isinstance(entries, list) else []
    shaped = [shapes.fulfillment(e) for e in entries if isinstance(e, Mapping)]
    total = shapes.optional_int(shapes.mapping(node.get("fulfillmentsCount")).get("count"))
    return {
        "order_id": order_id,
        "fulfillments": shaped,
        "total_count": total,
        "truncated": total is not None and total > len(shaped),
    }


# -- Catalog mutations ------------------------------------------------------


def _create_product(context: _Context) -> dict[str, Any]:
    """Create the product and every variant in one atomic ``productSet`` call.

    Images held as artifacts are staged first; nothing in the store changes
    until the single mutation, so a staging failure leaves no product behind.
    """
    operation_input = context.operation_input
    variables = create_product_variables(operation_input, staged_images=context.staged_images())
    data = context.execute(variables, mutating=True)
    record = _confirmed(data, "productSet", "product")
    product_id = _confirmed_id(record, expected_type=gids.PRODUCT)
    expected = variables["variantsFirst"]
    variants = shapes.nodes(record.get("variants"), limit=expected)
    if len(variants) != expected:
        raise ExtensionError(
            errors.TIMEOUT_UNKNOWN,
            "Shopify created the product without confirming every variant",
        )
    for variant in variants:
        _confirmed_id(variant, expected_type=gids.PRODUCT_VARIANT)
        _confirmed_id(
            shapes.mapping(variant.get("product")),
            expected_type=gids.PRODUCT,
            expected=product_id,
        )
        _confirmed_id(
            shapes.mapping(variant.get("inventoryItem")),
            expected_type=gids.INVENTORY_ITEM,
        )
    return {
        "product": shapes.product(record),
        "product_variants": [shapes.product_variant(variant) for variant in variants],
    }


def _update_product(context: _Context) -> dict[str, Any]:
    """Change one product, named by id, handle or unique metafield value.

    When the product was named by id, Shopify must confirm that same id; when
    by handle, the confirmed product must carry that handle (or the new one the
    call asked for). Anything else is a different record, reported as unknown.
    """
    operation_input = context.operation_input
    variables = product_update_variables(operation_input, staged_images=context.staged_images())
    data = context.execute(variables, mutating=True)
    record = _confirmed(data, "productUpdate", "product")
    _confirmed_id(
        record,
        expected_type=gids.PRODUCT,
        expected=str(operation_input.get("product_id") or ""),
    )
    if "product_handle" in operation_input and record.get("handle") not in (
        operation_input["product_handle"],
        operation_input.get("handle"),
    ):
        raise ExtensionError(
            errors.TIMEOUT_UNKNOWN, "Shopify confirmed a different product than the one requested"
        )
    return {"product": shapes.product(record)}


def _create_product_variants_batch(context: _Context) -> dict[str, Any]:
    operation_input = context.operation_input
    data = context.execute(
        {
            "productId": operation_input["product_id"],
            "variants": [variant_bulk_input(entry) for entry in operation_input["variants"]],
            "media": _create_media(operation_input),
            "strategy": operation_input["strategy"],
        },
        mutating=True,
    )
    records = _confirmed_list(data, "productVariantsBulkCreate", "productVariants")
    # Created variants have no caller-supplied id to match on, so they come back
    # as an unordered list carrying the ids Shopify assigned. Attaching input
    # positions here would invent a correspondence Shopify never stated — but
    # "no correspondence" is not "no check": one variant requested and an empty
    # list returned was being reported as success, which is the one answer this
    # operation must never give.
    _confirmed_count(
        records,
        expected_type=gids.PRODUCT_VARIANT,
        expected=len(operation_input["variants"]),
        product_id=operation_input["product_id"],
    )
    return {"product_variants": [shapes.product_variant(record) for record in records]}


def _update_product_variants_batch(context: _Context) -> dict[str, Any]:
    operation_input = context.operation_input
    requested = [entry["variant_id"] for entry in operation_input["variants"]]
    data = context.execute(
        {
            "productId": operation_input["product_id"],
            "variants": [variant_bulk_input(entry) for entry in operation_input["variants"]],
            "media": _create_media(operation_input),
            "allowPartialUpdates": bool(operation_input["allow_partial_updates"]),
        },
        mutating=True,
    )
    records = _confirmed_list(data, "productVariantsBulkUpdate", "productVariants")
    ordered = _confirmed_by_id(records, expected_type=gids.PRODUCT_VARIANT, requested=requested)
    _assert_same_product(ordered, operation_input["product_id"])
    return {"product_variants": [shapes.product_variant(record) for record in ordered]}


def _create_media(operation_input: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    media = operation_input.get("media")
    if not media:
        return None
    return [create_media_input(item) for item in media]


def _metafields_variables(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "metafields": [
            {
                "ownerId": entry["owner_id"],
                "namespace": entry["namespace"],
                "key": entry["key"],
                "type": entry["type"],
                "value": entry["value"],
                "compareDigest": entry["compare_digest"],
            }
            for entry in entries
        ]
    }


def _set_metafields(context: _Context) -> dict[str, Any]:
    entries = context.operation_input["metafields"]
    data = context.execute(_metafields_variables(entries), mutating=True)
    return {"metafields": _confirmed_metafields(data, entries)}


def _update_product_media(context: _Context) -> dict[str, Any]:
    operation_input = context.operation_input
    media_id = operation_input["media_id"]
    built: dict[str, Any] = {"id": media_id}
    for source, target in (
        ("alt", "alt"),
        ("source_url", "originalSource"),
        ("preview_image_url", "previewImageSource"),
        ("filename", "filename"),
    ):
        if source in operation_input:
            built[target] = operation_input[source]
    if "add_to_product_ids" in operation_input:
        built["referencesToAdd"] = list(operation_input["add_to_product_ids"])
    if "remove_from_product_ids" in operation_input:
        built["referencesToRemove"] = list(operation_input["remove_from_product_ids"])
    data = context.execute({"files": [built]}, mutating=True)
    records = _confirmed_list(data, "fileUpdate", "files")
    ordered = _confirmed_by_id(
        records, expected_type=_media_type_of(media_id), requested=[media_id]
    )
    return {"file": shapes.media_file(ordered[0])}


# -- Order mutations --------------------------------------------------------


_ORDER_FIELDS: tuple[tuple[str, str], ...] = (
    ("note", "note"),
    ("po_number", "poNumber"),
    ("email", "email"),
    ("phone", "phone"),
)

_ADDRESS_FIELDS: tuple[tuple[str, str], ...] = (
    ("first_name", "firstName"),
    ("last_name", "lastName"),
    ("company", "company"),
    ("address1", "address1"),
    ("address2", "address2"),
    ("city", "city"),
    ("province_code", "provinceCode"),
    ("zip", "zip"),
    ("country_code", "countryCode"),
    ("phone", "phone"),
)


def _update_order_metadata(context: _Context) -> dict[str, Any]:
    operation_input = context.operation_input
    order_id = operation_input["order_id"]
    built: dict[str, Any] = {"id": order_id}
    for source, target in _ORDER_FIELDS:
        if source in operation_input:
            built[target] = operation_input[source]
    if "replace_tags" in operation_input:
        built["tags"] = list(operation_input["replace_tags"])
    if "replace_custom_attributes" in operation_input:
        built["customAttributes"] = [
            {"key": entry["key"], "value": entry["value"]}
            for entry in operation_input["replace_custom_attributes"]
        ]
    address = operation_input.get("shipping_address")
    if isinstance(address, Mapping):
        built["shippingAddress"] = {
            target: address[source] for source, target in _ADDRESS_FIELDS if source in address
        }
    if "metafields" in operation_input:
        built["metafields"] = [metafield_input(entry) for entry in operation_input["metafields"]]
    if "localized_fields" in operation_input:
        built["localizedFields"] = [
            {"key": entry["key"], "value": entry["value"]}
            for entry in operation_input["localized_fields"]
        ]
    data = context.execute({"input": built}, mutating=True)
    record = _confirmed(data, "orderUpdate", "order")
    _confirmed_id(record, expected_type=gids.ORDER, expected=order_id)
    return {"order": shapes.order(record)}


def _tracking_variables(tracking: Mapping[str, Any]) -> dict[str, Any]:
    built: dict[str, Any] = {}
    if "company" in tracking:
        built["company"] = tracking["company"]
    if "numbers" in tracking:
        built["numbers"] = list(tracking["numbers"])
    if "urls" in tracking:
        built["urls"] = list(tracking["urls"])
    return built


def _create_fulfillment(context: _Context) -> dict[str, Any]:
    operation_input = context.operation_input
    fulfillment: dict[str, Any] = {
        # Always explicit. Shopify fulfils everything remaining when the line
        # items are omitted, and an omitted field must not be able to ship goods.
        "lineItemsByFulfillmentOrder": [
            {
                "fulfillmentOrderId": group["fulfillment_order_id"],
                "fulfillmentOrderLineItems": [
                    {"id": line["fulfillment_order_line_item_id"], "quantity": line["quantity"]}
                    for line in group["line_items"]
                ],
            }
            for group in operation_input["fulfillment_orders"]
        ],
        # Always explicit too: the customer is emailed only when asked for.
        "notifyCustomer": bool(operation_input.get("notify_customer", documents.NOTIFY_CUSTOMER)),
    }
    if "tracking" in operation_input:
        fulfillment["trackingInfo"] = _tracking_variables(operation_input["tracking"])
    origin = operation_input.get("origin_address")
    if isinstance(origin, Mapping):
        fulfillment["originAddress"] = {
            target: origin[source]
            for source, target in (
                ("address1", "address1"),
                ("address2", "address2"),
                ("city", "city"),
                ("zip", "zip"),
                ("province_code", "provinceCode"),
                ("country_code", "countryCode"),
            )
            if source in origin
        }
    data = context.execute(
        {
            "fulfillment": fulfillment,
            "message": operation_input.get("message"),
            "trackingFirst": documents.TRACKING_INFO_LIMIT,
        },
        mutating=True,
    )
    record = _confirmed(data, "fulfillmentCreate", "fulfillment")
    _confirmed_id(record, expected_type=gids.FULFILLMENT)
    return {"fulfillment": shapes.fulfillment(record)}


def _update_fulfillment_tracking(context: _Context) -> dict[str, Any]:
    operation_input = context.operation_input
    fulfillment_id = operation_input["fulfillment_id"]
    data = context.execute(
        {
            "fulfillmentId": fulfillment_id,
            "trackingInfoInput": _tracking_variables(operation_input["tracking"]),
            "notifyCustomer": bool(
                operation_input.get("notify_customer", documents.NOTIFY_CUSTOMER)
            ),
            "trackingFirst": documents.TRACKING_INFO_LIMIT,
        },
        mutating=True,
    )
    record = _confirmed(data, "fulfillmentTrackingInfoUpdate", "fulfillment")
    _confirmed_id(record, expected_type=gids.FULFILLMENT, expected=fulfillment_id)
    return {"fulfillment": shapes.fulfillment(record)}


# -- Result shaping -------------------------------------------------------


def _nodes(connection: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    nodes = connection.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [node for node in nodes[:MAX_RETURNED_NODES] if isinstance(node, Mapping)]


def _page_info(value: Any) -> dict[str, Any]:
    page_info = value if isinstance(value, Mapping) else {}
    return {
        "has_next_page": bool(page_info.get("hasNextPage", False)),
        "end_cursor": _optional_text(page_info.get("endCursor")),
    }


def _inventory_level(value: Any, *, include_inactive: bool) -> dict[str, Any] | None:
    """One level, or ``None`` when the item is not stocked at that location."""
    if not isinstance(value, Mapping):
        return None
    location = value.get("location")
    location = location if isinstance(location, Mapping) else {}
    is_active = _optional_bool(location.get("isActive"))
    if is_active is False and not include_inactive:
        return None
    quantities = _quantities_by_name(value.get("quantities"))
    return {
        "id": _text(value.get("id")),
        "location_id": _optional_text(location.get("id")),
        "is_active": is_active,
        "level_is_active": _optional_bool(value.get("isActive")),
        "can_deactivate": _optional_bool(value.get("canDeactivate")),
        "deactivation_alert": _optional_text(value.get("deactivationAlert")),
        "created_at": _optional_text(value.get("createdAt")),
        "updated_at": _optional_text(value.get("updatedAt")),
        **{name: quantities.get(name) for name in documents.READ_QUANTITY_NAMES},
    }


def _quantities_by_name(value: Any) -> dict[str, int | None]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return {}
    mapped: dict[str, int | None] = {}
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        name = entry.get("name")
        if isinstance(name, str) and name:
            mapped[name] = _optional_int(entry.get("quantity"))
    return mapped


def _is_inventory_item(node: Mapping[str, Any]) -> bool:
    """Whether the node Shopify returned really is an inventory item."""
    typename = node.get("__typename")
    if isinstance(typename, str) and typename != gids.INVENTORY_ITEM:
        return False
    return gids.is_gid(node.get("id"), expected_type=gids.INVENTORY_ITEM)


#: The inventory handlers were written before `runtime/shapes.py` existed and
#: carried their own copies of these. They are aliases now, so there is one
#: answer to "does this clip?" for the whole extension, and it is no.
_text = shapes.text
_optional_text = shapes.optional_text
_optional_bool = shapes.optional_bool
_optional_int = shapes.optional_int


# -- Response envelopes ---------------------------------------------------


def _ok(result: Mapping[str, Any]) -> dict[str, Any]:
    response: dict[str, Any] = {
        "ok": True,
        "result": dict(result),
        "error_code": None,
        "error": None,
        "errors": [],
    }
    if "external_effect_status" in result:
        response["external_effect_status"] = result["external_effect_status"]
        response["definitely_no_external_effect"] = result["definitely_no_external_effect"]
    return response


#: Every routable operation other than the two the dispatcher handles itself.
#: A row without an entry here cannot run, which is the same closed-registry
#: rule the dispatcher applies one level up.
_HANDLERS: dict[str, Callable[[_Context], dict[str, Any]]] = {
    "get_shop": _get_shop,
    "list_locations": _list_locations,
    "list_inventory_items": _list_inventory_items,
    "get_inventory_item": _get_inventory_item,
    "get_inventory_levels_batch": _inventory_levels_batch,
    "list_products": _list_products,
    "get_product": _get_product,
    "list_product_variants": _list_product_variants,
    "get_product_variant": _get_product_variant,
    "list_catalog_metafields": _list_catalog_metafields,
    "list_product_media": _list_product_media,
    "create_product": _create_product,
    "update_product": _update_product,
    "create_product_variants_batch": _create_product_variants_batch,
    "update_product_variants_batch": _update_product_variants_batch,
    "set_catalog_metafields": _set_metafields,
    "update_product_media": _update_product_media,
    "list_orders": _list_orders,
    "get_order": _get_order,
    "list_order_line_items": _list_order_line_items,
    "list_order_metafields": _list_order_metafields,
    "list_order_fulfillment_orders": _list_order_fulfillment_orders,
    "get_fulfillment_order": _get_fulfillment_order,
    "list_order_fulfillments": _list_order_fulfillments,
    "update_order_metadata": _update_order_metadata,
    "set_order_metafields": _set_metafields,
    "create_fulfillment": _create_fulfillment,
    "update_fulfillment_tracking": _update_fulfillment_tracking,
}


__all__ = ["handle_runtime"]
