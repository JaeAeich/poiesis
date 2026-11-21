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

from poiesis.api.exceptions import MissingCredentialError, UnauthorizedError

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Owner stamped on every task when ``auth.enabled`` is false. It has no
#: ``|``, so it can never equal a real ``namespace|subject`` owner.
ANONYMOUS_OWNER = "__anonymous__"


@dataclass(slots=True, frozen=True)
class Actor:
    """Who acts on the subject's behalf: an RFC 8693 ``act`` claim.

    ``listed`` says the actor is in its token issuer's ``actors``, which
    the built-in policy accepts without a decision service.
    """

    issuer: str
    subject: str
    listed: bool = False


@dataclass(slots=True, frozen=True)
class Principal:
    """The authenticated subject of a request.

    ``subject`` is the value of the issuer's ``principalClaim`` (default
    ``sub``) and ``owner`` (``namespace|subject``) the id stamped on the
    tasks it creates; ``namespace`` is the issuer's, which defaults to
    the issuer itself. ``via`` names the authenticator,
    ``credential_id`` the credential (a token's ``jti``, an API key's
    id) for audit, ``scopes`` what it grants, and ``actor`` the party
    acting for the subject (delegation). ``claims`` carries the
    validated token payload, ``userinfo`` the issuer's userinfo answer
    when that lookup is on (empty otherwise), kept apart from the claims.
    """

    issuer: str
    subject: str
    via: str  # "oidc", "apikey" or "anonymous"
    # Prefix of the owner id; empty means the issuer (set below).
    namespace: str = ""
    credential_id: str | None = None
    # When the credential was issued (seconds since the epoch): an API
    # key's minting time, which is also when its claims were snapshot.
    credential_issued_at: float | None = None
    actor: Actor | None = None
    scopes: frozenset[str] = frozenset()
    claims: dict[str, Any] = field(default_factory=dict)
    userinfo: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Default the namespace to the issuer."""
        if not self.namespace:
            # Frozen: assign through object, as dataclasses do themselves.
            object.__setattr__(self, "namespace", self.issuer)

    @property
    def owner(self) -> str:
        """The opaque owner id: ``namespace|subject``, or the anonymous one."""
        if self.via == "anonymous":
            return ANONYMOUS_OWNER
        return f"{self.namespace}|{self.subject}"

    @property
    def client(self) -> Any:
        """The OAuth client of the (minting) token: ``azp``, else ``client_id``."""
        return client_of(self.claims)

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


#: Longest owner id taken as an argument (the owner of key management
#: calls); real ones are an issuer URL or namespace and a subject.
MAX_OWNER_LENGTH = 1024


def is_owner_id(value: str) -> bool:
    """Whether ``value`` looks like an owner id: ``namespace|subject``.

    Both parts non-empty; the namespace has no ``|``, the subject may.
    """
    namespace, bar, subject = value.partition("|")
    return bool(namespace and bar and subject) and len(value) <= MAX_OWNER_LENGTH


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


def client_of(claims: dict[str, Any]) -> Any:
    """Return a token's OAuth client: ``azp``, else ``client_id``, or ``None``.

    ``azp`` is OIDC's (Keycloak, most IdPs), ``client_id`` RFC 9068's.
    The value is unchecked: callers compare it with configured ids.
    """
    return claims.get("azp") or claims.get("client_id")


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
    raise MissingCredentialError("missing bearer token")
