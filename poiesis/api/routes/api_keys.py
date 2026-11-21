"""API key routes: mint, list and revoke the caller's own keys.

Mounted at ``/poiesis/v1`` only when auth and API keys are enabled (see
`poiesis.api.app`). Managing keys needs an interactive OIDC login: an
API key can't mint, list or revoke keys (so a leaked key can't extend
itself), nor can a delegated token. Keys are bound to the caller's owner
id; see `poiesis.api.apikey_auth` for how they authenticate.

Note: no ``from __future__ import annotations``; FastAPI introspects the
handlers and models below at runtime (see `poiesis.api.auth`).
"""

import logging
import time
import uuid
from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from poiesis.api.apikey_auth import DB_ERRORS, SCOPES, hash_key, new_key
from poiesis.api.auth import Principal, get_principal
from poiesis.api.authz import Authz, get_authz
from poiesis.api.deps import get_db_pool
from poiesis.api.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from poiesis.api.settings import (
    TTL_PATTERN,
    ApiKeySettings,
    IssuerSettings,
    format_ttl,
    parse_ttl,
)
from poiesis.db import api_keys as api_keys_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ApiKeys"])

#: Token claims left out of a key's snapshot: they describe the minting
#: token's own lifetime and identity, not the owner, and would make the
#: snapshot look like a token that expired long ago.
_TOKEN_ONLY_CLAIMS = frozenset({"exp", "iat", "nbf", "jti", "auth_time"})

Scope = Literal["tasks:read", "tasks:write"]
#: ``Retry-After`` seconds while the database can't be reached.
_DB_RETRY_AFTER = 5


def _store_unavailable(exc: BaseException) -> ServiceUnavailableError:
    """The retryable ``503`` for a database error while managing keys."""
    logger.warning("API key store unavailable: %s", type(exc).__name__)
    return ServiceUnavailableError(
        "credential store unavailable", retry_after_seconds=_DB_RETRY_AFTER
    )


class _Camel(BaseModel):
    """camelCase on the wire, as in the rest of Poiesis's own API."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CreateApiKeyRequest(_Camel):
    """What to mint: a label, and optionally a lifetime and scopes."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100, examples=["nextflow-run-42"])
    ttl: str | None = Field(
        default=None,
        pattern=TTL_PATTERN,
        description="Lifetime, `<n>d` or `<n>h`; default and maximum are "
        "configured by the operator (30d and 90d unless changed).",
        examples=["30d"],
    )
    scopes: list[Scope] | None = Field(
        default=None,
        min_length=1,
        description="Default: both. `tasks:write` implies `tasks:read`.",
    )


class ApiKeyInfo(_Camel):
    """A key as listed: everything but the secret."""

    id: uuid.UUID
    name: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None = Field(
        default=None,
        description="Recorded in batches, so up to about a minute behind.",
    )
    revoked_at: datetime | None = None


class CreatedApiKey(_Camel):
    """A freshly minted key; ``key`` is shown this once and never again."""

    id: uuid.UUID
    name: str
    key: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime


def get_api_key_settings(request: Request) -> ApiKeySettings:
    """FastAPI dependency: the configured key limits."""
    return request.app.state.settings.auth.api_keys


async def key_manager(
    principal: Annotated[Principal, Depends(get_principal)],
    authz: Annotated[Authz, Depends(get_authz)],
) -> Principal:
    """FastAPI dependency: a principal allowed to manage its keys.

    It must come from an OIDC token, not be delegated, and pass the
    claim rule; anyone else gets ``403``.
    """
    if principal.via == "apikey":
        raise ForbiddenError("a key can't mint or manage keys; use an OIDC token")
    if principal.via != "oidc":
        raise ForbiddenError("managing API keys needs an OIDC token")
    if principal.actor is not None:
        raise ForbiddenError("delegated tokens can't manage keys")
    authz.gate(principal)
    return principal


def mint_refusal(
    principal: Principal, issuer: IssuerSettings | None, now: float
) -> str | None:
    """Why ``principal`` may not mint a key (the ``403`` message), or ``None``.

    Its issuer must have ``keyMinting``, the token must come from one of
    the listed clients, and, with ``maxAuthAge``, the user must have
    logged in recently (``auth_time``).
    """
    if issuer is None or issuer.key_minting is None:
        return "tokens of this issuer can't mint API keys"
    minting = issuer.key_minting
    client = principal.claims.get("azp") or principal.claims.get("client_id")
    if client not in minting.clients:
        return f"tokens of client {str(client)[:100]!r} can't mint API keys"
    if minting.max_auth_age is not None:
        auth_time = principal.claims.get("auth_time")
        if not isinstance(auth_time, int | float) or isinstance(auth_time, bool):
            return "the token has no auth_time; log in again to mint a key"
        if auth_time > now + issuer.clock_skew:
            return "the token's auth_time is in the future"
        if now - auth_time > minting.max_auth_age:
            return "the last login is too old to mint a key; log in again"
    return None


async def key_minter(
    request: Request,
    principal: Annotated[Principal, Depends(key_manager)],
) -> Principal:
    """FastAPI dependency: a key manager whose token may also mint keys."""
    issuers = request.app.state.settings.auth.issuers
    issuer = next((i for i in issuers if i.issuer == principal.issuer), None)
    refusal = mint_refusal(principal, issuer, time.time())
    if refusal is not None:
        logger.warning("API key minting refused for %s: %s", principal.owner, refusal)
        raise ForbiddenError(refusal)
    return principal


@router.post(
    "/api-keys",
    status_code=HTTPStatus.CREATED,
    operation_id="CreateApiKey",
    response_model_by_alias=True,
)
async def create_api_key(
    body: CreateApiKeyRequest,
    principal: Annotated[Principal, Depends(key_minter)],
    settings: Annotated[ApiKeySettings, Depends(get_api_key_settings)],
    pool: Annotated[Any, Depends(get_db_pool)],
) -> CreatedApiKey:
    """Mint an API key for the caller; the response is the only copy of it."""
    ttl = settings.default_ttl if body.ttl is None else parse_ttl(body.ttl)
    if ttl > settings.max_ttl:
        raise BadRequestError(
            f"ttl {body.ttl} exceeds the maximum of {format_ttl(settings.max_ttl)}"
        )
    scopes = sorted(set(body.scopes or SCOPES))
    key = new_key()
    snapshot = {
        "claims": {
            name: value
            for name, value in principal.claims.items()
            if name not in _TOKEN_ONLY_CLAIMS
        },
        "userinfo": principal.userinfo,
    }
    try:
        async with pool.acquire() as conn:
            record = await api_keys_db.create_api_key(
                conn,
                key_id=uuid.uuid4(),
                name=body.name,
                key_hash=hash_key(key),
                owner=principal.owner,
                scopes=scopes,
                claims_snapshot=snapshot,
                ttl=ttl,
                max_active=settings.max_per_owner,
            )
    except DB_ERRORS as exc:
        raise _store_unavailable(exc) from exc
    if record is None:
        raise ConflictError(
            f"at most {settings.max_per_owner} active API keys per owner; "
            "revoke one first"
        )
    logger.info(
        "API key %s minted for %s by client %s: scopes %s, expires %s",
        record.id,
        principal.owner,
        principal.claims.get("azp") or principal.claims.get("client_id"),
        ",".join(record.scopes),
        record.expires_at.isoformat(),
    )
    return CreatedApiKey(
        id=record.id,
        name=record.name,
        key=key,
        scopes=list(record.scopes),
        created_at=record.created_at,
        expires_at=record.expires_at,
    )


@router.get(
    "/api-keys",
    status_code=HTTPStatus.OK,
    operation_id="ListApiKeys",
    response_model_by_alias=True,
)
async def list_api_keys(
    principal: Annotated[Principal, Depends(key_manager)],
    pool: Annotated[Any, Depends(get_db_pool)],
) -> list[ApiKeyInfo]:
    """List the caller's keys, revoked and expired ones included, newest first."""
    try:
        async with pool.acquire() as conn:
            records = await api_keys_db.list_api_keys(conn, principal.owner)
    except DB_ERRORS as exc:
        raise _store_unavailable(exc) from exc
    return [
        ApiKeyInfo(
            id=record.id,
            name=record.name,
            scopes=list(record.scopes),
            created_at=record.created_at,
            expires_at=record.expires_at,
            last_used_at=record.last_used_at,
            revoked_at=record.revoked_at,
        )
        for record in records
    ]


@router.delete(
    "/api-keys/{id}",
    status_code=HTTPStatus.NO_CONTENT,
    operation_id="RevokeApiKey",
    response_class=Response,
)
async def revoke_api_key(
    id: str,
    principal: Annotated[Principal, Depends(key_manager)],
    pool: Annotated[Any, Depends(get_db_pool)],
) -> None:
    """Revoke one of the caller's keys; it stops working immediately."""
    try:
        key_id = uuid.UUID(id)
    except ValueError as exc:
        raise BadRequestError(f"invalid key id: {id}") from exc
    try:
        async with pool.acquire() as conn:
            revoked = await api_keys_db.revoke_api_key(conn, key_id, principal.owner)
    except DB_ERRORS as exc:
        raise _store_unavailable(exc) from exc
    if not revoked:
        raise NotFoundError(f"API key {id} not found")
    logger.info("API key %s revoked by %s", key_id, principal.owner)
