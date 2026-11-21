"""Authentication: the per-request principal and the authenticator chain.

Poiesis is a resource server: it does not run a login flow. Each request
is offered to an ordered chain of :class:`Authenticator` objects (built
at startup, kept in ``app.state.authenticators``); the first that
recognises the credential returns the :class:`Principal`, which route
handlers get from the :func:`get_principal` FastAPI dependency.

Identity only ever comes from a credential an authenticator verifies
itself (a signed JWT, see `poiesis.api.jwt_auth`, or a Poiesis API key,
see `poiesis.api.apikey_auth`), never from a plain header such as
``X-User`` or ``X-Forwarded-User``.

Note: this module does NOT use ``from __future__ import annotations``.
FastAPI introspects the signature of :func:`get_principal` at runtime
to wire dependency injection, so ``Request`` must be a live import,
not a string forward reference. Same constraint as `poiesis.api.deps`.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import Request

from poiesis.api.exceptions import UnauthorizedError

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Owner stamped on every task when ``auth.enabled`` is false. It has no
#: ``|``, so it can never equal a real ``issuer|subject`` owner.
ANONYMOUS_OWNER = "__anonymous__"


@dataclass(slots=True, frozen=True)
class Actor:
    """Who acts on the subject's behalf: an RFC 8693 ``act`` claim."""

    issuer: str
    subject: str


@dataclass(slots=True, frozen=True)
class Principal:
    """The authenticated subject of a request.

    ``subject`` is the value of the issuer's ``principalClaim`` (default
    ``sub``) and ``owner`` (``issuer|subject``) the id stamped on the
    tasks it creates. ``via`` names the authenticator, ``credential_id``
    the credential (a token's ``jti``, an API key's id) for audit,
    ``scopes`` what it grants, and ``actor`` the
    party acting for the subject (delegation). ``claims`` carries the
    validated token payload, ``userinfo`` the issuer's userinfo answer
    when that lookup is on (empty otherwise), kept apart from the claims.
    """

    issuer: str
    subject: str
    via: str  # "oidc", "apikey" or "anonymous"
    credential_id: str | None = None
    actor: Actor | None = None
    scopes: frozenset[str] = frozenset()
    claims: dict[str, Any] = field(default_factory=dict)
    userinfo: dict[str, Any] = field(default_factory=dict)

    @property
    def owner(self) -> str:
        """The opaque owner id: ``issuer|subject``, or the anonymous one."""
        if self.via == "anonymous":
            return ANONYMOUS_OWNER
        return f"{self.issuer}|{self.subject}"

    def claim(self, name: str) -> Any:
        """Return the caller's value of claim ``name``, or ``None``.

        The exact top-level name comes before a dotted path (so
        URI-named claims such as ``https://example.org/groups`` work),
        and at each step the access token comes before userinfo.
        """
        for source in (self.claims, self.userinfo):
            if source.get(name) is not None:
                return source[name]
        for source in (self.claims, self.userinfo):
            value = walk_claim_path(source, name)
            if value is not None:
                return value
        return None


#: Served to every request when auth is disabled.
ANONYMOUS = Principal(issuer="", subject=ANONYMOUS_OWNER, via="anonymous")


class Authenticator(Protocol):
    """One way to authenticate a request, a link in the chain.

    :meth:`authenticate` returns ``None`` for a credential that isn't
    this authenticator's (the next one is tried) and raises
    :class:`UnauthorizedError` for one that is but doesn't verify (or
    another API error, e.g. ``503`` while its issuer is unreachable).
    """

    name: str

    async def start(self) -> None:
        """Prepare for requests; called once from the FastAPI ``lifespan``."""
        ...

    async def aclose(self) -> None:
        """Release resources; called at shutdown."""
        ...

    async def authenticate(self, request: Request) -> Principal | None:
        """Return the request's principal, or ``None`` if not this kind."""
        ...


def walk_claim_path(claims: dict[str, Any], path: str) -> Any:
    """Resolve a dotted ``path`` like ``ctx.group_id`` against ``claims``.

    Returns ``None`` if any intermediate segment is missing or not a
    dict. The top-level case ``path='sub'`` is preserved for the common
    default with no dotted lookup overhead.
    """
    if "." not in path:
        return claims.get(path)
    current: Any = claims
    for segment in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


async def get_principal(request: Request) -> Principal:
    """FastAPI dependency: run the authenticator chain for the request.

    ``app.state.authenticators`` is ``None`` when auth is disabled: every
    request is then served as the anonymous principal, so downstream
    code paths stay uniform. Otherwise the first authenticator that
    recognises the credential wins; if none does, ``401``.
    """
    authenticators: Sequence[Authenticator] | None = request.app.state.authenticators
    if authenticators is None:
        return ANONYMOUS
    for authenticator in authenticators:
        principal = await authenticator.authenticate(request)
        if principal is not None:
            return principal
    if request.headers.get("authorization"):
        raise UnauthorizedError("invalid token")
    raise UnauthorizedError("missing bearer token")
