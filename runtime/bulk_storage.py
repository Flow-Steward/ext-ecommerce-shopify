"""Pinned, bounded Shopify staged upload without Admin API credentials."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request
from uuid import uuid4

from flowsteward_extension_sdk import open_pinned_url

from . import errors
from .errors import ExtensionError

MAX_BULK_BYTES = 100_000_000
_PARAM_NAME = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
_INVALID_UPLOAD_PARAMETERS = "Shopify returned invalid upload parameters"


def _upload_url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 16384:
        raise ExtensionError(errors.UPSTREAM_FAILURE, "Shopify returned an invalid storage URL")
    parsed = urlsplit(value)
    valid_host = parsed.hostname == "shopify-staged-uploads.storage.googleapis.com"
    if (
        parsed.scheme != "https"
        or not valid_host
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ExtensionError(errors.UPSTREAM_FAILURE, "Shopify returned an unsupported storage URL")
    return value


def upload_jsonl(
    target: Mapping[str, Any], body: bytes, *, opener: Callable[..., Any] = open_pinned_url
) -> str:
    """Upload a bulk JSONL body once; return its staged key."""
    return upload_staged(
        target,
        body,
        filename="products.jsonl",
        content_type="text/jsonl",
        key_marker="/bulk/",
        purpose="Shopify bulk staged upload",
        opener=opener,
    )


def upload_staged(
    target: Mapping[str, Any],
    body: bytes,
    *,
    filename: str,
    content_type: str,
    key_marker: str,
    purpose: str,
    opener: Callable[..., Any] = open_pinned_url,
) -> str:
    """Upload once to a Shopify-issued signed target; return its staged key.

    The target URL must be Shopify's staged-upload storage host, and the form
    parameters are exactly the ones Shopify issued — the file itself is the only
    part this side adds.
    """
    url = _upload_url(target.get("url"))
    params = target.get("parameters")
    if not isinstance(params, list) or not 1 <= len(params) <= 30:
        raise ExtensionError(errors.UPSTREAM_FAILURE, _INVALID_UPLOAD_PARAMETERS)
    boundary = "fs-shopify-" + uuid4().hex
    parts: list[bytes] = []
    values: dict[str, str] = {}
    for param in params:
        if not isinstance(param, Mapping):
            raise ExtensionError(errors.UPSTREAM_FAILURE, _INVALID_UPLOAD_PARAMETERS)
        name, value = param.get("name"), param.get("value")
        if (
            not isinstance(name, str)
            or not _PARAM_NAME.fullmatch(name)
            or name in values
            or name == "file"
            or not isinstance(value, str)
            or len(value) > 65536
        ):
            raise ExtensionError(errors.UPSTREAM_FAILURE, _INVALID_UPLOAD_PARAMETERS)
        values[name] = value
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    key = values.get("key", "")
    if not key.startswith("tmp/") or key_marker not in key or ".." in key or len(key) > 2048:
        raise ExtensionError(errors.UPSTREAM_FAILURE, "Shopify returned an invalid staged path")
    prefix = (
        b"".join(parts)
        + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode()
    )
    suffix = f"\r\n--{boundary}--\r\n".encode()
    request = Request(
        url,
        data=iter((prefix, body, suffix)),
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(prefix) + len(body) + len(suffix)),
        },
    )
    try:
        with opener(request, timeout_seconds=60.0, purpose=purpose) as response:
            if int(response.status) not in (200, 201, 204):
                raise ExtensionError(
                    errors.UPSTREAM_FAILURE, "Shopify staged upload was not accepted"
                )
    except ExtensionError:
        raise
    except Exception as exc:
        raise ExtensionError(
            errors.CONNECTION_FAILED,
            "Shopify staged upload could not be completed",
            definitely_no_external_effect=True,
            retryable=True,
        ) from exc
    return key


def staged_resource_url(value: Any) -> str:
    """The ``resourceUrl`` Shopify returned, held to the same storage host."""
    return _upload_url(value)
