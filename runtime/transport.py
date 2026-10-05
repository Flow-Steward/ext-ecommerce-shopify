"""The only way this extension reaches Shopify.

One POST, to one URL, carrying one of the fixed documents in
``runtime/documents.py`` plus its variables. The URL is built from the
connection's canonical shop domain and the pinned API version; it is never taken
from workflow input, and the transport refuses to send a request whose URL is
not exactly the endpoint it computed for itself.

Every request goes out through the public Flow Steward extension SDK, which
performs URL validation, DNS/IP pinning, connected-peer verification, redirect
rejection and timeout enforcement. This module adds no bypass and no local
override: there is no ``urlopen``, no ``requests``, no ``httpx``, and no Shopify
Python SDK anywhere in the bundle. Note that the SDK's address policy derives
from ``ipaddress.is_global``, which admits multicast literals; that gap is a
reported Core issue and is deliberately not worked around here.

Shopify answers some failures with HTTP 200 and a top-level ``errors`` array —
throttling in particular — so a 200 is not treated as success until the body has
been inspected.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

from flowsteward_extension_sdk import PinnedPeerError, open_pinned_url, parse_retry_after

from . import errors
from .connection import Connection, assert_shop_domain_allowed
from .documents import API_VERSION
from .errors import ExtensionError

_MESSAGE_SHOPIFY_RETURNED_A_RESPONSE_THAT_IS_NOT_VALID_JSON = (
    "Shopify returned a response that is not valid JSON"
)

DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_TIMEOUT_SECONDS = 30.0
MAX_REQUEST_BODY_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_ERROR_BODY_BYTES = 16 * 1024
CHUNK_BYTES = 64 * 1024

_USER_AGENT = "FlowSteward-Shopify/0.4"


@dataclass(frozen=True)
class GraphQLResult:
    """One validated GraphQL response body."""

    status: int
    data: dict[str, Any]


class ShopifyGraphQLTransport:
    """Issues exactly the request one declared operation describes."""

    def __init__(
        self,
        connection: Connection,
        *,
        opener: Callable[..., Any] = open_pinned_url,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._connection = connection
        self._opener = opener
        self._timeout_seconds = max(1.0, min(float(timeout_seconds), MAX_TIMEOUT_SECONDS))

    @property
    def endpoint(self) -> str:
        return self._connection.graphql_endpoint

    def execute(
        self,
        document: str,
        variables: Mapping[str, Any],
        *,
        mutating: bool,
        purpose: str,
    ) -> GraphQLResult:
        """Send one fixed document with its variables and return the ``data`` object."""
        url = self._connection.graphql_endpoint
        _assert_endpoint(url, self._connection.shop_domain)
        assert_shop_domain_allowed(self._connection.shop_domain)
        body = _json_bytes({"query": document, "variables": dict(variables)})
        request = Request(
            url,
            method="POST",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": _USER_AGENT,
                **self._connection.authorization_headers(),
            },
        )
        status, raw = self._open(request, mutating=mutating, purpose=purpose)
        payload = _decode_json(raw, mutating=mutating)
        return GraphQLResult(status=status, data=_graphql_data(payload, mutating=mutating))

    def _open(self, request: Request, *, mutating: bool, purpose: str) -> tuple[int, bytes]:
        try:
            with self._opener(
                request,
                timeout_seconds=self._timeout_seconds,
                purpose=purpose,
            ) as response:
                status = int(getattr(response, "status", 0) or getattr(response, "code", 0) or 0)
                raw = read_bounded(response, MAX_RESPONSE_BYTES, mutating=mutating)
        except HTTPError as exc:
            _drain(exc)
            status = int(exc.code)
            code, message = errors.classify_status(status, mutating=mutating)
            raise ExtensionError(
                code,
                message,
                **_http_failure_facts(
                    status=status,
                    mutating=mutating,
                    retry_after=_retry_after_seconds(exc.headers),
                ),
            ) from exc
        except PinnedPeerError as exc:
            raise ExtensionError(
                errors.BLOCKED_ADDRESS,
                "The store address is not reachable under the host policy",
            ) from exc
        except TimeoutError as exc:
            raise ExtensionError(
                errors.TIMEOUT_UNKNOWN if mutating else errors.TIMEOUT,
                "Shopify did not respond in time",
                **_transport_failure_facts(mutating=mutating),
            ) from exc
        except OSError as exc:
            raise ExtensionError(
                errors.TIMEOUT_UNKNOWN if mutating else errors.CONNECTION_FAILED,
                "Shopify could not be reached",
                **_transport_failure_facts(mutating=mutating),
            ) from exc
        if 300 <= status < 400:
            raise ExtensionError(
                errors.REDIRECT_REJECTED,
                "Shopify redirected the request and it was not followed",
            )
        if status >= 400:
            code, message = errors.classify_status(status, mutating=mutating)
            raise ExtensionError(
                code,
                message,
                **_http_failure_facts(status=status, mutating=mutating),
            )
        return status, raw


def read_bounded(response: Any, limit: int, *, mutating: bool = False) -> bytes:
    """Read at most ``limit`` bytes.

    An oversized answer to a mutation is an unknown outcome, not a clean
    failure: the write may well have happened, and this side simply could not
    read the confirmation.
    """
    buffer = bytearray()
    while True:
        chunk = response.read(min(CHUNK_BYTES, limit + 1 - len(buffer)))
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise ExtensionError(
                errors.TIMEOUT_UNKNOWN if mutating else errors.RESPONSE_TOO_LARGE,
                "The Shopify response exceeds its safe limit",
            )
    return bytes(buffer)


def _decode_json(raw: bytes, *, mutating: bool = False) -> Any:
    """Decode one response body, or classify why it could not be read.

    A body this side cannot parse leaves a mutation's outcome unknown for the
    same reason an oversized one does: Shopify may have applied the write and
    only the confirmation is unreadable.
    """
    code = errors.TIMEOUT_UNKNOWN if mutating else errors.INVALID_JSON_RESPONSE
    if not raw.strip():
        raise ExtensionError(code, _MESSAGE_SHOPIFY_RETURNED_A_RESPONSE_THAT_IS_NOT_VALID_JSON)
    try:
        return json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExtensionError(
            code, _MESSAGE_SHOPIFY_RETURNED_A_RESPONSE_THAT_IS_NOT_VALID_JSON
        ) from exc


def _graphql_data(payload: Any, *, mutating: bool) -> dict[str, Any]:
    """Reduce one GraphQL body to its ``data`` object, or to a safe failure.

    A top-level ``errors`` array is a failure even under HTTP 200 — Shopify
    reports throttling that way — so the array is classified by its documented
    code and the upstream message is discarded rather than echoed.
    """
    if not isinstance(payload, Mapping):
        raise ExtensionError(
            errors.TIMEOUT_UNKNOWN if mutating else errors.INVALID_JSON_RESPONSE,
            _MESSAGE_SHOPIFY_RETURNED_A_RESPONSE_THAT_IS_NOT_VALID_JSON,
        )
    raised = payload.get("errors")
    if isinstance(raised, list) and raised:
        # A recognised code normally says what happened — `THROTTLED` means
        # Shopify refused before doing anything. That reasoning only holds when
        # the response carries no data. Arriving *alongside* a mutation payload,
        # the same code means something ran and the answer is incomplete, and
        # the code no longer describes the outcome. So partial data outranks the
        # code: for a mutation the result is unknown whatever Shopify called it.
        data = payload.get("data")
        partial = isinstance(data, Mapping) and any(value is not None for value in data.values())
        if mutating and partial:
            raise ExtensionError(
                errors.TIMEOUT_UNKNOWN,
                "Shopify answered with both a result and an error; the outcome is unknown",
            )
        provider_code = _first_error_code(raised)
        code, message = errors.classify_graphql_error(provider_code, mutating=mutating)
        definite_refusal = provider_code.strip().upper() in {
            "THROTTLED",
            "ACCESS_DENIED",
            "UNAUTHORIZED",
            "SHOP_INACTIVE",
            "MAX_COST_EXCEEDED",
        }
        raise ExtensionError(
            code,
            message,
            failure_class="provider",
            retryable=code == errors.RATE_LIMITED,
            definitely_no_external_effect=(not mutating or definite_refusal),
            external_effect_status=(
                "failed" if not mutating or definite_refusal else "timeout_unknown"
            ),
        )
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ExtensionError(
            errors.TIMEOUT_UNKNOWN if mutating else errors.UPSTREAM_FAILURE,
            "Shopify returned no data for the request",
        )
    return dict(data)


def _first_error_code(raised: list[Any]) -> str:
    """The documented code carried by the first GraphQL error, if there is one."""
    for entry in raised:
        if not isinstance(entry, Mapping):
            continue
        extensions = entry.get("extensions")
        if isinstance(extensions, Mapping):
            code = extensions.get("code")
            if isinstance(code, str) and code.strip():
                return code
    return ""


def _assert_endpoint(url: str, shop_domain: str) -> None:
    """Refuse to send anywhere but the endpoint this connection computes."""
    expected = f"https://{shop_domain}/admin/api/{API_VERSION}/graphql.json"
    if url != expected:  # pragma: no cover - defensive; the URL has one source
        raise ExtensionError(errors.UNSUPPORTED_OPERATION, "That endpoint is not supported")


def _json_bytes(body: Mapping[str, Any]) -> bytes:
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_REQUEST_BODY_BYTES:
        raise ExtensionError(errors.INVALID_PAYLOAD, "The request body exceeds its safe limit")
    return encoded


def _drain(exc: HTTPError) -> None:
    try:
        exc.read(MAX_ERROR_BODY_BYTES)
    except Exception:  # pragma: no cover - upstream bodies are never echoed
        return


def _retry_after_seconds(headers: Any) -> float | None:
    """Return a positive Retry-After delay without exposing headers."""
    if headers is None:
        return None
    try:
        raw = headers.get("Retry-After")
    except (AttributeError, TypeError, ValueError):
        return None
    return parse_retry_after(raw)


def _http_failure_facts(
    *,
    status: int,
    mutating: bool,
    retry_after: float | None = None,
) -> dict[str, object]:
    retryable_status = status in {408, 429, 500, 502, 503, 504}
    ambiguous = mutating and status in {408, 500, 502, 503, 504}
    facts: dict[str, object] = {
        "failure_class": "provider",
        "retryable": retryable_status and not ambiguous,
        "definitely_no_external_effect": not ambiguous,
        "external_effect_status": "timeout_unknown" if ambiguous else "failed",
        "http_status": status,
    }
    if retry_after is not None:
        facts["retry_after_seconds"] = retry_after
    return facts


def _transport_failure_facts(*, mutating: bool) -> dict[str, object]:
    return {
        "failure_class": "transient",
        "retryable": not mutating,
        "definitely_no_external_effect": not mutating,
        "external_effect_status": "timeout_unknown" if mutating else "failed",
    }


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_REQUEST_BODY_BYTES",
    "MAX_RESPONSE_BYTES",
    "GraphQLResult",
    "ShopifyGraphQLTransport",
    "read_bounded",
]
