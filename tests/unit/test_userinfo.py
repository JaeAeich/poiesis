"""Tests for the optional userinfo lookup and the claim lookup.

Tokens are minted and validated for real; the issuer (discovery, JWKS,
userinfo) is a fake on a fake network (see `fake_issuer.py`).
"""

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fake_issuer import ISSUER, Issuer, Network

from poiesis.api import auth
from poiesis.api.auth import OIDCValidator, Principal, get_principal
from poiesis.api.exceptions import UnauthorizedError
from poiesis.api.settings import AuthSettings


def validator(*, userinfo: bool = True) -> OIDCValidator:
    """Bootstrap a validator against the fake issuer."""
    oidc = OIDCValidator(AuthSettings(userinfo_enabled=userinfo))
    asyncio.run(oidc.bootstrap())
    return oidc


def principal(oidc: OIDCValidator, token: str) -> Principal:
    """Run the `get_principal` dependency for a request with `token`."""
    request: Any = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(oidc=oidc)),
        headers={"authorization": f"Bearer {token}"},
    )
    return asyncio.run(get_principal(request))


def fetches(issuer: Issuer, oidc: OIDCValidator, token: str) -> int:
    """Return how many userinfo calls a request with `token` caused."""
    before = issuer.userinfo_calls
    principal(oidc, token)
    return issuer.userinfo_calls - before


def test_off_by_default(issuer: Issuer, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the setting, userinfo is never fetched and stays empty."""
    monkeypatch.delenv("POIESIS_AUTH_OIDC_USERINFO_ENABLED", raising=False)
    oidc = OIDCValidator(AuthSettings())
    asyncio.run(oidc.bootstrap())
    assert principal(oidc, issuer.token()).userinfo == {}
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
    """Two requests with one token cause one userinfo call."""
    oidc = validator()
    token = issuer.token()
    assert fetches(issuer, oidc, token) == 1
    assert fetches(issuer, oidc, token) == 0
    assert fetches(issuer, oidc, issuer.token(jti="other")) == 1


def test_cached_answer_is_a_copy(issuer: Issuer) -> None:
    """Changing a principal's userinfo doesn't change the cached answer."""
    oidc = validator()
    token = issuer.token()
    issuer.userinfo = {"groups": ["g"]}
    first = principal(oidc, token).userinfo
    first["sub"] = "mallory"
    first["groups"].append("h")
    assert principal(oidc, token).userinfo == {"sub": "alice", "groups": ["g"]}


def test_request_carries_token(issuer: Issuer, network: Network) -> None:
    """The token goes to the discovered endpoint, asking for JSON."""
    token = issuer.token()
    principal(validator(), token)
    request = network.requests[-1]
    assert str(request.url) == f"{ISSUER}/userinfo"
    assert request.headers["authorization"] == f"Bearer {token}"
    assert request.headers["accept"] == "application/json"


def test_cache_ends_with_token(issuer: Issuer, monkeypatch: pytest.MonkeyPatch) -> None:
    """An entry ends when its token expires."""
    oidc = validator()
    now = auth.time.time()
    token = issuer.token(exp=int(now) + 60)
    principal(oidc, token)
    monkeypatch.setattr(auth.time, "time", lambda: now + 120)
    before = issuer.userinfo_calls
    asyncio.run(oidc.userinfo(token, issuer.tokens[token]))
    assert issuer.userinfo_calls == before + 1


def test_cache_ends_after_five_minutes(
    issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An entry of a long-lived token ends after five minutes."""
    oidc = validator()
    now = auth.time.time()
    token = issuer.token(exp=int(now) + 3600)
    principal(oidc, token)
    monkeypatch.setattr(auth.time, "time", lambda: now + 290)
    before = issuer.userinfo_calls
    asyncio.run(oidc.userinfo(token, issuer.tokens[token]))
    assert issuer.userinfo_calls == before
    monkeypatch.setattr(auth.time, "time", lambda: now + 310)
    asyncio.run(oidc.userinfo(token, issuer.tokens[token]))
    assert issuer.userinfo_calls == before + 1


def test_cache_is_bounded(issuer: Issuer, monkeypatch: pytest.MonkeyPatch) -> None:
    """The least recently used entry goes when the cache is full."""
    monkeypatch.setattr(auth, "_USERINFO_CACHE_SIZE", 2)
    oidc = validator()
    first, second, third = (issuer.token(jti=str(i)) for i in range(3))
    for token in (first, second, first, third):
        principal(oidc, token)
    assert fetches(issuer, oidc, first) == 0  # used recently, kept
    assert fetches(issuer, oidc, second) == 1  # least recently used, evicted


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
        respond(302, headers={"location": "https://elsewhere.example.org/"}),
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
        "redirect",
        "signed-jwt",
        "not-json",
        "not-an-object",
    ],
)
def test_failures_are_401(issuer: Issuer, handler: Any) -> None:
    """A different `sub`, any error or a non-JSON answer is a 401."""
    issuer.userinfo_handler = handler
    oidc = validator()
    token = issuer.token()
    with pytest.raises(UnauthorizedError):
        principal(oidc, token)
    issuer.userinfo_handler = None
    assert principal(oidc, token).userinfo == {"sub": "alice"}  # failure not cached


def test_media_type_case_insensitive(issuer: Issuer) -> None:
    """`Application/JSON; charset=utf-8` is JSON too."""
    issuer.userinfo_handler = respond(
        200,
        content=b'{"sub": "alice"}',
        headers={"content-type": "Application/JSON; charset=utf-8"},
    )
    assert principal(validator(), issuer.token()).userinfo == {"sub": "alice"}


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


# -- OIDC timeout ------------------------------------------------------------


def timeouts(network: Network) -> set[float]:
    """Return the read timeouts of all recorded requests."""
    return {request.extensions["timeout"]["read"] for request in network.requests}


@pytest.mark.parametrize(
    ("value", "expected"), [(None, 10.0), ("", 10.0), ("2.5", 2.5), ("30", 30.0)]
)
def test_timeout_setting(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: float
) -> None:
    """`POIESIS_AUTH_OIDC_TIMEOUT` is in seconds; unset or empty is 10."""
    if value is None:
        monkeypatch.delenv("POIESIS_AUTH_OIDC_TIMEOUT", raising=False)
    else:
        monkeypatch.setenv("POIESIS_AUTH_OIDC_TIMEOUT", value)
    assert AuthSettings().timeout == expected


@pytest.mark.parametrize("value", ["0", "-1", "soon", "nan", "inf"])
def test_timeout_setting_invalid(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """A timeout that isn't a positive number of seconds refuses to start."""
    monkeypatch.setenv("POIESIS_AUTH_OIDC_TIMEOUT", value)
    with pytest.raises(ValueError, match="POIESIS_AUTH_OIDC_TIMEOUT"):
        AuthSettings()


@pytest.mark.parametrize("seconds", [None, 2.5])
def test_timeout_bounds_every_call(
    issuer: Issuer,
    network: Network,
    monkeypatch: pytest.MonkeyPatch,
    seconds: float | None,
) -> None:
    """Discovery, JWKS and userinfo all use the one timeout (default 10 s)."""
    if seconds is not None:
        monkeypatch.setenv("POIESIS_AUTH_OIDC_TIMEOUT", str(seconds))
    principal(validator(), issuer.token())
    paths = {request.url.path for request in network.requests}
    assert paths == {"/.well-known/openid-configuration", "/jwks", "/userinfo"}
    assert timeouts(network) == {seconds or 10.0}


def slow(delay: float) -> Any:
    """Return a userinfo handler that answers after `delay` seconds.

    The fake network doesn't wait; it fails like a timed-out request
    whenever the client's read timeout is shorter than `delay`.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.extensions["timeout"]["read"] < delay:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json={"sub": "alice"})

    return handler


def test_slow_userinfo_is_401(issuer: Issuer, monkeypatch: pytest.MonkeyPatch) -> None:
    """Userinfo slower than the timeout is a 401; a longer timeout lets it in."""
    issuer.userinfo_handler = slow(5)
    monkeypatch.setenv("POIESIS_AUTH_OIDC_TIMEOUT", "1")
    with pytest.raises(UnauthorizedError):
        principal(validator(), issuer.token())
    monkeypatch.delenv("POIESIS_AUTH_OIDC_TIMEOUT")
    assert principal(validator(), issuer.token()).userinfo == {"sub": "alice"}


class TestClaimLookup:
    """`Principal.claim`: exact name, then dotted path; token, then userinfo."""

    def test_token_wins(self) -> None:
        """A claim in both sources resolves to the token's value."""
        both = Principal(id="a", claims={"g": "token"}, userinfo={"g": "info"})
        assert both.claim("g") == "token"

    def test_userinfo_fills_in(self) -> None:
        """A claim only in userinfo resolves to the userinfo value."""
        assert Principal(id="a", userinfo={"g": "info"}).claim("g") == "info"

    def test_exact_name_before_path(self) -> None:
        """An exact (URI) name anywhere wins over a dotted path in the token."""
        p = Principal(
            id="a",
            claims={"https://e": {"org/g": "path"}},
            userinfo={"https://e.org/g": "exact"},
        )
        assert p.claim("https://e.org/g") == "exact"

    def test_dotted_path(self) -> None:
        """Dotted paths walk objects, token before userinfo."""
        p = Principal(id="a", claims={"ctx": {}}, userinfo={"ctx": {"groups": ["x"]}})
        assert p.claim("ctx.groups") == ["x"]

    def test_null_exact_name_falls_back_to_path(self) -> None:
        """A null exact-name claim counts as missing."""
        p = Principal(id="a", claims={"a.b": None, "a": {"b": "x"}})
        assert p.claim("a.b") == "x"

    @pytest.mark.parametrize("claims", [{}, {"g": None}, {"ctx": "flat"}])
    def test_missing(self, claims: dict[str, Any]) -> None:
        """Absent, null and unwalkable claims resolve to `None`."""
        assert Principal(id="a", claims=claims).claim("ctx.g") is None
        assert Principal(id="a", claims=claims).claim("g") is None

    def test_principal_claim_unchanged(self, issuer: Issuer) -> None:
        """`principal_claim` still walks a dotted path, as before."""
        oidc = OIDCValidator(AuthSettings(principal_claim="ctx.id"))
        asyncio.run(oidc.bootstrap())
        token = issuer.token(**{"ctx.id": "top", "ctx": {"id": "nested"}})
        assert principal(oidc, token).id == "nested"
