"""Shared fixtures: fake issuers on a fake network (see `fake_issuer`)."""

import os
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fake_issuer import AUDIENCE, ISSUER, Issuer, Network, set_issuers

from poiesis.api import audit


@pytest.fixture(autouse=True)
def _no_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test without auth (or service-info) settings from outside."""
    for name in list(os.environ):
        if name.startswith(("POIESIS_AUTH_", "POIESIS_SERVICE_INFO_")):
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


@pytest.fixture(autouse=True)
def _audit_on() -> Iterator[None]:
    """Start and end every test with the audit log on, as by default."""
    audit.configure(enabled=True)
    yield
    audit.configure(enabled=True)
