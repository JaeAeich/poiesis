"""Shared fixtures: fake issuers on a fake network (see `fake_issuer`)."""

import os
from typing import Any

import httpx
import pytest
from fake_issuer import AUDIENCE, ISSUER, Issuer, Network, set_issuers


@pytest.fixture(autouse=True)
def _no_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test without auth settings from the outer environment."""
    for name in list(os.environ):
        if name.startswith("POIESIS_AUTH_"):
            monkeypatch.delenv(name)


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
    """A fake issuer on the network, configured as Poiesis's only issuer."""
    set_issuers(monkeypatch, {"issuer": ISSUER, "audience": AUDIENCE})
    return network.add(Issuer())
