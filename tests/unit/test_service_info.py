"""Tests for `GET /service-info` and its settings (`POIESIS_SERVICE_INFO_*`)."""

import json
from datetime import UTC, datetime
from importlib import resources
from importlib.metadata import version
from typing import Any

import httpx
import pytest
import yaml
from fake_issuer import Issuer, Network
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_authn import TASKS, started_app

from poiesis.api.app import create_app
from poiesis.api.constants import get_poiesis_api_constants
from poiesis.api.settings import ServiceInfoSettings

SERVICE_INFO = "/ga4gh/tes/v1/service-info"
PDP = "https://pdp.example.org/access/v1/evaluation"

CONFIGURED = {
    "ID": "org.example.tes.prod",
    "NAME": "Example TES",
    "DESCRIPTION": "Example's TES for genomics",
    "ORGANIZATION_NAME": "Example",
    "ORGANIZATION_URL": "https://example.org/",
    "CONTACT_URL": "mailto:tes@example.org",
    "DOCUMENTATION_URL": "https://docs.example.org/tes",
    "ENVIRONMENT": "prod",
    "CREATED_AT": "2026-01-15T09:00:00Z",
}


def configure(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    """Set `POIESIS_SERVICE_INFO_<key>` for each of `values`."""
    for key, value in values.items():
        monkeypatch.setenv(f"POIESIS_SERVICE_INFO_{key}", value)


def service_info(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Build the app from the environment (auth off) and get the service info."""
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    response = TestClient(create_app()).get(SERVICE_INFO)
    assert response.status_code == 200  # noqa: PLR2004
    return response.json()


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset, the fields keep their built-in values; no `environment`."""
    before = datetime.now(UTC)
    info = service_info(monkeypatch)
    assert info["id"] == "org.ga4gh.poiesis"
    assert info["name"] == "Poiesis"
    assert info["description"] == "GA4GH TES (Task Execution Service) on Kubernetes"
    assert info["organization"] == {
        "name": "Poiesis",
        "url": "https://poiesis.jaeaeich.com/",
    }
    assert info["contactUrl"].startswith("mailto:")
    assert info["documentationUrl"] == "https://poiesis.jaeaeich.com/"
    assert "environment" not in info
    # As before: the time of the request.
    assert datetime.fromisoformat(info["createdAt"]) >= before
    assert info["type"] == {
        "group": "org.ga4gh",
        "artifact": "tes",
        "version": "1.1.0",
    }


def test_version_is_poiesis(monkeypatch: pytest.MonkeyPatch) -> None:
    """`version` is the Poiesis version; the TES version is `type.version`."""
    info = service_info(monkeypatch)
    assert info["version"] == version("poiesis")


def test_tes_version_matches_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    """`type.version` and the OpenAPI version are the shipped spec's version.

    GA4GH service-info types use bare semantic versions (`1.1.0`, no `v`);
    registries match `type.version` against them.
    """
    spec_file = f"{get_poiesis_api_constants().SPEC_GIT_HASH}.openapi.yaml"
    spec = yaml.safe_load(
        (resources.files("poiesis.api.tes") / "spec" / spec_file).read_text()
    )
    info = service_info(monkeypatch)
    assert info["type"]["version"] == spec["info"]["version"]
    openapi = TestClient(create_app()).get("/openapi.json").json()
    assert openapi["info"]["version"] == spec["info"]["version"]


def test_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every deployment-specific field comes from its setting."""
    configure(monkeypatch, **CONFIGURED)
    info = service_info(monkeypatch)
    assert info["id"] == "org.example.tes.prod"
    assert info["name"] == "Example TES"
    assert info["description"] == "Example's TES for genomics"
    assert info["organization"] == {"name": "Example", "url": "https://example.org/"}
    assert info["contactUrl"] == "mailto:tes@example.org"
    assert info["documentationUrl"] == "https://docs.example.org/tes"
    assert info["environment"] == "prod"
    assert info["createdAt"] == "2026-01-15T09:00:00Z"
    assert info["version"] == version("poiesis")


#: The service-info field each setting changes.
FIELDS = {
    "ID": "id",
    "NAME": "name",
    "DESCRIPTION": "description",
    "ORGANIZATION_NAME": "organization",
    "ORGANIZATION_URL": "organization",
    "CONTACT_URL": "contactUrl",
    "DOCUMENTATION_URL": "documentationUrl",
    "ENVIRONMENT": "environment",
    "CREATED_AT": "createdAt",
}


@pytest.mark.parametrize("key", sorted(FIELDS))
def test_each_field_alone(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    """A setting set alone changes its field only."""
    default = service_info(monkeypatch)
    configure(monkeypatch, **{key: CONFIGURED[key]})
    info = service_info(monkeypatch)
    # The time of the request, unless configured.
    volatile = {"createdAt", "updatedAt"} - {FIELDS[key]}
    changed = {
        name
        for name in default.keys() | info.keys()
        if name not in volatile and default.get(name) != info.get(name)
    }
    assert changed == {FIELDS[key]}


def test_created_at_with_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    """`createdAt` keeps the configured instant, also with another offset."""
    configure(monkeypatch, CREATED_AT="2026-01-15T10:00:00+01:00")
    created = datetime.fromisoformat(service_info(monkeypatch)["createdAt"])
    assert created == datetime(2026, 1, 15, 9, tzinfo=UTC)


def test_contact_url_may_be_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """`contactUrl` may be a contact form instead of an email address."""
    configure(monkeypatch, CONTACT_URL="https://example.org/contact")
    assert service_info(monkeypatch)["contactUrl"] == "https://example.org/contact"


@pytest.mark.parametrize("value", ["", "  "])
def test_empty_is_unset(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Empty values count as unset: built-in values, no `environment`."""
    configure(monkeypatch, **dict.fromkeys(CONFIGURED, value))
    info = service_info(monkeypatch)
    assert info["id"] == "org.ga4gh.poiesis"
    assert info["name"] == "Poiesis"
    assert "environment" not in info


INVALID = [
    ("ORGANIZATION_URL", "example.org"),
    ("ORGANIZATION_URL", "ftp://example.org"),
    ("ORGANIZATION_URL", "https://"),
    ("ORGANIZATION_URL", "https://example.org:99999"),
    ("DOCUMENTATION_URL", "/docs"),
    ("DOCUMENTATION_URL", "https://example.org/a b"),
    ("DOCUMENTATION_URL", "mailto:tes@example.org"),
    ("CONTACT_URL", "tes@example.org"),
    ("CONTACT_URL", "mailto:"),
    ("CONTACT_URL", "javascript:alert(1)"),
    ("CREATED_AT", "yesterday"),
    ("CREATED_AT", "2026-01-15"),
    ("CREATED_AT", "2026-01-15T09:00:00"),
    ("CREATED_AT", "2026-13-01T09:00:00Z"),
]


@pytest.mark.parametrize(("key", "value"), INVALID, ids=str)
def test_invalid_env_refused(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    """An invalid value refuses to start, naming the variable."""
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    configure(monkeypatch, **{key: value})
    with pytest.raises(ValidationError, match=f"POIESIS_SERVICE_INFO_{key}"):
        create_app()


@pytest.mark.parametrize(
    "values",
    [
        {"id": ""},
        {"name": ""},
        {"organization_url": "ftp://example.org"},
        {"contact_url": "example.org"},
        {"created_at": "2026-01-15T09:00:00"},
        {"created_at": datetime(2026, 1, 15)},  # noqa: DTZ001 (no tzinfo, refused)
        {"created_at": 1767000000},
    ],
    ids=str,
)
def test_invalid_values_refused(values: dict[str, Any]) -> None:
    """Invalid values are refused when given directly, too."""
    with pytest.raises(ValidationError):
        ServiceInfoSettings(**values)


@pytest.fixture
def pdp(
    issuer: Issuer, network: Network, monkeypatch: pytest.MonkeyPatch
) -> list[dict[str, Any]]:
    """Allow everything at a stub decision service; return its request bodies."""
    bodies: list[dict[str, Any]] = []

    def decide(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"decision": True})

    network.hosts["pdp.example.org"] = decide
    monkeypatch.setenv("POIESIS_AUTHZ_DECISION_SERVICE_URL", PDP)
    return bodies


@pytest.mark.parametrize(
    ("configured", "expected"),
    [(None, "org.ga4gh.poiesis"), ("org.example.tes.prod", "org.example.tes.prod")],
)
def test_decision_service_gets_the_id(
    issuer: Issuer,
    pdp: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    configured: str | None,
    expected: str,
) -> None:
    """The decision service is sent the deployment's service-info `id`."""
    if configured is not None:
        configure(monkeypatch, ID=configured)
    with started_app(monkeypatch) as client:
        headers = {"Authorization": f"Bearer {issuer.token()}"}
        assert client.get(TASKS, headers=headers).status_code == 200  # noqa: PLR2004
        assert client.get(SERVICE_INFO).json()["id"] == expected
    assert pdp
    assert {body["context"]["tes"]["service_id"] for body in pdp} == {expected}
