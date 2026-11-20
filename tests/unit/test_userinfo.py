"""Tests for the optional userinfo lookup and the claim lookup.

Tokens are minted and validated for real; the issuer (discovery, JWKS,
userinfo) is a fake on a fake network (see `fake_issuer.py`).
"""

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fake_issuer import AUDIENCE, ISSUER, Issuer, Network, set_issuers
from pydantic import ValidationError

from poiesis.api import jwt_auth
from poiesis.api.auth import Principal, get_principal
from poiesis.api.exceptions import ServiceUnavailableError, UnauthorizedError
from poiesis.api.jwt_auth import IssuerValidator, JWTAuthenticator
from poiesis.api.settings import AuthSettings, IssuerSettings


def started(oidc: JWTAuthenticator) -> JWTAuthenticator:
    """Start `oidc` (bootstrap its issuers) and return it."""
    asyncio.run(oidc.start())
    return oidc


def validator(**settings: Any) -> JWTAuthenticator:
    """Start an authenticator for the fake issuer, userinfo on by default."""
    entry = {"issuer": ISSUER, "audience": AUDIENCE, "userinfo": {"enabled": True}}
    return started(JWTAuthenticator([IssuerSettings.model_validate(entry | settings)]))


def from_env() -> JWTAuthenticator:
    """Start an authenticator for the issuers configured in the environment."""
    return started(JWTAuthenticator(AuthSettings().issuers))


def principal(oidc: JWTAuthenticator, token: str) -> Principal:
    """Run the `get_principal` dependency for a request with `token`."""
    request: Any = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(authenticators=[oidc])),
        headers={"authorization": f"Bearer {token}"},
    )
    return asyncio.run(get_principal(request))


def userinfo(oidc: JWTAuthenticator, issuer: Issuer, token: str) -> dict[str, Any]:
    """Call the fake issuer's validator's userinfo lookup directly."""
    lookup = oidc.issuers[ISSUER].userinfo(token, issuer.tokens[token])
    return asyncio.run(lookup)


def fetches(issuer: Issuer, oidc: JWTAuthenticator, token: str) -> int:
    """Return how many userinfo calls a request with `token` caused."""
    before = issuer.userinfo_calls
    principal(oidc, token)
    return issuer.userinfo_calls - before


def test_off_by_default(issuer: Issuer, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the setting, userinfo is never fetched and stays empty."""
    oidc = from_env()
    assert principal(oidc, issuer.token()).userinfo == {}
    assert issuer.userinfo_calls == 0


def test_setting_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`"userinfo": {"enabled": true}` in an issuer's entry turns it on."""
    entry = {"issuer": ISSUER, "audience": AUDIENCE, "userinfo": {"enabled": True}}
    set_issuers(monkeypatch, entry)
    assert AuthSettings().issuers[0].userinfo.enabled


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
    now = jwt_auth.time.time()
    token = issuer.token(exp=int(now) + 60)
    principal(oidc, token)
    monkeypatch.setattr(jwt_auth.time, "time", lambda: now + 120)
    before = issuer.userinfo_calls
    userinfo(oidc, issuer, token)
    assert issuer.userinfo_calls == before + 1


def test_cache_ends_after_five_minutes(
    issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An entry of a long-lived token ends after five minutes."""
    oidc = validator()
    now = jwt_auth.time.time()
    token = issuer.token(exp=int(now) + 3600)
    principal(oidc, token)
    monkeypatch.setattr(jwt_auth.time, "time", lambda: now + 290)
    before = issuer.userinfo_calls
    userinfo(oidc, issuer, token)
    assert issuer.userinfo_calls == before
    monkeypatch.setattr(jwt_auth.time, "time", lambda: now + 310)
    userinfo(oidc, issuer, token)
    assert issuer.userinfo_calls == before + 1


def test_cache_is_bounded(issuer: Issuer, monkeypatch: pytest.MonkeyPatch) -> None:
    """The least recently used entry goes when the cache is full."""
    monkeypatch.setattr(jwt_auth, "_USERINFO_CACHE_SIZE", 2)
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
        respond(401),
        respond(302, headers={"location": "https://elsewhere.example.org/"}),
        respond(200, content=b"e.y.J", headers={"content-type": "application/jwt"}),
        respond(200, content=b"{", headers={"content-type": "application/json"}),
        respond(200, json=["alice"]),
    ],
    ids=[
        "other-sub",
        "no-sub",
        "token-refused",
        "redirect",
        "signed-jwt",
        "not-json",
        "not-an-object",
    ],
)
def test_failures_are_401(issuer: Issuer, handler: Any) -> None:
    """A different `sub`, a refused token or a non-JSON answer is a 401."""
    issuer.userinfo_handler = handler
    oidc = validator()
    token = issuer.token()
    with pytest.raises(UnauthorizedError):
        principal(oidc, token)
    issuer.userinfo_handler = None
    assert principal(oidc, token).userinfo == {"sub": "alice"}  # failure not cached


@pytest.mark.parametrize(
    "handler",
    [fail, respond(500, json={"sub": "alice"}), respond(503)],
    ids=["unreachable", "server-error", "unavailable"],
)
def test_outages_are_503(issuer: Issuer, handler: Any) -> None:
    """An unreachable or failing endpoint is a 503, not a bad token."""
    issuer.userinfo_handler = handler
    oidc = validator()
    token = issuer.token()
    with pytest.raises(ServiceUnavailableError) as error:
        principal(oidc, token)
    assert error.value.retry_after_seconds == jwt_auth._ISSUER_RETRY_AFTER
    issuer.userinfo_handler = None
    assert principal(oidc, token).userinfo == {"sub": "alice"}  # failure not cached


def test_missing_owner_claim_skips_userinfo(
    issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A token without the owner claim is refused before userinfo sees it."""
    oidc = validator(principalClaim="ctx.group_id")
    before = issuer.userinfo_calls
    with pytest.raises(UnauthorizedError, match="claim"):
        principal(oidc, issuer.token())
    assert issuer.userinfo_calls == before


def test_one_client_per_validator(
    issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovery, JWKS and userinfo share one HTTP client until closed."""
    made: list[httpx.AsyncClient] = []
    factory = httpx.AsyncClient

    def counting(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        made.append(factory(*args, **kwargs))
        return made[-1]

    monkeypatch.setattr(httpx, "AsyncClient", counting)
    oidc = validator()
    principal(oidc, issuer.token())
    principal(oidc, issuer.token(jti="second"))
    assert len(made) == 1
    asyncio.run(oidc.aclose())
    assert made[0].is_closed


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
    with pytest.raises(jwt_auth.IssuerConfigError, match="userinfo_endpoint"):
        validator()


# -- OIDC timeout ------------------------------------------------------------


def timeouts(network: Network) -> list[dict[str, float]]:
    """Return the httpx timeouts (per phase) of all recorded requests."""
    return [request.extensions["timeout"] for request in network.requests]


def entry(**settings: Any) -> dict[str, Any]:
    """Return an issuer entry for the fake issuer, plus `settings`."""
    return {"issuer": ISSUER, "audience": AUDIENCE} | settings


@pytest.mark.parametrize(("value", "expected"), [(None, 10.0), (2.5, 2.5), (30, 30.0)])
def test_timeout_setting(
    monkeypatch: pytest.MonkeyPatch, value: float | None, expected: float
) -> None:
    """An issuer's `timeout` is in seconds; unset is 10."""
    set_issuers(monkeypatch, entry() if value is None else entry(timeout=value))
    assert AuthSettings().issuers[0].timeout == expected


@pytest.mark.parametrize("value", [0, -1, "soon", math.nan, math.inf])
def test_timeout_setting_invalid(monkeypatch: pytest.MonkeyPatch, value: Any) -> None:
    """A timeout that isn't a positive number of seconds refuses to start."""
    set_issuers(monkeypatch, entry(timeout=value))
    with pytest.raises(ValueError, match=r"(?s)POIESIS_AUTH_ISSUERS\[0\].*timeout"):
        AuthSettings()


@pytest.mark.parametrize("value", [0, -1, math.nan, math.inf])
def test_timeout_argument_invalid(value: float) -> None:
    """The same holds when the settings are built in code."""
    with pytest.raises(ValidationError, match="timeout"):
        IssuerSettings(issuer=ISSUER, audience=AUDIENCE, timeout=value)


@pytest.mark.parametrize("seconds", [None, 2.5])
def test_timeout_bounds_every_call(
    issuer: Issuer,
    network: Network,
    monkeypatch: pytest.MonkeyPatch,
    seconds: float | None,
) -> None:
    """Discovery, JWKS and userinfo all use the one timeout (default 10 s)."""
    principal(
        validator(**({} if seconds is None else {"timeout": seconds})), issuer.token()
    )
    paths = {request.url.path for request in network.requests}
    assert paths == {"/.well-known/openid-configuration", "/jwks", "/userinfo"}
    phases = dict.fromkeys(("connect", "read", "write", "pool"), seconds or 10.0)
    assert timeouts(network) == [phases] * 3


def slow(delay: float) -> Any:
    """Return a userinfo handler that answers after `delay` seconds.

    The fake network doesn't wait; it fails like a timed-out request
    whenever the client's read timeout is shorter than `delay`. This
    checks the mapping of a timeout to 503; `test_trickle_*` check
    that the timeout bounds the whole call.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.extensions["timeout"]["read"] < delay:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json={"sub": "alice"})

    return handler


def test_slow_userinfo_is_503(issuer: Issuer, monkeypatch: pytest.MonkeyPatch) -> None:
    """Userinfo slower than the timeout is a 503; a longer timeout lets it in."""
    issuer.userinfo_handler = slow(5)
    with pytest.raises(ServiceUnavailableError):
        principal(validator(timeout=1), issuer.token())
    assert principal(validator(), issuer.token()).userinfo == {"sub": "alice"}


TRICKLE_BODY = b'{"sub": "alice", "padding": "................"}'
TRICKLE_GAP = 0.05  # seconds between bytes: each wait is far below the timeout
TRICKLE_TIMEOUT = 0.5  # the whole answer takes about 2.3 s


async def trickle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Answer any request with JSON, one byte at a time."""
    await reader.readuntil(b"\r\n\r\n")
    writer.write(
        b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n"
        b"content-length: %d\r\n\r\n" % len(TRICKLE_BODY)
    )
    try:
        for byte in TRICKLE_BODY:
            writer.write(bytes([byte]))
            await writer.drain()
            await asyncio.sleep(TRICKLE_GAP)
    except ConnectionError:  # the client gave up
        pass
    writer.close()


async def against_trickle(call: Callable[[str], Awaitable[Any]]) -> float:
    """Run `call` with the URL of a local trickling server; return seconds."""
    server = await asyncio.start_server(trickle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    start = time.monotonic()
    try:
        await call(f"http://127.0.0.1:{port}")
    finally:
        elapsed = time.monotonic() - start
        server.close()
    return elapsed


def test_trickle_userinfo_is_503() -> None:
    """The timeout bounds the whole userinfo call, not each read."""

    async def call(url: str) -> None:
        with pytest.raises(ServiceUnavailableError) as error:
            await IssuerValidator._fetch_userinfo(
                f"{url}/userinfo", "token", TRICKLE_TIMEOUT
            )
        assert isinstance(error.value.__cause__, TimeoutError)

    assert asyncio.run(against_trickle(call)) < 2 * TRICKLE_TIMEOUT


def test_trickle_discovery_is_an_outage() -> None:
    """A slow issuer at startup counts as down within the timeout."""

    async def call(url: str) -> None:
        settings = IssuerSettings(issuer=url, audience="a", timeout=TRICKLE_TIMEOUT)
        validator = IssuerValidator(settings)
        try:
            await validator.start()
            assert not validator.ready
        finally:
            await validator.aclose()

    assert asyncio.run(against_trickle(call)) < 2 * TRICKLE_TIMEOUT


def oidc_principal(**fields: Any) -> Principal:
    """Return a principal of the fake issuer for `a`, plus `fields`."""
    return Principal(issuer=ISSUER, subject="a", via="oidc", **fields)


class TestClaimLookup:
    """`Principal.claim`: exact name, then dotted path; token, then userinfo."""

    def test_token_wins(self) -> None:
        """A claim in both sources resolves to the token's value."""
        both = oidc_principal(claims={"g": "token"}, userinfo={"g": "info"})
        assert both.claim("g") == "token"

    def test_userinfo_fills_in(self) -> None:
        """A claim only in userinfo resolves to the userinfo value."""
        assert oidc_principal(userinfo={"g": "info"}).claim("g") == "info"

    def test_exact_name_before_path(self) -> None:
        """An exact (URI) name anywhere wins over a dotted path in the token."""
        p = oidc_principal(
            claims={"https://e": {"org/g": "path"}},
            userinfo={"https://e.org/g": "exact"},
        )
        assert p.claim("https://e.org/g") == "exact"

    def test_dotted_path(self) -> None:
        """Dotted paths walk objects, token before userinfo."""
        p = oidc_principal(claims={"ctx": {}}, userinfo={"ctx": {"groups": ["x"]}})
        assert p.claim("ctx.groups") == ["x"]

    def test_null_exact_name_falls_back_to_path(self) -> None:
        """A null exact-name claim counts as missing."""
        p = oidc_principal(claims={"a.b": None, "a": {"b": "x"}})
        assert p.claim("a.b") == "x"

    @pytest.mark.parametrize("claims", [{}, {"g": None}, {"ctx": "flat"}])
    def test_missing(self, claims: dict[str, Any]) -> None:
        """Absent, null and unwalkable claims resolve to `None`."""
        assert oidc_principal(claims=claims).claim("ctx.g") is None
        assert oidc_principal(claims=claims).claim("g") is None

    def test_principal_claim_unchanged(self, issuer: Issuer) -> None:
        """`principal_claim` still walks a dotted path, as before."""
        oidc = validator(principalClaim="ctx.id", userinfo={"enabled": False})
        token = issuer.token(**{"ctx.id": "top", "ctx": {"id": "nested"}})
        assert principal(oidc, token).subject == "nested"
