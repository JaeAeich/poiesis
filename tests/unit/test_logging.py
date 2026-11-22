"""Tests for the shared log setup and the API access log.

The format (JSON off a terminal, text on one, forced by
``POIESIS_LOG_FORMAT``), the request and task ids on every line, the
access log's line (no query strings, no headers), and that audit lines
are left as they were.
"""

import io
import json
import logging
import threading
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import click
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from poiesis.api import access_log, audit
from poiesis.api.access_log import AccessLogMiddleware
from poiesis.api.settings import Settings
from poiesis.cli.env import configure_logging
from poiesis.core import logging_config
from poiesis.core.logging_config import (
    LOG_FORMAT_ENV,
    resolve_format,
    set_task_id,
    setup_logging,
    task_context,
)

TASK_ID = "0b6a5b0e-6c8e-4c1e-9b8a-3f7d2a1c9e10"
SECRET = "s3cr3t-token-value"


class Tty(io.StringIO):
    """A stream that says it is a terminal."""

    def isatty(self) -> bool:
        """Yes."""
        return True


@pytest.fixture(autouse=True)
def _restore_logging(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Put the import-time setup back after each test."""
    monkeypatch.delenv(LOG_FORMAT_ENV, raising=False)
    monkeypatch.setattr(logging_config, "_process_task_id", None)
    yield
    setup_logging()


def capture(log_format: str | None = None, level: str = "INFO") -> io.StringIO:
    """Set up logging into a (non-terminal) buffer and return it."""
    stream = io.StringIO()
    setup_logging(level=level, log_format=log_format, stream=stream)
    return stream


def lines(stream: io.StringIO) -> list[dict[str, Any]]:
    """Every line written, each parsed as JSON (so each must be JSON).

    Lines of the test client (``httpx``) are left out.
    """
    parsed = [json.loads(line) for line in stream.getvalue().splitlines()]
    return [line for line in parsed if line["logger"] != "httpx"]


def test_json_line_fields() -> None:
    """Time (RFC 3339 UTC), level, logger, message; no ids when none is set."""
    stream = capture()
    logging.getLogger("poiesis.core.x").warning("hello %s", "world")
    (line,) = lines(stream)
    assert list(line) == ["timestamp", "level", "logger", "message"]
    assert line["timestamp"].endswith("Z")
    assert datetime.fromisoformat(line["timestamp"]).utcoffset().total_seconds() == 0
    assert line["level"] == "WARNING"
    assert line["logger"] == "poiesis.core.x"
    assert line["message"] == "hello world"


def test_json_line_exception_and_extra() -> None:
    """An exception's text is one field; ``extra`` fields are kept."""
    stream = capture()
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("x").exception("failed", extra={"attempt": 2})
    (line,) = lines(stream)
    assert line["attempt"] == 2
    assert "ValueError: boom" in line["exception"]
    assert "\n" not in stream.getvalue().rstrip("\n")


def test_task_id_for_the_process_and_its_threads() -> None:
    """set_task_id tags every later line, also from other threads."""
    stream = capture()
    set_task_id(TASK_ID)
    logging.getLogger("a").info("main")
    thread = threading.Thread(target=lambda: logging.getLogger("b").info("thread"))
    thread.start()
    thread.join()
    assert [line["task_id"] for line in lines(stream)] == [TASK_ID, TASK_ID]


def test_task_context_is_scoped() -> None:
    """task_context tags the lines inside the block only (tctl)."""
    stream = capture()
    with task_context(TASK_ID):
        logging.getLogger("poiesis.core.tctl").info("inside")
    logging.getLogger("poiesis.core.tctl").info("outside")
    inside, outside = lines(stream)
    assert inside["task_id"] == TASK_ID
    assert "task_id" not in outside


@pytest.mark.parametrize(
    ("value", "stream", "expected"),
    [
        (None, io.StringIO(), "json"),
        ("", Tty(), "text"),
        (None, Tty(), "text"),
        ("json", Tty(), "json"),
        ("TEXT", io.StringIO(), "text"),
    ],
)
def test_format_selection(
    value: str | None, stream: io.StringIO, expected: str
) -> None:
    """Unset: text on a terminal, JSON otherwise; a set value wins."""
    assert resolve_format(value, stream) == expected


def test_unknown_format_is_refused() -> None:
    """A typo is an error where it is read strictly."""
    with pytest.raises(ValueError, match=LOG_FORMAT_ENV):
        resolve_format("yaml", io.StringIO())


def test_terminal_gets_colour_and_others_none() -> None:
    """ANSI colour codes only on a terminal."""
    tty = Tty()
    setup_logging(level="INFO", stream=tty)
    with task_context(TASK_ID):
        logging.getLogger("poiesis.core.trec").info("hi")
    assert "\033[92mINFO\033[0m" in tty.getvalue()
    assert f"task_id={TASK_ID}" in tty.getvalue()
    stream = capture()
    logging.getLogger("poiesis.core.trec").info("hi")
    assert "\033[" not in stream.getvalue()


def test_env_forces_the_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """POIESIS_LOG_FORMAT=text gives text even off a terminal."""
    monkeypatch.setenv(LOG_FORMAT_ENV, "text")
    stream = capture()
    logging.getLogger("x").info("plain")
    assert stream.getvalue().split(" ", 2)[2].startswith("\033[92mINFO")


def test_bad_env_falls_back_to_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """The import-time setup never fails: JSON and a warning line."""
    monkeypatch.setenv(LOG_FORMAT_ENV, "yaml")
    stream = capture()
    (line,) = lines(stream)
    assert line["level"] == "WARNING"
    assert LOG_FORMAT_ENV in line["message"]


def test_cli_refuses_a_bad_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """trec/tif/tof/tctl stop at startup on an unknown format."""
    monkeypatch.setenv(LOG_FORMAT_ENV, "yaml")
    with pytest.raises(click.ClickException, match=LOG_FORMAT_ENV):
        configure_logging(TASK_ID)


def test_cli_sets_the_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """configure_logging(task_id) tags the process's lines."""
    monkeypatch.setenv(LOG_FORMAT_ENV, "json")
    configure_logging(TASK_ID)
    assert logging_config._process_task_id == TASK_ID


def test_settings_read_the_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """The API's setting is strict and reaches the TaskPod config."""
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    monkeypatch.setenv(LOG_FORMAT_ENV, "text")
    assert Settings().runtime_config().log_format == "text"
    monkeypatch.delenv(LOG_FORMAT_ENV)
    assert Settings().runtime_config().log_format is None
    monkeypatch.setenv(LOG_FORMAT_ENV, "yaml")
    with pytest.raises(ValueError, match=LOG_FORMAT_ENV):
        Settings()


def access_app() -> TestClient:
    """An app with the API's two middlewares; ``/me`` is an authenticated route."""
    app = FastAPI()
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(audit.RequestIdMiddleware)

    @app.get("/me")
    async def me() -> dict[str, str]:
        access_log.note_owner("https://issuer.example.org|alice")
        logging.getLogger("poiesis.api.x").info("serving")
        audit.emit("task.list", audit.ALLOW)
        return {}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {}

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("boom")

    return TestClient(app, raise_server_exceptions=False)


def test_access_line(capsys: pytest.CaptureFixture[str]) -> None:
    """One line per request; no query string, header or body in any line."""
    stream = capture()
    response = access_app().get(
        f"/me?token={SECRET}",
        headers={"Authorization": f"Bearer {SECRET}", "X-Request-ID": "req-1"},
    )
    assert response.headers["x-request-id"] == "req-1"
    app_line, access = lines(stream)
    assert app_line["request_id"] == "req-1"
    assert app_line["message"] == "serving"
    assert access["logger"] == "poiesis.access"
    assert access["level"] == "INFO"
    assert access["message"] == "GET /me 200"
    assert access["request_id"] == "req-1"
    assert {k: access[k] for k in ("method", "path", "status")} == {
        "method": "GET",
        "path": "/me",
        "status": 200,
    }
    assert access["owner"] == "https://issuer.example.org|alice"
    assert isinstance(access["duration_ms"], float)
    out = capsys.readouterr().out
    ours = json.dumps([app_line, access])
    assert SECRET not in ours
    assert SECRET not in out
    assert "token=" not in ours


def test_access_line_on_error_and_without_owner() -> None:
    """An unhandled error is logged as 500; no owner when none authenticated."""
    stream = capture()
    access_app().get("/boom")
    access = next(line for line in lines(stream) if line["logger"] == "poiesis.access")
    assert access["status"] == 500
    assert "owner" not in access


def test_probes_are_debug() -> None:
    """Probe lines are DEBUG: absent at INFO, present at DEBUG."""
    stream = capture()
    access_app().get("/healthz")
    assert lines(stream) == []
    stream = capture(level="DEBUG")
    access_app().get("/healthz")
    (line,) = [x for x in lines(stream) if x["logger"] == "poiesis.access"]
    assert line["level"] == "DEBUG"
    assert line["path"] == "/healthz"


def test_audit_lines_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    """Audit lines stay on stdout in their own format, not the app's."""
    stream = capture()
    access_app().get("/me", headers={"X-Request-ID": "req-2"})
    (audit_line,) = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert list(audit_line)[:4] == ["ts", "event", "outcome", "request_id"]
    assert audit_line["request_id"] == "req-2"
    assert "timestamp" not in audit_line
    assert all(line["logger"] != "poiesis.audit" for line in lines(stream))
