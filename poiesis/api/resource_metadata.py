"""OAuth 2.0 Protected Resource Metadata (RFC 9728) and ``401`` challenges.

Clients that know only the URL of a Poiesis can find out how to
authenticate to it: from the metadata document, or from the
``WWW-Authenticate`` header of any ``401`` (and of a ``403`` for a
missing scope), which points to it (RFC 9728 §5.1). The document lists
the configured issuers that clients can get tokens from
(``authorization_servers``) and is served when auth is on and
``auth.resource`` (the public URL) is set. Without it, a
``401`` still carries the plain RFC 6750 ``Bearer`` challenge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.exceptions import (
    InsufficientScopeError,
    UnauthorizedError,
    handle_api_exception,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi import Request

    from poiesis.api.settings import AuthSettings, ServiceInfoSettings

WELL_KNOWN = "/.well-known/oauth-protected-resource"


def metadata_path(resource: str) -> str:
    """Return the metadata path for ``resource``: the suffix after its path.

    RFC 9728 §3.1 inserts the well-known suffix between the host and the
    path, so ``https://h/tes`` has its metadata at
    ``https://h/.well-known/oauth-protected-resource/tes``.
    """
    return WELL_KNOWN + urlsplit(resource).path.rstrip("/")


def metadata_url(resource: str) -> str:
    """Return the absolute URL of ``resource``'s metadata document."""
    parts = urlsplit(resource)
    return urlunsplit((parts.scheme, parts.netloc, metadata_path(resource), "", ""))


def metadata(auth: AuthSettings, info: ServiceInfoSettings) -> dict[str, Any]:
    """Return the metadata document for ``auth`` (``auth.resource`` set).

    ``resource_name`` and ``resource_documentation`` are the service-info
    ``name`` and ``documentationUrl``, with the same defaults.

    Issuers with a static ``jwksUri`` aren't listed: they publish only
    keys (e.g. a gateway signing its own JWTs), and clients can't get a
    token from them. ``scopes_supported`` are the issuers'
    ``requiredScopes``, the scopes a client must ask for.
    """
    servers = [i for i in auth.issuers if i.jwks_uri is None]
    document: dict[str, Any] = {"resource": auth.resource}
    if servers:
        document["authorization_servers"] = [i.issuer for i in servers]
    scopes = sorted({scope for i in servers for scope in i.required_scopes})
    if scopes:
        document["scopes_supported"] = scopes
    document["bearer_methods_supported"] = ["header"]
    constants = get_poiesis_api_constants()
    document["resource_name"] = info.name or constants.SERVICE_NAME
    document["resource_documentation"] = (
        info.documentation_url or constants.DOCUMENTATION_URL
    )
    return document


def router(auth: AuthSettings, info: ServiceInfoSettings) -> APIRouter:
    """Return a router serving the metadata of ``auth`` (``auth.resource`` set)."""
    if auth.resource is None:
        raise ValueError("resource metadata needs auth.resource")
    document = metadata(auth, info)
    api = APIRouter(tags=["auth"])

    @api.get(metadata_path(auth.resource), include_in_schema=False)
    async def protected_resource_metadata() -> JSONResponse:
        """Serve the RFC 9728 metadata; public, like the issuers' own."""
        return JSONResponse(document, headers={"Cache-Control": "max-age=3600"})

    return api


def challenge(auth: AuthSettings, error: str | None, scopes: Sequence[str] = ()) -> str:
    """Return the ``WWW-Authenticate`` value of a ``401`` or ``403``.

    ``error`` is the RFC 6750 error code (``invalid_token``,
    ``insufficient_scope``), or none when the request had no credential
    (RFC 6750 §3.1). ``scopes`` are those the token needs; settings
    refuse scopes that can't be quoted (RFC 6749 §3.3).
    """
    params = []
    if error:
        params.append(f'error="{error}"')
    if scopes:
        params.append(f'scope="{" ".join(scopes)}"')
    if auth.resource:
        # Settings refuse quotes and backslashes in the URL.
        params.append(f'resource_metadata="{metadata_url(auth.resource)}"')
    return f"Bearer {', '.join(params)}" if params else "Bearer"


async def handle_challenge(request: Request, exc: Exception) -> JSONResponse:
    """Answer a ``401`` or a missing scope as usual, plus the challenge.

    Other ``403``s (claim rule, policy) get none: a new token with more
    scopes wouldn't change their answer.
    """
    response = await handle_api_exception(request, exc)
    error, scopes = None, ()
    if isinstance(exc, UnauthorizedError):
        error = exc.bearer_error
    elif isinstance(exc, InsufficientScopeError):
        error, scopes = exc.bearer_error, exc.scopes
    response.headers["WWW-Authenticate"] = challenge(
        request.app.state.settings.auth, error, scopes
    )
    return response
