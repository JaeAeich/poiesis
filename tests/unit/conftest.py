"""Shared fixtures: a fake OIDC issuer on a fake network (see `fake_issuer`)."""

from typing import Any

import httpx
import pytest
from fake_issuer import AUDIENCE, ISSUER, Issuer, Network


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
