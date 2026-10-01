"""Stable, safe error vocabulary for the Shopify extension.

Every failure the runtime can produce maps to exactly one of these codes. No
message carries the access token, an authorization header, a secret
reference, or unbounded upstream content: Shopify's own text is never echoed,
only classified.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_MESSAGE_SHOPIFY_COULD_NOT_COMPLETE_THE_REQUEST = "Shopify could not complete the request"
_MESSAGE_THE_OUTCOME_OF_THIS_REQUEST_IS_UNKNOWN = "The outcome of this request is unknown"

INVALID_PAYLOAD = "invalid_payload"
INVALID_CONFIGURATION = "invalid_configuration"
INVALID_CONNECTION = "invalid_connection"
#: The connection exists but holds no usable grant any more. Distinct from a
#: malformed connection, because the answer is "authorize again", not "fix it".
REAUTHORIZATION_REQUIRED = "reauthorization_required"
UNSUPPORTED_OPERATION = "unsupported_operation"
MISSING_IDEMPOTENCY_KEY = "missing_idempotency_key"
AUTHENTICATION_FAILED = "authentication_failed"
AUTHORIZATION_FAILED = "authorization_failed"
MISSING_REQUIRED_SCOPE = "missing_required_scope"
SHOP_DOMAIN_MISMATCH = "shop_domain_mismatch"
SHOP_INACTIVE = "shop_inactive"
NOT_FOUND = "not_found"
RATE_LIMITED = "rate_limited"
UPSTREAM_VALIDATION_FAILED = "upstream_validation_failed"
UPSTREAM_FAILURE = "upstream_failure"
INVALID_JSON_RESPONSE = "invalid_json_response"
RESPONSE_TOO_LARGE = "response_too_large"
ARTIFACT_OUTPUT_UNAVAILABLE = "artifact_output_unavailable"
TIMEOUT = "timeout"
CONNECTION_FAILED = "connection_failed"
REDIRECT_REJECTED = "redirect_rejected"
BLOCKED_ADDRESS = "blocked_address"
TIMEOUT_UNKNOWN = "timeout_unknown"
INTERNAL_ERROR = "internal_error"

SAFE_ERROR_CODES: tuple[str, ...] = (
    INVALID_PAYLOAD,
    INVALID_CONFIGURATION,
    INVALID_CONNECTION,
    REAUTHORIZATION_REQUIRED,
    UNSUPPORTED_OPERATION,
    MISSING_IDEMPOTENCY_KEY,
    AUTHENTICATION_FAILED,
    AUTHORIZATION_FAILED,
    MISSING_REQUIRED_SCOPE,
    SHOP_DOMAIN_MISMATCH,
    SHOP_INACTIVE,
    NOT_FOUND,
    RATE_LIMITED,
    UPSTREAM_VALIDATION_FAILED,
    UPSTREAM_FAILURE,
    INVALID_JSON_RESPONSE,
    RESPONSE_TOO_LARGE,
    ARTIFACT_OUTPUT_UNAVAILABLE,
    TIMEOUT,
    CONNECTION_FAILED,
    REDIRECT_REJECTED,
    BLOCKED_ADDRESS,
    TIMEOUT_UNKNOWN,
    INTERNAL_ERROR,
)

#: Codes that leave a mutation's outcome unknown to the caller.
AMBIGUOUS_ERROR_CODES: frozenset[str] = frozenset({TIMEOUT_UNKNOWN})

#: Codes any Shopify-contacting operation can raise. Operation rows extend this
#: with the codes only they can produce.
TRANSPORT_ERROR_CODES: tuple[str, ...] = (
    INVALID_PAYLOAD,
    INVALID_CONFIGURATION,
    INVALID_CONNECTION,
    UNSUPPORTED_OPERATION,
    AUTHENTICATION_FAILED,
    AUTHORIZATION_FAILED,
    NOT_FOUND,
    RATE_LIMITED,
    SHOP_INACTIVE,
    UPSTREAM_VALIDATION_FAILED,
    UPSTREAM_FAILURE,
    INVALID_JSON_RESPONSE,
    RESPONSE_TOO_LARGE,
    TIMEOUT,
    CONNECTION_FAILED,
    REDIRECT_REJECTED,
    BLOCKED_ADDRESS,
    INTERNAL_ERROR,
)


class ExtensionError(Exception):
    """A failure already reduced to a safe code and a safe message."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        failure_class: str | None = None,
        retryable: bool | None = None,
        retry_after_seconds: float | None = None,
        definitely_no_external_effect: bool | None = None,
        external_effect_status: str | None = None,
        http_status: int | None = None,
    ) -> None:
        safe_code = code if code in SAFE_ERROR_CODES else INTERNAL_ERROR
        super().__init__(message)
        self.code = safe_code
        self.message = message
        self.failure_class = failure_class
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.definitely_no_external_effect = definitely_no_external_effect
        self.external_effect_status = external_effect_status
        self.http_status = http_status

    def retry_facts(self) -> dict[str, object]:
        """Project only closed, non-secret facts understood by Core."""
        facts: dict[str, object] = {}
        for key in (
            "failure_class",
            "retryable",
            "retry_after_seconds",
            "definitely_no_external_effect",
            "external_effect_status",
            "http_status",
        ):
            value = getattr(self, key)
            if value is not None:
                facts[key] = value
        if self.failure_class in {"provider", "transient"}:
            facts["provider_error_code"] = self.code
        return facts


def error_response(
    code: str,
    message: str,
    *,
    retry_facts: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the failing runtime envelope for one safe error."""
    safe_code = code if code in SAFE_ERROR_CODES else INTERNAL_ERROR
    response: dict[str, object] = {
        "ok": False,
        "result": {},
        "error_code": safe_code,
        "error": message,
        "errors": [{"code": safe_code, "message": message}],
    }
    if safe_code in AMBIGUOUS_ERROR_CODES:
        response["external_effect_status"] = TIMEOUT_UNKNOWN
        response["definitely_no_external_effect"] = False
    if retry_facts:
        response.update(retry_facts)
    return response


def classify_status(status: int, *, mutating: bool) -> tuple[str, str]:
    """Map one Shopify HTTP status onto a safe code and a safe message.

    Shopify answers a frozen or otherwise unavailable shop with 402 or 423, and
    an over-budget app with 429. A 5xx after a mutation has been sent leaves the
    outcome unknown, so it is reported as such rather than as a plain failure.
    """
    if 300 <= status < 400:
        return REDIRECT_REJECTED, "Shopify redirected the request and it was not followed"
    if status == 401:
        return AUTHENTICATION_FAILED, "Shopify rejected this connection's access token"
    if status == 403:
        return AUTHORIZATION_FAILED, "This connection's granted scopes do not allow this"
    if status in {402, 423}:
        return SHOP_INACTIVE, "The Shopify store is not currently available"
    if status == 404:
        return NOT_FOUND, "Shopify does not expose the requested endpoint"
    if status == 429:
        return RATE_LIMITED, "Shopify is rate limiting requests"
    if status in {400, 409, 422}:
        return UPSTREAM_VALIDATION_FAILED, "Shopify rejected the request as invalid"
    if status in {408, 500, 502, 503, 504} and mutating:
        return TIMEOUT_UNKNOWN, _MESSAGE_THE_OUTCOME_OF_THIS_REQUEST_IS_UNKNOWN
    return UPSTREAM_FAILURE, _MESSAGE_SHOPIFY_COULD_NOT_COMPLETE_THE_REQUEST


#: Top-level GraphQL error codes Shopify documents, mapped onto this
#: extension's vocabulary. Shopify returns several of these with HTTP 200.
GRAPHQL_ERROR_CODES: dict[str, tuple[str, str]] = {
    "THROTTLED": (RATE_LIMITED, "Shopify is rate limiting requests"),
    "ACCESS_DENIED": (AUTHORIZATION_FAILED, "This connection's granted scopes do not allow this"),
    "UNAUTHORIZED": (AUTHENTICATION_FAILED, "Shopify rejected this connection's access token"),
    "SHOP_INACTIVE": (SHOP_INACTIVE, "The Shopify store is not currently available"),
    "INTERNAL_SERVER_ERROR": (UPSTREAM_FAILURE, _MESSAGE_SHOPIFY_COULD_NOT_COMPLETE_THE_REQUEST),
    "MAX_COST_EXCEEDED": (UPSTREAM_VALIDATION_FAILED, "Shopify rejected the request as too costly"),
}


def classify_graphql_error(code: Any, *, mutating: bool) -> tuple[str, str]:
    """Map one top-level GraphQL error code onto a safe code and message."""
    key = code.strip().upper() if isinstance(code, str) else ""
    mapped = GRAPHQL_ERROR_CODES.get(key)
    if mapped is None:
        # An error this extension does not recognise says nothing about whether
        # the mutation ran. Reporting a plain failure would be a guess in the
        # one direction a caller cannot recover from.
        if mutating:
            return TIMEOUT_UNKNOWN, _MESSAGE_THE_OUTCOME_OF_THIS_REQUEST_IS_UNKNOWN
        return UPSTREAM_FAILURE, _MESSAGE_SHOPIFY_COULD_NOT_COMPLETE_THE_REQUEST
    safe_code, message = mapped
    if safe_code == UPSTREAM_FAILURE and mutating:
        return TIMEOUT_UNKNOWN, _MESSAGE_THE_OUTCOME_OF_THIS_REQUEST_IS_UNKNOWN
    return safe_code, message


__all__ = [
    "AMBIGUOUS_ERROR_CODES",
    "GRAPHQL_ERROR_CODES",
    "SAFE_ERROR_CODES",
    "TRANSPORT_ERROR_CODES",
    "ExtensionError",
    "classify_graphql_error",
    "classify_status",
    "error_response",
]
