"""Tests for authentication: the chain, issuers, keys and the principal.

Tokens are minted and validated for real; the issuers (discovery, JWKS,
userinfo) are fakes on a fake network (see `fake_issuer.py`).
"""

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fake_issuer import (
    AUDIENCE,
    GATEWAY,
    GATEWAY_JWKS,
    ISSUER,
    OTHER_ISSUER,
    Issuer,
    Network,
    set_issuers,
)
from fastapi.testclient import TestClient
from joserfc.jwk import ECKey

from poiesis.api import app as app_module
from poiesis.api import jwt_auth
from poiesis.api.auth import ANONYMOUS_OWNER, Actor, Principal, get_principal
from poiesis.api.exceptions import (
    ForbiddenError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from poiesis.api.jwt_auth import IssuerConfigError, JWTAuthenticator
from poiesis.api.routes import tasks as tasks_routes
from poiesis.api.settings import AuthSettings, IssuerSettings

TASKS = "/ga4gh/tes/v1/tasks"


def entry(issuer: str = ISSUER, **settings: Any) -> dict[str, Any]:
    """Return an issuer entry (camelCase keys, as in Helm) plus `settings`."""
    return {"issuer": issuer, "audience": AUDIENCE} | settings


def authenticator(*entries: dict[str, Any]) -> JWTAuthenticator:
    """Return an (unstarted) authenticator for `entries`, default the issuer."""
    entries = entries or (entry(),)
    return JWTAuthenticator([IssuerSettings.model_validate(e) for e in entries])


def run(
    oidc: JWTAuthenticator, scenario: Callable[[JWTAuthenticator], Awaitable[Any]]
) -> Any:
    """Start `oidc`, run `scenario` with it and close it, in one event loop."""

    async def main() -> Any:
        await oidc.start()
        try:
            return await scenario(oidc)
        finally:
            await oidc.aclose()

    return asyncio.run(main())


async def principal_of(
    authenticators: list[JWTAuthenticator] | None,
    token: str | None = None,
    **headers: str,
) -> Principal:
    """Run the `get_principal` dependency for a request."""
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    request: Any = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(authenticators=authenticators)),
        headers={name.lower(): value for name, value in headers.items()},
    )
    return await get_principal(request)


def authenticate(oidc: JWTAuthenticator, *tokens: str) -> list[Any]:
    """Start `oidc` and authenticate each token; return principals or errors."""

    async def scenario(oidc: JWTAuthenticator) -> list[Any]:
        results: list[Any] = []
        for token in tokens:
            try:
                results.append(await principal_of([oidc], token))
            except (UnauthorizedError, ForbiddenError, ServiceUnavailableError) as exc:
                results.append(exc)
        return results

    return run(oidc, scenario)


class Clock:
    """A settable stand-in for the validator's monotonic clock."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Start at a fixed time and install."""
        self.now = 1000.0
        monkeypatch.setattr(jwt_auth, "_monotonic", lambda: self.now)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """Control the time the validators see."""
    return Clock(monkeypatch)


@pytest.fixture
def fast_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry a failed bootstrap after milliseconds instead of seconds."""
    monkeypatch.setattr(jwt_auth, "_RETRY_INITIAL", 0.01)
    monkeypatch.setattr(jwt_auth, "_RETRY_MAX", 0.02)


# -- settings ---------------------------------------------------------------------


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`POIESIS_AUTH_ISSUERS` is a JSON array of camelCase objects."""
    set_issuers(
        monkeypatch,
        entry(principalClaim="ctx.id", requiredScopes=["tes"], jwksCacheTtl=60),
        entry(GATEWAY, jwksUri=GATEWAY_JWKS, clockSkew=0, timeout=2.5),
    )
    first, second = AuthSettings().issuers
    assert (first.principal_claim, first.required_scopes) == ("ctx.id", ("tes",))
    assert (first.jwks_cache_ttl, first.jwks_uri, first.timeout) == (60, None, 10)
    assert not first.userinfo.enabled
    assert (second.jwks_uri, second.clock_skew, second.timeout) == (
        GATEWAY_JWKS,
        0,
        2.5,
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("", "lists no issuer"),
        ("[]", "lists no issuer"),
        ("{", "not valid JSON"),
        ('{"issuer": "https://a"}', "JSON array"),
        ('["https://a"]', r"\[0\] is invalid"),
        (json.dumps([{"issuer": ISSUER}]), "audience"),
        (json.dumps([{"audience": AUDIENCE}]), "issuer"),
        (json.dumps([entry(audience="")]), "audience"),
        (json.dumps([entry(clientSecret="x")]), "clientSecret"),
        (json.dumps([entry(principal_claim="sub")]), "principal_claim"),
        (json.dumps([entry(), entry(OTHER_ISSUER, jwksCacheTtl=0)]), r"\[1\]"),
        (json.dumps([entry(), entry()]), "twice"),
        (json.dumps([entry("issuer.example.org")]), "http"),
        (json.dumps([entry(jwksUri="file:///keys")]), "jwksUri"),
        (
            json.dumps([entry(jwksUri=GATEWAY_JWKS, userinfo={"enabled": True})]),
            "jwksUri",
        ),
        (json.dumps([entry("https://a|b")]), r"\|"),
        (json.dumps([entry(requiredScopes=[""])]), "requiredScopes"),
    ],
    ids=[
        "unset",
        "empty",
        "not-json",
        "not-array",
        "not-object",
        "no-audience",
        "no-issuer",
        "empty-audience",
        "unknown-key",
        "snake-case-key",
        "bad-ttl",
        "duplicate",
        "not-a-url",
        "bad-jwks-uri",
        "userinfo-and-jwks-uri",
        "pipe",
        "empty-scope",
    ],
)
def test_invalid_issuers_refused(
    monkeypatch: pytest.MonkeyPatch, value: str, message: str
) -> None:
    """Invalid or missing `POIESIS_AUTH_ISSUERS` refuses to start."""
    monkeypatch.setenv("POIESIS_AUTH_ISSUERS", value)
    with pytest.raises(ValueError, match=f"(?s){message}"):
        AuthSettings()


@pytest.mark.parametrize("name", ["POIESIS_AUTH_OIDC_ISSUER", "POIESIS_AUTH_OIDC_X"])
@pytest.mark.parametrize("enabled", ["true", "false"])
def test_old_settings_refused(
    monkeypatch: pytest.MonkeyPatch, name: str, enabled: str
) -> None:
    """Any leftover `POIESIS_AUTH_OIDC_*` refuses to start, auth on or off."""
    set_issuers(monkeypatch, entry())
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", enabled)
    monkeypatch.setenv(name, "https://issuer.example.org")
    with pytest.raises(ValueError, match=f"{name}.*replaced by POIESIS_AUTH_ISSUERS"):
        AuthSettings()


def test_disabled_needs_no_issuer() -> None:
    """With auth off, no issuer is needed."""
    assert AuthSettings(enabled=False).issuers == ()


# -- the chain -----------------------------------------------------------------------


def test_anonymous_when_disabled() -> None:
    """With auth off every request is the anonymous owner, token or not."""
    for token in (None, "e.y.J"):
        principal = asyncio.run(principal_of(None, token))
        assert principal.owner == ANONYMOUS_OWNER == "__anonymous__"
        assert principal.via == "anonymous"


def test_owner_is_issuer_and_subject(issuer: Issuer) -> None:
    """The owner is `issuer|sub`; via, jti and scopes come from the token."""
    token = issuer.token(jti="t-1", scope="openid tes")
    (principal,) = authenticate(authenticator(), token)
    assert principal.owner == f"{ISSUER}|alice"
    assert (principal.issuer, principal.subject) == (ISSUER, "alice")
    assert principal.via == "oidc"
    assert principal.credential_id == "t-1"
    assert principal.scopes == {"openid", "tes"}
    assert principal.actor is None
    assert principal.claims == issuer.tokens[token]


def test_scp_list(issuer: Issuer) -> None:
    """Scopes may also come as an `scp` list."""
    (principal,) = authenticate(authenticator(), issuer.token(scp=["a", "b"]))
    assert principal.scopes == {"a", "b"}


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        ({}, "missing bearer token"),
        ({"authorization": "Basic YWxpY2U6YWxpY2U="}, "invalid token"),
        ({"authorization": "Bearer poi_abc"}, "invalid token"),
        ({"authorization": "Bearer a.b.c.d.e"}, "invalid token"),
        ({"authorization": "Bearer !!.!!.!!"}, "invalid token"),
        ({"authorization": "Bearer W10.W10.x"}, "invalid token"),
    ],
    ids=["none", "basic", "not-a-jwt", "jwe", "not-base64", "not-objects"],
)
def test_no_credential(issuer: Issuer, headers: dict[str, str], message: str) -> None:
    """Without a JWT that verifies, 401."""

    async def scenario(oidc: JWTAuthenticator) -> None:
        with pytest.raises(UnauthorizedError, match=message):
            await principal_of([oidc], **headers)

    run(authenticator(), scenario)


def test_identity_headers_ignored(issuer: Issuer) -> None:
    """Identity never comes from a plain header, alone or next to a token."""
    identity = {
        "X-User": "bob",
        "X-Forwarded-User": "bob",
        "X-Remote-User": "bob",
        "X-Auth-Request-User": "bob",
        "Remote-User": "bob",
        "X-Forwarded-Email": "bob@example.org",
    }

    async def scenario(oidc: JWTAuthenticator) -> None:
        with pytest.raises(UnauthorizedError, match="missing bearer token"):
            await principal_of([oidc], **identity)
        principal = await principal_of([oidc], issuer.token(), **identity)
        assert principal.owner == f"{ISSUER}|alice"

    run(authenticator(), scenario)


def test_identity_headers_ignored_by_app(
    issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real app answers 401 to identity headers without a token."""
    with started_app(monkeypatch) as client:
        response = client.get(TASKS, headers={"X-User": "alice"})
        assert response.status_code == 401  # noqa: PLR2004
        response = client.get(TASKS, headers={"X-Forwarded-User": "alice"})
        assert response.status_code == 401  # noqa: PLR2004


# -- several issuers ----------------------------------------------------------------


def test_two_issuers(network: Network) -> None:
    """Tokens of two issuers both authenticate; equal `sub`s don't collide."""
    first, second = network.add(Issuer()), network.add(Issuer(OTHER_ISSUER))
    one, two = authenticate(
        authenticator(entry(), entry(OTHER_ISSUER)), first.token(), second.token()
    )
    assert one.subject == two.subject == "alice"
    assert one.owner == f"{ISSUER}|alice"
    assert two.owner == f"{OTHER_ISSUER}|alice"


def test_token_of_one_issuer_signed_by_another(network: Network) -> None:
    """The `iss` picks the keys: a token claiming another issuer fails."""
    network.add(Issuer())
    second = network.add(Issuer(OTHER_ISSUER))
    forged = second.token(iss=ISSUER)
    (result,) = authenticate(authenticator(entry(), entry(OTHER_ISSUER)), forged)
    assert isinstance(result, UnauthorizedError)


@pytest.mark.parametrize(
    "iss", ["https://evil.example.org", f"{ISSUER}/", None, 42], ids=str
)
def test_unknown_issuer(issuer: Issuer, network: Network, iss: Any) -> None:
    """A token of an unconfigured issuer is a 401; nothing is fetched for it."""
    evil = network.add(Issuer("https://evil.example.org"))
    (result,) = authenticate(authenticator(), evil.token(iss=iss))
    assert isinstance(result, UnauthorizedError)
    assert network.paths("evil.example.org") == []


def test_static_jwks_issuer(network: Network) -> None:
    """With `jwksUri`, keys come from there and discovery is never asked."""
    gateway = network.add(Issuer(GATEWAY, static=True))
    (principal,) = authenticate(
        authenticator(entry(GATEWAY, jwksUri=GATEWAY_JWKS)),
        gateway.token(sub="repo:org/x"),
    )
    assert principal.owner == f"{GATEWAY}|repo:org/x"
    assert network.paths("gateway.example.org") == ["/keys.json"]


@pytest.mark.parametrize(
    "named", ["https://elsewhere.example.org", f"{ISSUER}/", None], ids=str
)
def test_discovery_issuer_mismatch(issuer: Issuer, named: str | None) -> None:
    """A discovery document naming another issuer fails the start."""
    issuer.discovery["issuer"] = named
    with pytest.raises(IssuerConfigError, match="match exactly"):
        run(authenticator(), lambda _: asyncio.sleep(0))


@pytest.mark.parametrize(
    "jwks_uri", ["http://issuer.example.org/jwks", "/jwks", None], ids=str
)
def test_discovery_needs_safe_jwks_uri(issuer: Issuer, jwks_uri: str | None) -> None:
    """The discovered JWKS URL must be absolute and as secure as the issuer."""
    issuer.discovery["jwks_uri"] = jwks_uri
    with pytest.raises(IssuerConfigError, match="jwks_uri"):
        run(authenticator(), lambda _: asyncio.sleep(0))


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(404), httpx.Response(200, content=b"<html>")],
    ids=["404", "not-json"],
)
def test_misconfigured_issuer_fails_start(
    issuer: Issuer, network: Network, answer: httpx.Response
) -> None:
    """A 4xx or non-JSON discovery answer is misconfiguration, not an outage."""
    network.hosts["issuer.example.org"] = lambda _: answer
    with pytest.raises(IssuerConfigError):
        run(authenticator(), lambda _: asyncio.sleep(0))


def test_required_scopes_per_issuer(network: Network) -> None:
    """Each issuer's required scopes apply to its tokens only."""
    first, second = network.add(Issuer()), network.add(Issuer(OTHER_ISSUER))
    oidc = authenticator(entry(requiredScopes=["tes"]), entry(OTHER_ISSUER))
    missing, ok, other = authenticate(
        oidc, first.token(scope="openid"), first.token(scope="tes"), second.token()
    )
    assert isinstance(missing, ForbiddenError)
    assert isinstance(ok, Principal)
    assert isinstance(other, Principal)


# -- soft start ---------------------------------------------------------------------


def test_down_at_start_then_back(issuer: Issuer, fast_retry: None) -> None:
    """Issuer down at start: 503 with Retry-After, then tokens work."""
    issuer.down = True

    async def scenario(oidc: JWTAuthenticator) -> None:
        with pytest.raises(ServiceUnavailableError) as error:
            await principal_of([oidc], issuer.token())
        assert error.value.retry_after_seconds == jwt_auth._ISSUER_RETRY_AFTER
        issuer.down = False
        for _ in range(200):
            if oidc.issuers[ISSUER].ready:
                break
            await asyncio.sleep(0.01)
        principal = await principal_of([oidc], issuer.token())
        assert principal.owner == f"{ISSUER}|alice"

    run(authenticator(), scenario)


def test_one_issuer_down_others_serve(network: Network, fast_retry: None) -> None:
    """One issuer being down doesn't affect the others."""
    first, second = network.add(Issuer()), network.add(Issuer(OTHER_ISSUER))
    second.down = True
    one, two = authenticate(
        authenticator(entry(), entry(OTHER_ISSUER)), first.token(), second.token()
    )
    assert isinstance(one, Principal)
    assert isinstance(two, ServiceUnavailableError)


def test_misconfiguration_after_outage_keeps_issuer_unready(
    issuer: Issuer, fast_retry: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Misconfiguration found by the retry is logged; tokens keep getting 503."""
    issuer.down = True

    async def scenario(oidc: JWTAuthenticator) -> None:
        issuer.discovery["issuer"] = "https://elsewhere.example.org"
        issuer.down = False
        for _ in range(100):
            if "misconfigured" in caplog.text:
                break
            await asyncio.sleep(0.01)
        assert "misconfigured" in caplog.text
        with pytest.raises(ServiceUnavailableError):
            await principal_of([oidc], issuer.token())

    run(authenticator(), scenario)


@contextlib.contextmanager
def started_app(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Run the real app (lifespan included) with fake database and cluster."""

    class Pool:
        @contextlib.asynccontextmanager
        async def acquire(self) -> AsyncIterator[None]:
            yield None

        async def close(self) -> None:
            pass

    async def create_pool(_: str) -> Pool:
        return Pool()

    async def list_tasks(*_: Any, **__: Any) -> tuple[list[Any], None]:
        return [], None

    monkeypatch.setattr(app_module, "create_pool", create_pool)
    monkeypatch.setattr(app_module, "load_config", lambda: None)
    monkeypatch.setattr(app_module, "K8sClient", lambda: None)
    monkeypatch.setattr(tasks_routes.tasks_db, "list_tasks", list_tasks)
    with TestClient(app_module.create_app()) as client:
        yield client


def test_app_starts_with_issuer_down(
    issuer: Issuer, monkeypatch: pytest.MonkeyPatch, fast_retry: None
) -> None:
    """The real app starts with its issuer down and serves once it is back."""
    issuer.down = True
    with started_app(monkeypatch) as client:
        headers = {"Authorization": f"Bearer {issuer.token()}"}
        response = client.get(TASKS, headers=headers)
        assert response.status_code == 503  # noqa: PLR2004
        assert response.headers["retry-after"] == str(jwt_auth._ISSUER_RETRY_AFTER)
        issuer.down = False
        deadline = time.monotonic() + 5
        while client.get(TASKS, headers=headers).status_code != 200:  # noqa: PLR2004
            assert time.monotonic() < deadline
            time.sleep(0.01)


def test_app_refuses_misconfigured_issuer(
    issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A misconfigured issuer fails the real app's start."""
    issuer.discovery["issuer"] = "https://elsewhere.example.org"
    with pytest.raises(IssuerConfigError), started_app(monkeypatch):
        pass


# -- key refresh ---------------------------------------------------------------------


def stale_scenario(
    issuer: Issuer, clock: Clock, failure: Callable[[], None]
) -> Callable[[JWTAuthenticator], Awaitable[None]]:
    """Expire the keys, break the JWKS with `failure`, then authenticate."""

    async def scenario(oidc: JWTAuthenticator) -> None:
        before = issuer.jwks_calls
        clock.now += 61
        failure()
        # Refresh fails: the cached keys still validate.
        assert (await principal_of([oidc], issuer.token())).subject == "alice"
        assert issuer.jwks_calls == before + 1
        # No refresh storm: the next requests within the back-off don't fetch.
        for _ in range(3):
            await principal_of([oidc], issuer.token())
        assert issuer.jwks_calls == before + 1
        # After the back-off, the refresh is tried again.
        clock.now += jwt_auth._RETRY_INITIAL + 0.1
        await principal_of([oidc], issuer.token())
        assert issuer.jwks_calls == before + 2

    return scenario


def fail(issuer: Issuer, answer: Any) -> Callable[[], None]:
    """Return a function making the issuer's JWKS answer `answer` (or raise)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(answer, Exception):
            raise answer
        return answer

    def apply() -> None:
        issuer.jwks_handler = handler

    return apply


@pytest.mark.parametrize(
    "answer",
    [
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
        httpx.Response(503),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"keys": []}),
        httpx.Response(404),
    ],
    ids=["down", "timeout", "503", "not-json", "no-keys", "404"],
)
def test_refresh_failure_keeps_cached_keys(
    issuer: Issuer, clock: Clock, answer: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """A failed refresh keeps the stale keys, warns and backs off; never 500."""
    run(
        authenticator(entry(jwksCacheTtl=60)),
        stale_scenario(issuer, clock, fail(issuer, answer)),
    )
    assert "keeping the cached keys" in caplog.text


def test_refresh_success(issuer: Issuer, clock: Clock) -> None:
    """An expired key set is refetched, and the new keys are used."""

    async def scenario(oidc: JWTAuthenticator) -> None:
        old = issuer.token()
        issuer.rotate()
        clock.now += 61
        assert (await principal_of([oidc], issuer.token())).subject == "alice"
        with pytest.raises(UnauthorizedError):
            await principal_of([oidc], old)

    run(authenticator(entry(jwksCacheTtl=60)), scenario)


def test_no_keys_is_503(issuer: Issuer) -> None:
    """Without a key set (issuer down since startup), 503 with Retry-After."""
    issuer.down = True
    (result,) = authenticate(authenticator(), issuer.token())
    assert isinstance(result, ServiceUnavailableError)
    assert result.retry_after_seconds == jwt_auth._ISSUER_RETRY_AFTER


def test_concurrent_refresh_fetches_once(issuer: Issuer, clock: Clock) -> None:
    """Requests arriving during a refresh wait for it instead of repeating it."""

    async def scenario(oidc: JWTAuthenticator) -> None:
        before = issuer.jwks_calls
        clock.now += 61
        tokens = [issuer.token(jti=str(i)) for i in range(5)]
        await asyncio.gather(*(principal_of([oidc], t) for t in tokens))
        assert issuer.jwks_calls == before + 1

    run(authenticator(entry(jwksCacheTtl=60)), scenario)


# -- unknown kid ---------------------------------------------------------------------


def test_unknown_kid_refetches_once(issuer: Issuer, clock: Clock) -> None:
    """After a key rotation, the first new token refetches the JWKS once."""

    async def scenario(oidc: JWTAuthenticator) -> None:
        before = issuer.jwks_calls
        issuer.rotate()
        for jti in ("1", "2"):
            principal = await principal_of([oidc], issuer.token(jti=jti))
            assert principal.subject == "alice"
        assert issuer.jwks_calls == before + 1

    run(authenticator(), scenario)


def test_unknown_kid_rate_limited(issuer: Issuer, clock: Clock) -> None:
    """At most one refetch per 30 s for unknown kids; still unknown is 401."""
    stranger = ECKey.generate_key("P-256", auto_kid=True)
    other = ECKey.generate_key("P-256", auto_kid=True)

    async def scenario(oidc: JWTAuthenticator) -> None:
        before = issuer.jwks_calls
        with pytest.raises(UnauthorizedError):
            await principal_of([oidc], issuer.token(key=stranger))
        assert issuer.jwks_calls == before + 1
        clock.now += 29
        with pytest.raises(UnauthorizedError):
            await principal_of([oidc], issuer.token(key=other))
        assert issuer.jwks_calls == before + 1
        clock.now += 2
        issuer.published.append(other)
        assert (await principal_of([oidc], issuer.token(key=other))).subject
        assert issuer.jwks_calls == before + 2

    run(authenticator(), scenario)


def test_unknown_kid_with_issuer_down(issuer: Issuer, clock: Clock) -> None:
    """An unknown kid while the JWKS can't be fetched is a 401, not a 500."""
    stranger = ECKey.generate_key("P-256", auto_kid=True)

    async def scenario(oidc: JWTAuthenticator) -> None:
        issuer.down = True
        with pytest.raises(UnauthorizedError):
            await principal_of([oidc], issuer.token(key=stranger))
        assert (await principal_of([oidc], issuer.token())).subject == "alice"

    run(authenticator(), scenario)


# -- delegation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("act", "actor"),
    [
        ({"sub": "engine"}, Actor(ISSUER, "engine")),
        ({"sub": "x", "iss": OTHER_ISSUER}, Actor(OTHER_ISSUER, "x")),
        ({"sub": "x", "act": {"sub": "y"}}, Actor(ISSUER, "x")),
    ],
    ids=["same-issuer", "other-issuer", "nested-ignored"],
)
def test_act_claim_is_actor(issuer: Issuer, act: Any, actor: Actor) -> None:
    """An RFC 8693 `act` claim sets the actor; the subject stays the owner."""
    (principal,) = authenticate(authenticator(), issuer.token(act=act))
    assert principal.actor == actor
    assert principal.owner == f"{ISSUER}|alice"


@pytest.mark.parametrize(
    "act",
    ["engine", ["engine"], {}, {"sub": ""}, {"sub": 1}, {"sub": "x", "iss": 1}],
    ids=str,
)
def test_malformed_act_is_401(issuer: Issuer, act: Any) -> None:
    """A malformed `act` claim is a 401."""
    (result,) = authenticate(authenticator(), issuer.token(act=act))
    assert isinstance(result, UnauthorizedError)
