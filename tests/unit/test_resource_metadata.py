"""Tests for the protected resource metadata (RFC 9728) and 401 challenges."""

from typing import Any

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
from pydantic import ValidationError
from test_authn import TASKS, started_app

from poiesis.api.resource_metadata import WELL_KNOWN, challenge, metadata_url
from poiesis.api.settings import AuthSettings

RESOURCE = "https://poiesis.example.org"
METADATA = f"{RESOURCE}{WELL_KNOWN}"


@pytest.fixture
def resource(issuer: Issuer, monkeypatch: pytest.MonkeyPatch) -> str:
    """Configure `RESOURCE` as the public URL, next to the issuer."""
    monkeypatch.setenv("POIESIS_AUTH_RESOURCE", RESOURCE)
    return RESOURCE


def test_metadata(network: Network, monkeypatch: pytest.MonkeyPatch) -> None:
    """The document lists the issuers clients can get tokens from."""
    network.add(Issuer())
    network.add(Issuer(OTHER_ISSUER))
    network.add(Issuer(GATEWAY, static=True))
    set_issuers(
        monkeypatch,
        {"issuer": ISSUER, "audience": AUDIENCE, "requiredScopes": ["tes"]},
        {"issuer": OTHER_ISSUER, "audience": AUDIENCE, "requiredScopes": ["tes", "x"]},
        {"issuer": GATEWAY, "audience": AUDIENCE, "jwksUri": GATEWAY_JWKS},
    )
    monkeypatch.setenv("POIESIS_AUTH_RESOURCE", RESOURCE + "/")
    with started_app(monkeypatch) as client:
        response = client.get(WELL_KNOWN)
    assert response.status_code == 200  # noqa: PLR2004
    assert response.headers["cache-control"] == "max-age=3600"
    assert response.json() == {
        "resource": RESOURCE,
        "authorization_servers": [ISSUER, OTHER_ISSUER],
        "scopes_supported": ["tes", "x"],
        "bearer_methods_supported": ["header"],
        "resource_name": "Poiesis",
        "resource_documentation": "https://poiesis.jaeaeich.com",
    }


def test_metadata_names_from_service_info(
    resource: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The name and documentation follow the service-info settings."""
    monkeypatch.setenv("POIESIS_SERVICE_INFO_NAME", "Node 1")
    monkeypatch.setenv(
        "POIESIS_SERVICE_INFO_DOCUMENTATION_URL", "https://docs.example.org"
    )
    with started_app(monkeypatch) as client:
        document = client.get(WELL_KNOWN).json()
        info = client.get("/ga4gh/tes/v1/service-info").json()
    assert document["resource_name"] == info["name"] == "Node 1"
    assert document["resource_documentation"] == "https://docs.example.org"
    assert info["documentationUrl"].rstrip("/") == "https://docs.example.org"


def test_metadata_without_scopes(
    resource: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without required scopes, `scopes_supported` is left out."""
    with started_app(monkeypatch) as client:
        document = client.get(WELL_KNOWN).json()
    assert document["authorization_servers"] == [ISSUER]
    assert "scopes_supported" not in document


def test_metadata_of_resource_with_path(
    issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resource with a path has its metadata after the suffix (§3.1)."""
    monkeypatch.setenv("POIESIS_AUTH_RESOURCE", "https://example.org/poiesis")
    with started_app(monkeypatch) as client:
        assert client.get(WELL_KNOWN).status_code == 404  # noqa: PLR2004
        response = client.get(f"{WELL_KNOWN}/poiesis")
        assert response.json()["resource"] == "https://example.org/poiesis"
        challenge = client.get(TASKS).headers["www-authenticate"]
    assert challenge == (
        f'Bearer resource_metadata="https://example.org{WELL_KNOWN}/poiesis"'
    )


def test_no_metadata_without_resource(
    issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without `auth.resource` nothing is served; 401s still challenge."""
    with started_app(monkeypatch) as client:
        assert client.get(WELL_KNOWN).status_code == 404  # noqa: PLR2004
        missing = client.get(TASKS)
        invalid = client.get(TASKS, headers={"Authorization": "Bearer nope"})
    assert missing.headers["www-authenticate"] == "Bearer"
    assert invalid.headers["www-authenticate"] == 'Bearer error="invalid_token"'


def test_no_metadata_when_auth_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """With auth off there is nothing to discover."""
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    monkeypatch.setenv("POIESIS_AUTH_RESOURCE", RESOURCE)
    with started_app(monkeypatch) as client:
        assert client.get(WELL_KNOWN).status_code == 404  # noqa: PLR2004
        assert client.get(TASKS).status_code == 200  # noqa: PLR2004


@pytest.mark.parametrize(
    ("headers", "expected", "message"),
    [
        ({}, f'Bearer resource_metadata="{METADATA}"', "missing bearer token"),
        (
            {"Authorization": "Bearer a.b.c"},
            f'Bearer error="invalid_token", resource_metadata="{METADATA}"',
            "invalid token",
        ),
        (
            {"Authorization": "Basic eDpwb2lfbm9wZQ=="},
            f'Bearer error="invalid_token", resource_metadata="{METADATA}"',
            "invalid token",
        ),
    ],
    ids=["missing", "invalid", "basic"],
)
def test_401_points_to_metadata(
    resource: str,
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
    expected: str,
    message: str,
) -> None:
    """Every 401 names the metadata; the body stays as it was."""
    with started_app(monkeypatch) as client:
        response = client.get(TASKS, headers=headers)
    assert response.status_code == 401  # noqa: PLR2004
    assert response.headers["www-authenticate"] == expected
    assert response.json() == {"error": "unauthorized", "message": message}


def test_valid_token_gets_no_challenge(
    resource: str, issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only 401s carry the challenge."""
    with started_app(monkeypatch) as client:
        response = client.get(
            TASKS, headers={"Authorization": f"Bearer {issuer.token()}"}
        )
    assert response.status_code == 200  # noqa: PLR2004
    assert "www-authenticate" not in response.headers


@pytest.mark.parametrize("public", [True, False], ids=["resource", "no-resource"])
def test_missing_scope_challenges(
    issuer: Issuer, monkeypatch: pytest.MonkeyPatch, public: bool
) -> None:
    """A missing scope is a 403 naming the scopes a new token needs."""
    set_issuers(
        monkeypatch,
        {"issuer": ISSUER, "audience": AUDIENCE, "requiredScopes": ["tes", "x"]},
    )
    if public:
        monkeypatch.setenv("POIESIS_AUTH_RESOURCE", RESOURCE)
    with started_app(monkeypatch) as client:
        response = client.get(
            TASKS, headers={"Authorization": f"Bearer {issuer.token(scope='tes')}"}
        )
    expected = 'Bearer error="insufficient_scope", scope="tes x"'
    if public:
        expected += f', resource_metadata="{METADATA}"'
    assert response.status_code == 403  # noqa: PLR2004
    assert response.headers["www-authenticate"] == expected
    assert response.json() == {
        "error": "forbidden",
        "message": "token missing required scope(s): x",
    }


def test_policy_403_gets_no_challenge(
    resource: str, issuer: Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 403 a new token can't fix (the claim rule) carries no challenge."""
    set_issuers(
        monkeypatch,
        {
            "issuer": ISSUER,
            "audience": AUDIENCE,
            "requiredClaim": {"name": "groups", "values": ["lab"]},
        },
    )
    with started_app(monkeypatch) as client:
        response = client.get(
            TASKS, headers={"Authorization": f"Bearer {issuer.token()}"}
        )
    assert response.status_code == 403  # noqa: PLR2004
    assert "www-authenticate" not in response.headers


@pytest.mark.parametrize(
    "value",
    [
        "poiesis.example.org",
        "ftp://poiesis.example.org",
        "https://poiesis.example.org?x=1",
        "https://poiesis.example.org/#top",
        "https://user:pw@poiesis.example.org",
        'https://poiesis.example.org/"x',
        "https://poiesis.example.org/a b",
        "https://poiesis.example.org/\\",
        "https://poiesis.example.org/{x}",
    ],
)
def test_invalid_resource_refused(value: str) -> None:
    """The public URL must be a plain http(s) URL, safe to quote."""
    with pytest.raises(ValidationError, match="POIESIS_AUTH_RESOURCE"):
        AuthSettings(enabled=False, resource=value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (RESOURCE, RESOURCE),
        (f"{RESOURCE}/", RESOURCE),
        ("http://localhost:8000/tes/", "http://localhost:8000/tes"),
    ],
)
def test_resource_spelling(value: str, expected: str) -> None:
    """A trailing slash is dropped; the rest is kept as given."""
    assert AuthSettings(enabled=False, resource=value).resource == expected


@pytest.mark.parametrize(
    ("resource", "url"),
    [
        (RESOURCE, METADATA),
        ("http://localhost:8000", f"http://localhost:8000{WELL_KNOWN}"),
        ("https://h.org/a/b", f"https://h.org{WELL_KNOWN}/a/b"),
    ],
)
def test_metadata_url(resource: str, url: str) -> None:
    """The well-known suffix goes between the host and the path."""
    assert metadata_url(resource) == url


@pytest.mark.parametrize(
    ("settings", "error", "scopes", "expected"),
    [
        ({}, None, (), "Bearer"),
        ({}, "invalid_token", (), 'Bearer error="invalid_token"'),
        ({"resource": RESOURCE}, None, (), f'Bearer resource_metadata="{METADATA}"'),
        (
            {},
            "insufficient_scope",
            ("a", "b"),
            'Bearer error="insufficient_scope", scope="a b"',
        ),
    ],
)
def test_challenge(
    settings: dict[str, Any],
    error: str | None,
    scopes: tuple[str, ...],
    expected: str,
) -> None:
    """The challenge has the error code only for a bad credential or scope."""
    challenged = challenge(AuthSettings(enabled=False, **settings), error, scopes)
    assert challenged == expected


def test_invalid_resource_env_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The environment variable is checked like a value set in code."""
    monkeypatch.setenv("POIESIS_AUTH_RESOURCE", "https://poiesis.example.org?x")
    with pytest.raises(ValidationError, match="POIESIS_AUTH_RESOURCE"):
        AuthSettings(enabled=False)
