"""Tests for the audit log itself: line format, request id, on and off.

What each route writes is tested next to the route (`test_authz.py`
for tasks, `test_api_keys.py` for keys); this covers `poiesis.api.audit`.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from poiesis.api import audit
from poiesis.api.auth import Actor, Principal, is_owner_id
from poiesis.api.settings import AuditSettings

ISSUER = "https://issuer.example.org"


def lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    """Parse what was written to stdout as audit lines (each must be JSON)."""
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def echo_app() -> TestClient:
    """An app whose one route writes an audit line and returns its request id."""
    app = FastAPI()
    app.add_middleware(audit.RequestIdMiddleware)

    @app.get("/")
    async def root() -> dict[str, str]:
        audit.emit("task.list", audit.ALLOW)
        return {"request_id": audit.request_id()}

    return TestClient(app)


def test_line(capsys: pytest.CaptureFixture[str]) -> None:
    """One JSON object per line: time, event, outcome, request id, principal."""
    principal = Principal(
        issuer=ISSUER,
        subject="alice",
        via="oidc",
        credential_id="jti-1",
        actor=Actor(issuer=ISSUER, subject="gateway"),
        claims={"azp": "portal", "groups": ["secret-group"]},
    )
    audit.emit("task.get", audit.DENY, principal, task_id="t", admin=False, gone=None)
    (line,) = lines(capsys)
    assert list(line)[:4] == ["ts", "event", "outcome", "request_id"]
    assert line["ts"].endswith("Z")
    assert datetime.fromisoformat(line["ts"]).utcoffset() is not None
    uuid.UUID(line["request_id"])
    assert {k: v for k, v in line.items() if k not in {"ts", "request_id"}} == {
        "event": "task.get",
        "outcome": "deny",
        "owner": f"{ISSUER}|alice",
        "issuer": ISSUER,
        "via": "oidc",
        "credential_id": "jti-1",
        "client": "portal",
        "actor": {"iss": ISSUER, "sub": "gateway"},
        "task_id": "t",
        "admin": False,
    }


def test_line_leaves_out_what_is_unset(capsys: pytest.CaptureFixture[str]) -> None:
    """No credential id, client or actor: the keys are absent, not null."""
    principal = Principal(issuer=ISSUER, subject="alice", via="oidc", claims={})
    audit.emit("task.list", audit.ALLOW, principal)
    (line,) = lines(capsys)
    assert not {"credential_id", "client", "actor"} & line.keys()
    assert None not in line.values()


def test_client_not_a_string_left_out(capsys: pytest.CaptureFixture[str]) -> None:
    """The client is an unchecked claim: anything but a string is left out."""
    principal = Principal(issuer=ISSUER, subject="a", via="oidc", claims={"azp": [1]})
    audit.emit("task.list", audit.ALLOW, principal)
    assert "client" not in lines(capsys)[0]


class _Recorder(logging.Handler):
    """Keeps the records it gets."""

    def __init__(self) -> None:
        """Start empty."""
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Keep the record."""
        self.records.append(record)


def test_own_handler(capsys: pytest.CaptureFixture[str]) -> None:
    """Audit lines skip the app's (root) handlers and go to stdout only."""
    root = logging.getLogger()
    recorder = _Recorder()
    root.addHandler(recorder)
    try:
        audit.emit("task.list", audit.ALLOW)
    finally:
        root.removeHandler(recorder)
    assert recorder.records == []
    assert len(lines(capsys)) == 1


def test_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    """Turned off, nothing is written; turned on again, lines are back."""
    audit.configure(enabled=False)
    audit.emit("task.list", audit.ALLOW)
    assert capsys.readouterr().out == ""
    audit.configure(enabled=True)
    audit.configure(enabled=True)  # idempotent: still one line per event
    audit.emit("task.list", audit.ALLOW)
    assert len(lines(capsys)) == 1


@pytest.mark.parametrize("sent", ["abc-123", "0f0e/req:1@gw", "x" * 128])
def test_request_id_echoed(sent: str, capsys: pytest.CaptureFixture[str]) -> None:
    """A sent X-Request-ID is kept, echoed and written to the audit line."""
    response = echo_app().get("/", headers={"X-Request-ID": sent})
    assert response.headers["x-request-id"] == sent
    assert response.json()["request_id"] == sent
    assert lines(capsys)[0]["request_id"] == sent


@pytest.mark.parametrize("sent", [None, "", "x" * 129, "a b", "naïve".encode(), "a\tb"])
def test_request_id_generated(
    sent: str | bytes | None, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without a usable X-Request-ID, a new UUID is used and echoed."""
    headers = {} if sent is None else {"X-Request-ID": sent}
    response = echo_app().get("/", headers=headers)
    generated = response.headers["x-request-id"]
    assert generated != sent
    uuid.UUID(generated)
    assert lines(capsys)[0]["request_id"] == generated


def test_request_id_per_request() -> None:
    """Each request gets its own id; outside a request there is a fresh one."""
    client = echo_app()
    ids = {client.get("/").headers["x-request-id"] for _ in range(3)}
    assert len(ids) == 3  # noqa: PLR2004
    assert audit.request_id() != audit.request_id()


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        (f"{ISSUER}|alice", True),
        ("ns|a|b", True),
        ("", False),
        ("alice", False),
        ("|alice", False),
        ("ns|", False),
        ("ns|" + "a" * 1021, True),
        ("ns|" + "a" * 1022, False),
    ],
)
def test_owner_ids(value: str, *, valid: bool) -> None:
    """An owner id is `namespace|subject`, both non-empty, not overly long."""
    assert is_owner_id(value) is valid


@pytest.mark.parametrize(
    ("value", "enabled"), [("", True), ("true", True), ("off", False), ("0", False)]
)
def test_settings(
    monkeypatch: pytest.MonkeyPatch, value: str, *, enabled: bool
) -> None:
    """`POIESIS_AUDIT_ENABLED` is a boolean, on by default."""
    monkeypatch.setenv("POIESIS_AUDIT_ENABLED", value)
    assert AuditSettings().enabled is enabled


@pytest.mark.parametrize("value", ["of", "disabled", "2"])
def test_settings_typo_refused(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """An unrecognised boolean refuses to start rather than guess."""
    monkeypatch.setenv("POIESIS_AUDIT_ENABLED", value)
    with pytest.raises(ValueError, match="POIESIS_AUDIT_ENABLED"):
        AuditSettings()
