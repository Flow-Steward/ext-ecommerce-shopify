"""Project-scoped connection contract: domain normalization and secret handling.

A connection is built from the material the host hydrates for one invocation and
is thrown away when that invocation ends. Nothing here is cached, memoised, or
stored at module level, so two Shopify connections in the same project cannot
see each other's shop or token even when they are used one after the other in
the same worker process.

The store is not configuration. It is the subject Shopify itself confirmed in the
signed authorization callback, and the platform records it as
``connection_config.oauth.subject``; this module reads it back and refuses
anything that is not the canonical form. A workflow can therefore never name the
store it talks to.

The access token is held in a private field of a frozen dataclass and is never
placed in a result, a log line, or an exception message. ``__repr__`` is
overridden so that a stray f-string cannot leak it either.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from flowsteward_extension_sdk import PinnedPeerError, assert_safe_remote_http_url

from . import errors
from .documents import API_VERSION
from .errors import ExtensionError

CONNECTION_TYPE_ID = "shopify_admin"

#: The platform projects OAuth connections as ``{"oauth": {...}}``. Nothing else
#: is expected, and anything else is refused rather than ignored.
CONFIG_FIELDS: frozenset[str] = frozenset({"oauth"})
REQUIRED_CONFIG_FIELDS: frozenset[str] = frozenset({"oauth"})
SECRET_FIELDS: frozenset[str] = frozenset({"access_token"})
REQUIRED_SECRET_FIELDS: frozenset[str] = frozenset({"access_token"})

SHOP_DOMAIN_SUFFIX = ".myshopify.com"
MAX_SHOP_DOMAIN_LENGTH = 255
MAX_SHOP_NAME_LENGTH = 60
MIN_TOKEN_LENGTH = 8
MAX_TOKEN_LENGTH = 512

#: A Shopify store handle: lowercase letters, digits and inner hyphens.
_SHOP_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])?$")

#: Printable, non-space ASCII. A token outside this set could inject a header.
_TOKEN_RE = re.compile(r"^[\x21-\x7e]+$")

_DOMAIN_HELP = (
    "Enter your store as store-name or store-name.myshopify.com, "
    "with no https://, path, port, or query string"
)


@dataclass(frozen=True)
class Connection:
    """One validated project connection to a single Shopify store."""

    connection_id: str
    shop_domain: str
    _access_token: str = field(repr=False)

    @property
    def graphql_endpoint(self) -> str:
        """The only URL this extension ever calls, built from the stored domain.

        The endpoint is never accepted from workflow input: it is derived here
        from the canonical domain and the pinned API version.
        """
        return f"https://{self.shop_domain}/admin/api/{API_VERSION}/graphql.json"

    def authorization_headers(self) -> dict[str, str]:
        """Shopify's Admin API takes the token in its own header, not as a bearer."""
        return {"X-Shopify-Access-Token": self._access_token}

    def __repr__(self) -> str:  # pragma: no cover - defensive, never carries the token
        return f"Connection(connection_id={self.connection_id!r}, shop_domain={self.shop_domain!r})"

    def __str__(self) -> str:  # pragma: no cover - defensive, never carries the token
        return self.__repr__()


def normalize_shop_domain(value: Any) -> str:
    """Reduce a pasted store name to the canonical ``store.myshopify.com`` form.

    Both forms a merchant is likely to have to hand are accepted: the bare store
    handle from the admin URL, and the full ``.myshopify.com`` domain. Anything
    that carries more than a hostname — a scheme, a path, a port, credentials, a
    query string, a fragment, whitespace, a wildcard — is refused rather than
    trimmed, because silently discarding part of what someone pasted is how a
    connection ends up pointing somewhere they did not intend.
    """
    if not isinstance(value, str):
        raise ExtensionError(errors.INVALID_CONFIGURATION, _DOMAIN_HELP)
    text = value.strip()
    if not text or len(text) > MAX_SHOP_DOMAIN_LENGTH:
        raise ExtensionError(errors.INVALID_CONFIGURATION, _DOMAIN_HELP)
    if any(character.isspace() for character in text):
        raise ExtensionError(
            errors.INVALID_CONFIGURATION, "The store address must not contain spaces"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise ExtensionError(
            errors.INVALID_CONFIGURATION,
            "The store address contains characters that are not part of a domain name",
        )
    if "//" in text or ":" in text:
        raise ExtensionError(
            errors.INVALID_CONFIGURATION,
            "Remove the https:// prefix and any port from the store address",
        )
    if "@" in text:
        raise ExtensionError(
            errors.INVALID_CONFIGURATION, "Remove the username and password from the store address"
        )
    if "/" in text:
        raise ExtensionError(errors.INVALID_CONFIGURATION, "Remove the path from the store address")
    if "?" in text or "#" in text:
        raise ExtensionError(
            errors.INVALID_CONFIGURATION, "Remove everything after ? or # from the store address"
        )
    if "*" in text:
        raise ExtensionError(
            errors.INVALID_CONFIGURATION, "A wildcard domain does not identify one store"
        )
    lowered = text.lower()
    name = lowered[: -len(SHOP_DOMAIN_SUFFIX)] if lowered.endswith(SHOP_DOMAIN_SUFFIX) else lowered
    if "." in name:
        raise ExtensionError(
            errors.INVALID_CONFIGURATION,
            "This extension connects to a store's own myshopify.com domain, not a custom storefront domain",
        )
    if not name or len(name) > MAX_SHOP_NAME_LENGTH or _SHOP_NAME_RE.fullmatch(name) is None:
        raise ExtensionError(errors.INVALID_CONFIGURATION, _DOMAIN_HELP)
    return f"{name}{SHOP_DOMAIN_SUFFIX}"


def assert_shop_domain_allowed(shop_domain: str) -> str:
    """Refuse a store address the default Flow Steward host policy blocks."""
    try:
        return assert_safe_remote_http_url(f"https://{shop_domain}", purpose="Shopify store domain")
    except (PinnedPeerError, ValueError) as exc:
        raise ExtensionError(
            errors.BLOCKED_ADDRESS, "The store address is not reachable under the host policy"
        ) from exc


def _access_token(value: Any) -> str:
    """The hydrated access token, or a refusal that names no value.

    An absent token means the authorization is gone rather than malformed, so it
    asks for reconnection instead of reporting a broken connection.
    """
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        raise ExtensionError(
            errors.REAUTHORIZATION_REQUIRED, "Reconnect this Shopify store to continue"
        )
    if (
        len(text) < MIN_TOKEN_LENGTH
        or len(text) > MAX_TOKEN_LENGTH
        or _TOKEN_RE.fullmatch(text) is None
    ):
        # Deliberately says nothing about the value itself.
        raise ExtensionError(errors.INVALID_CONNECTION, "The Shopify access token is not usable")
    return text


def _verified_shop_domain(config: Mapping[str, Any]) -> str:
    """The store Shopify confirmed when the connection was authorized.

    Read from the OAuth subject the platform wrote after verifying the callback
    signature, and re-checked here against the same canonical form the
    authorization used. A connection whose subject is missing was never completed.
    """
    oauth = config.get("oauth")
    oauth = oauth if isinstance(oauth, Mapping) else {}
    subject = oauth.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        raise ExtensionError(
            errors.REAUTHORIZATION_REQUIRED, "Reconnect this Shopify store to continue"
        )
    return normalize_shop_domain(subject)


def connection_from_payload(payload: Mapping[str, Any], *, connection_ref: str) -> Connection:
    """Validate the selected project connection before any outbound request.

    Connection material is read only from ``action.target.connection``. The
    operation's ``connection_ref`` must name that same connection, so a workflow
    cannot ask for one connection's data while the host hydrates another.
    """
    action = payload.get("action")
    target = action.get("target") if isinstance(action, Mapping) else None
    connection = target.get("connection") if isinstance(target, Mapping) else None
    if not isinstance(connection, Mapping):
        raise ExtensionError(errors.INVALID_CONNECTION, "The selected connection is unavailable")
    connection_id = str(connection.get("connection_id") or "")
    if connection_id != connection_ref:
        raise ExtensionError(
            errors.INVALID_CONNECTION, "The selected connection does not match connection_ref"
        )
    connection_type = str(
        connection.get("connection_type_id") or connection.get("connection_type") or ""
    )
    if connection_type and connection_type != CONNECTION_TYPE_ID:
        raise ExtensionError(errors.INVALID_CONNECTION, "The selected connection is not supported")

    config = connection.get("config")
    config = config if isinstance(config, Mapping) else {}
    secrets = connection.get("secrets")
    secrets = secrets if isinstance(secrets, Mapping) else {}
    if set(config) - CONFIG_FIELDS or set(secrets) - SECRET_FIELDS:
        raise ExtensionError(errors.INVALID_CONNECTION, "The connection carries unsupported fields")

    return Connection(
        connection_id=connection_id,
        shop_domain=_verified_shop_domain(config),
        _access_token=_access_token(secrets.get("access_token")),
    )


__all__ = [
    "CONFIG_FIELDS",
    "CONNECTION_TYPE_ID",
    "REQUIRED_CONFIG_FIELDS",
    "REQUIRED_SECRET_FIELDS",
    "SECRET_FIELDS",
    "SHOP_DOMAIN_SUFFIX",
    "Connection",
    "assert_shop_domain_allowed",
    "connection_from_payload",
    "normalize_shop_domain",
]
