"""Fake token issuers on a fake network, for the auth tests.

All outgoing HTTP of the code under test goes through an
`httpx.MockTransport` that dispatches by host, so tests see every
request Poiesis sends without a real network.
"""

import json
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from joserfc import jwt
from joserfc.jwk import ECKey

ISSUER = "https://issuer.example.org"
#: A second OIDC issuer, side by side with the first.
OTHER_ISSUER = "https://other.example.org"
#: A gateway that signs its own JWTs and only publishes keys (no discovery).
GATEWAY = "https://gateway.example.org"
GATEWAY_JWKS = f"{GATEWAY}/keys.json"
AUDIENCE = "poiesis"

Handler = Callable[[httpx.Request], httpx.Response]


def set_issuers(monkeypatch: pytest.MonkeyPatch, *entries: dict[str, Any]) -> None:
    """Enable auth with `entries` as `POIESIS_AUTH_ISSUERS`."""
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "true")
    monkeypatch.setenv("POIESIS_AUTH_ISSUERS", json.dumps(list(entries)))


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

    def add(self, issuer: "Issuer") -> "Issuer":
        """Put `issuer` on the network under its host; return it."""
        self.hosts[httpx.URL(issuer.url).host] = issuer
        return issuer

    def paths(self, host: str) -> list[str]:
        """Return the paths requested from `host`, in order."""
        return [r.url.path for r in self.requests if r.url.host == host]


class Issuer:
    """A fake issuer: discovery (unless static), JWKS, userinfo; mints tokens.

    With `static`, only the key set is served, at `/keys.json`, like a
    gateway that signs its own JWTs. `down` makes every request fail like
    an unreachable host; `jwks_handler` replaces the JWKS answer.
    """

    def __init__(self, url: str = ISSUER, *, static: bool = False) -> None:
        """Generate a signing key; userinfo echoes the token's `sub`."""
        self.url = url
        self.static = static
        self.key = ECKey.generate_key("P-256", auto_kid=True)
        self.published = [self.key]
        self.discovery: dict[str, Any] = {
            "issuer": url,
            "jwks_uri": f"{url}/jwks",
            "userinfo_endpoint": f"{url}/userinfo",
        }
        self.down = False
        self.jwks_handler: Handler | None = None
        self.jwks_calls = 0
        self.userinfo: dict[str, Any] = {}
        self.userinfo_handler: Handler | None = None
        self.userinfo_calls = 0
        self.tokens: dict[str, dict[str, Any]] = {}

    def rotate(self) -> None:
        """Sign with a new key and publish only that one."""
        self.key = ECKey.generate_key("P-256", auto_kid=True)
        self.published = [self.key]

    def token(
        self,
        key: ECKey | None = None,
        *,
        typ: str | None = "at+jwt",
        **claims: Any,
    ) -> str:
        """Mint an access token for `alice`, valid five minutes, plus `claims`.

        `typ` is the header's token type: RFC 9068's `at+jwt` by default,
        none for `None`.
        """
        key = key or self.key
        payload = {
            "iss": self.url,
            "aud": AUDIENCE,
            "sub": "alice",
            "exp": int(time.time()) + 300,
        } | claims
        header = {"alg": "ES256", "kid": key.kid}
        if typ is not None:
            header["typ"] = typ
        token = jwt.encode(header, payload, key, default_type=None)
        self.tokens[token] = payload
        return token

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Serve discovery, JWKS and userinfo."""
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if path.endswith("openid-configuration"):
            if self.static:
                return httpx.Response(404)
            return httpx.Response(200, json=self.discovery)
        if path.endswith(("/jwks", "/keys.json")):
            self.jwks_calls += 1
            if self.jwks_handler is not None:
                return self.jwks_handler(request)
            keys = [key.as_dict(private=False) for key in self.published]
            return httpx.Response(200, json={"keys": keys})
        self.userinfo_calls += 1
        if self.userinfo_handler is not None:
            return self.userinfo_handler(request)
        token = request.headers["authorization"].removeprefix("Bearer ")
        return httpx.Response(
            200, json={"sub": self.tokens[token]["sub"]} | self.userinfo
        )
