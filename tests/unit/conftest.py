"""Shared fixtures: a fake OIDC issuer on a fake network.

All outgoing HTTP of the code under test goes through an
`httpx.MockTransport` that dispatches by host, so tests see every
request Poiesis sends without a real network.
"""

import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from joserfc import jwt
from joserfc.jwk import ECKey

ISSUER = "https://issuer.example.org"
AUDIENCE = "poiesis"

Handler = Callable[[httpx.Request], httpx.Response]


class Network:
    """Routes requests to a handler per host and records them."""

    def __init__(self) -> None:
        """Start without hosts."""
        self.hosts: dict[str, Handler] = {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Record `request` and answer it with its host's handler."""
        self.requests.append(request)
        handler = self.hosts.get(request.url.host)
        if handler is None:
            raise httpx.ConnectError("unknown host", request=request)
        return handler(request)


class Issuer:
    """A fake OIDC issuer: discovery, JWKS, userinfo; mints tokens."""

    def __init__(self) -> None:
        """Generate a signing key; userinfo echoes the token's `sub`."""
        self.key = ECKey.generate_key("P-256", auto_kid=True)
        self.userinfo: dict[str, Any] = {}
        self.userinfo_handler: Handler | None = None
        self.userinfo_calls = 0
        self.tokens: dict[str, dict[str, Any]] = {}

    def token(self, **claims: Any) -> str:
        """Mint an access token for `alice`, valid five minutes, plus `claims`."""
        payload = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "alice",
            "exp": int(time.time()) + 300,
        } | claims
        token = jwt.encode({"alg": "ES256", "kid": self.key.kid}, payload, self.key)
        self.tokens[token] = payload
        return token

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Serve discovery, JWKS and userinfo."""
        path = request.url.path
        if path.endswith("openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "jwks_uri": f"{ISSUER}/jwks",
                    "userinfo_endpoint": f"{ISSUER}/userinfo",
                },
            )
        if path.endswith("jwks"):
            return httpx.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        self.userinfo_calls += 1
        if self.userinfo_handler is not None:
            return self.userinfo_handler(request)
        token = request.headers["authorization"].removeprefix("Bearer ")
        return httpx.Response(
            200, json={"sub": self.tokens[token]["sub"]} | self.userinfo
        )


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> Network:
    """Route every `httpx.AsyncClient` to a fresh fake network."""
    net = Network()
    real = httpx.AsyncClient

    def client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real(*args, transport=httpx.MockTransport(net), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return net


@pytest.fixture
def issuer(network: Network, monkeypatch: pytest.MonkeyPatch) -> Issuer:
    """A fake issuer on the network, configured as Poiesis's issuer."""
    fake = Issuer()
    network.hosts["issuer.example.org"] = fake
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "true")
    monkeypatch.setenv("POIESIS_AUTH_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("POIESIS_AUTH_OIDC_AUDIENCE", AUDIENCE)
    return fake
