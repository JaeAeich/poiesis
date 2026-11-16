"""Tests for the optional userinfo lookup and the claim lookup.

Tokens are minted and validated for real; the issuer (discovery, JWKS,
userinfo) is a fake on a fake network (see `conftest.py`).
"""

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from conftest import ISSUER, Issuer, Network

from poiesis.api import auth
from poiesis.api.auth import OIDCValidator, Principal, get_principal
from poiesis.api.exceptions import UnauthorizedError
from poiesis.api.settings import AuthSettings


def validator(*, userinfo: bool = True) -> OIDCValidator:
    """Bootstrap a validator against the fake issuer."""
    settings = AuthSettings(userinfo_enabled=userinfo)
    oidc = OIDCValidator(settings)
    asyncio.run(oidc.bootstrap())
    return oidc


def principal(oidc: OIDCValidator, token: str) -> Principal:
    """Run the `get_principal` dependency for a request with `token`."""
    request: Any = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(oidc=oidc)),
        headers={"authorization": f"Bearer {token}"},
    )
    return asyncio.run(get_principal(request))


def test_off_by_default(issuer: Issuer, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the setting, userinfo is never fetched and stays empty."""
    monkeypatch.delenv("POIESIS_AUTH_OIDC_USERINFO_ENABLED", raising=False)
    oidc = OIDCValidator(AuthSettings())
    asyncio.run(oidc.bootstrap())
    result = principal(oidc, issuer.token())
    assert result.userinfo == {}
    assert issuer.userinfo_calls == 0


def test_setting_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`POIESIS_AUTH_OIDC_USERINFO_ENABLED=true` turns it on."""
    monkeypatch.setenv("POIESIS_AUTH_OIDC_USERINFO_ENABLED", "true")
    assert AuthSettings().userinfo_enabled


def test_claims_kept_apart(issuer: Issuer) -> None:
    """Userinfo claims sit next to the token claims, not merged into them."""
    issuer.userinfo = {"groups": ["g"]}
    result = principal(validator(), issuer.token(scope="openid"))
    assert result.userinfo == {"sub": "alice", "groups": ["g"]}
    assert "groups" not in result.claims
    assert result.claims["scope"] == "openid"


def test_one_lookup_per_token(issuer: Issuer) -> None:
    """Case 21: two requests with one token cause one userinfo call."""
    oidc = validator()
    token = issuer.token()
    principal(oidc, token)
    principal(oidc, token)
    assert issuer.userinfo_calls == 1
    principal(oidc, issuer.token(jti="other"))
    assert issuer.userinfo_calls == 2  # noqa: PLR2004


def test_request_carries_token(issuer: Issuer, network: Network) -> None:
    """The token goes to the discovered endpoint, asking for JSON."""
    token = issuer.token()
    principal(validator(), token)
    request = network.requests[-1]
    assert str(request.url) == f"{ISSUER}/userinfo"
    assert request.headers["authorization"] == f"Bearer {token}"
    assert request.headers["accept"] == "application/json"


def test_cache_expires(issuer: Issuer, monkeypatch: pytest.MonkeyPatch) -> None:
    """Entries live until the token expires, at most five minutes."""
    oidc = validator()
    now = auth.time.time()
    short, long = issuer.token(exp=int(now) + 60), issuer.token(exp=int(now) + 3600)
    principal(oidc, short)
    principal(oidc, long)
    monkeypatch.setattr(auth.time, "time", lambda: now + 120)
    asyncio.run(oidc.userinfo(short, issuer.tokens[short]))
    asyncio.run(oidc.userinfo(long, issuer.tokens[long]))
    assert issuer.userinfo_calls == 3  # noqa: PLR2004 (short refetched)
    monkeypatch.setattr(auth.time, "time", lambda: now + 400)
    asyncio.run(oidc.userinfo(long, issuer.tokens[long]))
    assert issuer.userinfo_calls == 4  # noqa: PLR2004 (five minutes passed)


def test_cache_is_bounded(issuer: Issuer, monkeypatch: pytest.MonkeyPatch) -> None:
    """The least recently used entry goes when the cache is full."""
    monkeypatch.setattr(auth, "_USERINFO_CACHE_SIZE", 2)
    oidc = validator()
    first, second, third = (issuer.token(jti=str(i)) for i in range(3))
    for token in (first, second, first, third):
        principal(oidc, token)
    assert issuer.userinfo_calls == 3  # noqa: PLR2004
    principal(oidc, first)
    assert issuer.userinfo_calls == 3  # noqa: PLR2004 (first was used recently)
    principal(oidc, second)
    assert issuer.userinfo_calls == 4  # noqa: PLR2004 (second was evicted)


def respond(*args: Any, **kwargs: Any) -> Any:
    """Return a userinfo handler answering with `httpx.Response(...)`."""
    return lambda _: httpx.Response(*args, **kwargs)


def fail(_: httpx.Request) -> httpx.Response:
    """Fail like an unreachable endpoint."""
    raise httpx.ConnectTimeout("timed out")


@pytest.mark.parametrize(
    "handler",
    [
        respond(200, json={"sub": "mallory"}),
        respond(200, json={"name": "no sub"}),
        fail,
        respond(500, json={"sub": "alice"}),
        respond(401),
        respond(200, content=b"e.y.J", headers={"content-type": "application/jwt"}),
        respond(200, content=b"{", headers={"content-type": "application/json"}),
        respond(200, json=["alice"]),
    ],
    ids=[
        "other-sub",
        "no-sub",
        "unreachable",
        "server-error",
        "token-refused",
        "signed-jwt",
        "not-json",
        "not-an-object",
    ],
)
def test_failures_are_401(issuer: Issuer, handler: Any) -> None:
    """Case 20: a different `sub`, any error or non-JSON answer is a 401."""
    issuer.userinfo_handler = handler
    oidc = validator()
    token = issuer.token()
    with pytest.raises(UnauthorizedError):
        principal(oidc, token)
    issuer.userinfo_handler = None
    assert principal(oidc, token).userinfo == {"sub": "alice"}  # failure not cached


@pytest.mark.parametrize(
    "endpoint",
    [None, 42, "/userinfo", "ftp://issuer.example.org/u", "http://idp/u"],
    ids=["missing", "not-a-string", "relative", "ftp", "http"],
)
def test_bootstrap_needs_usable_endpoint(
    issuer: Issuer, network: Network, endpoint: Any
) -> None:
    """Startup fails without an absolute https endpoint (for an https issuer)."""
    doc = {"issuer": ISSUER, "jwks_uri": f"{ISSUER}/jwks"}
    if endpoint is not None:
        doc["userinfo_endpoint"] = endpoint
    network.hosts["issuer.example.org"] = lambda request: (
        httpx.Response(200, json=doc)
        if request.url.path.endswith("openid-configuration")
        else issuer(request)
    )
    with pytest.raises(RuntimeError, match="userinfo_endpoint"):
        validator()


class TestClaimLookup:
    """`Principal.claim`: exact name, then dotted path; token, then userinfo."""

    def test_token_wins(self) -> None:
        """Case 6b: a claim in both sources resolves to the token's value."""
        both = Principal(id="a", claims={"g": "token"}, userinfo={"g": "info"})
        assert both.claim("g") == "token"

    def test_userinfo_fills_in(self) -> None:
        """Case 6b: a claim only in userinfo resolves to the userinfo value."""
        assert Principal(id="a", userinfo={"g": "info"}).claim("g") == "info"

    def test_exact_name_before_path(self) -> None:
        """An exact name anywhere wins over a dotted path in the token."""
        p = Principal(
            id="a",
            claims={"https://e": {"org/g": "path"}},
            userinfo={"https://e.org/g": "exact"},
        )
        assert p.claim("https://e.org/g") == "exact"

    def test_dotted_path(self) -> None:
        """Case 5c: dotted paths walk objects, token before userinfo."""
        p = Principal(id="a", claims={"ctx": {}}, userinfo={"ctx": {"groups": ["x"]}})
        assert p.claim("ctx.groups") == ["x"]

    @pytest.mark.parametrize("claims", [{}, {"g": None}, {"ctx": "flat"}])
    def test_missing(self, claims: dict[str, Any]) -> None:
        """Absent, null and unwalkable claims resolve to `None`."""
        assert Principal(id="a", claims=claims).claim("ctx.g") is None
        assert Principal(id="a", claims=claims).claim("g") is None

    def test_principal_claim_exact_name(self, issuer: Issuer) -> None:
        """`principal_claim` also prefers an exact (URI) name."""
        oidc = OIDCValidator(AuthSettings(principal_claim="https://e.org/id"))
        asyncio.run(oidc.bootstrap())
        token = issuer.token(**{"https://e.org/id": "owner-1"})
        assert principal(oidc, token).id == "owner-1"
