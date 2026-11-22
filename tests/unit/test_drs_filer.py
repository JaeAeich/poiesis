"""Tests for `drs://` inputs, resolved by `DrsFilerStrategy`.

A recording HTTP server in a thread plays the DRS server and the data
server, so the requests and headers on the wire are those of a real
resolution and download. `_API_URL` points DRS hosts at it.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from poiesis.api.settings import Settings
from poiesis.api.tes.models import TesExecutor, TesFileType, TesInput, TesTask
from poiesis.core.constants import (
    DRS_ALLOWED_HOSTS_ENV,
    DRS_BEARER_TOKEN_ENV,
    DRS_ENABLED_ENV,
    DRS_OBJECT_STORES_ENV,
)
from poiesis.core.services.filer import filer_strategy_factory as factory
from poiesis.core.services.filer.strategy import drs_filer, filer_strategy
from poiesis.core.services.filer.strategy.drs_filer import DrsError, resolve
from poiesis.core.services.filer.tif import Tif
from poiesis.core.taskpod import RuntimeConfig, build_taskpod_job

HOST = "drs.example.org"
TOKEN = "drs-token-value"  # noqa: S105 - a test token
DATA = b">chr1\nACGT\n"


@dataclass
class Seen:
    """A request the server received: its path and headers."""

    path: str
    headers: dict[str, str]


@dataclass
class Drs:
    """The server: DRS objects by id, access answers by `id/access_id`."""

    port: int = 0
    objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    access: dict[str, dict[str, Any]] = field(default_factory=dict)
    seen: list[Seen] = field(default_factory=list)

    @property
    def data_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/data/file"


class Handler(http.server.BaseHTTPRequestHandler):
    """Serves `/<host>/ga4gh/drs/v1/objects/...` from `Drs` and `/data/*`."""

    server: Any

    def log_message(self, format, *args):
        """Keep the test output quiet."""

    def do_GET(self):
        drs: Drs = self.server.drs
        drs.seen.append(Seen(self.path, dict(self.headers)))
        if self.path == "/elsewhere":
            # Another origin: same server, other host name.
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{drs.port}/data/file")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/data/"):
            self._send(200, DATA, "application/octet-stream")
            return
        prefix = f"/{HOST}/ga4gh/drs/v1/objects/"
        rest = self.path.removeprefix(prefix)
        object_id, _, access_id = rest.partition("/access/")
        body = (
            drs.access.get(f"{object_id}/{access_id}")
            if access_id
            else drs.objects.get(object_id)
        )
        if body is None:
            self._send(404, b'{"msg": "not found"}', "application/json")
        else:
            self._send(200, json.dumps(body).encode(), "application/json")

    def _send(self, status: int, body: bytes, kind: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def drs(monkeypatch: pytest.MonkeyPatch) -> Iterator[Drs]:
    """The DRS server, with DRS turned on for any host."""
    state = Drs()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.drs = state  # type: ignore[attr-defined]
    state.port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        drs_filer, "_API_URL", f"http://127.0.0.1:{state.port}/{{host}}/ga4gh/drs/v1"
    )
    monkeypatch.setenv(DRS_ENABLED_ENV, "true")
    monkeypatch.delenv(DRS_ALLOWED_HOSTS_ENV, raising=False)
    monkeypatch.delenv(DRS_OBJECT_STORES_ENV, raising=False)
    monkeypatch.delenv(DRS_BEARER_TOKEN_ENV, raising=False)
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def pvc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The task volume as TIF sees it."""
    path = tmp_path / "pvc"
    path.mkdir()
    monkeypatch.setattr(filer_strategy, "FILER_PVC_PATH", str(path))
    return path


def stage(uri: str, path: str = "/in/genome.fa") -> None:
    asyncio.run(Tif("task", [TesInput(url=uri, path=path)]).file())


def test_access_id_is_followed_and_its_headers_go_with_the_data(
    drs: Drs, pvc: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DRS_BEARER_TOKEN_ENV, TOKEN)
    drs.objects["obj1"] = {
        "id": "obj1",
        "access_methods": [{"type": "https", "access_id": "a1"}],
    }
    drs.access["obj1/a1"] = {"url": drs.data_url, "headers": ["X-Signed: abc123"]}
    stage(f"drs://{HOST}/obj1")
    assert (pvc / "in" / "genome.fa").read_bytes() == DATA
    lookup, access, data = drs.seen
    assert lookup.path.endswith("/objects/obj1")
    assert access.path.endswith("/objects/obj1/access/a1")
    assert lookup.headers["Authorization"] == f"Bearer {TOKEN}"
    assert access.headers["Authorization"] == f"Bearer {TOKEN}"
    assert data.headers["X-Signed"] == "abc123"
    assert "Authorization" not in data.headers


def test_access_headers_do_not_follow_a_redirect_to_another_host(
    drs: Drs, pvc: Path
) -> None:
    drs.objects["o"] = {"access_methods": [{"type": "https", "access_id": "a"}]}
    drs.access["o/a"] = {
        "url": f"http://127.0.0.1:{drs.port}/elsewhere",
        "headers": ["Authorization: Bearer signed-for-the-first-host"],
    }
    stage(f"drs://{HOST}/o")
    assert (pvc / "in" / "genome.fa").read_bytes() == DATA
    first, final = drs.seen[-2:]
    assert first.headers["Authorization"] == "Bearer signed-for-the-first-host"
    assert "Authorization" not in final.headers


def test_https_is_preferred_over_an_object_store(
    drs: Drs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DRS_OBJECT_STORES_ENV, "s3")
    drs.objects["o"] = {
        "access_methods": [
            {"type": "s3", "access_url": {"url": "s3://bucket/key"}},
            {"type": "https", "access_url": {"url": "https://data.example.org/o"}},
        ]
    }
    assert resolve(f"drs://{HOST}/o") == ("https://data.example.org/o", {})


def test_object_store_is_used_only_when_enabled(
    drs: Drs, monkeypatch: pytest.MonkeyPatch
) -> None:
    drs.objects["o"] = {
        "access_methods": [{"type": "s3", "access_url": {"url": "s3://bucket/key"}}]
    }
    with pytest.raises(DrsError, match=r"no access method .*offered: s3"):
        resolve(f"drs://{HOST}/o")
    monkeypatch.setenv(DRS_OBJECT_STORES_ENV, "s3,gs")
    assert resolve(f"drs://{HOST}/o") == ("s3://bucket/key", {})


def test_access_url_with_headers_is_not_used_for_an_object_store(
    drs: Drs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DRS_OBJECT_STORES_ENV, "gs")
    drs.objects["o"] = {
        "access_methods": [
            {
                "type": "gs",
                "access_url": {"url": "gs://b/k", "headers": ["Authorization: x"]},
            }
        ]
    }
    with pytest.raises(DrsError, match="no access method"):
        resolve(f"drs://{HOST}/o")


def test_bundle_is_refused(drs: Drs) -> None:
    drs.objects["b"] = {"contents": [{"name": "x", "id": "x"}]}
    with pytest.raises(DrsError, match="bundle"):
        resolve(f"drs://{HOST}/b")


def test_missing_object_fails_with_a_clear_cause(drs: Drs, pvc: Path) -> None:
    with pytest.raises(DrsError, match=r"no object .* \(404\)"):
        stage(f"drs://{HOST}/nope")
    assert not list((pvc / "in").iterdir())


def test_compact_identifier_is_refused(drs: Drs) -> None:
    uri = "drs://dg.4503:8f5a4c39"
    assert not factory.can_input(uri)
    with pytest.raises(ValueError, match="compact-identifier"):
        build_taskpod_job(_task(uri), _config())
    with pytest.raises(DrsError, match="compact-identifier"):
        resolve(uri)


def test_allowed_hosts_limit_the_hosts(
    drs: Drs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DRS_ALLOWED_HOSTS_ENV, "drs.example.org, other.org")
    assert factory.can_input(f"drs://{HOST}/o")
    assert factory.can_input("drs://DRS.example.org/o")
    assert not factory.can_input("drs://evil.example.com/o")
    with pytest.raises(ValueError, match="doesn't allow"):
        build_taskpod_job(_task("drs://evil.example.com/o"), _config())


def test_drs_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DRS_ENABLED_ENV, raising=False)
    assert "drs" not in factory.supported_input_schemes()
    assert not factory.can_input(f"drs://{HOST}/o")
    with pytest.raises(ValueError, match="DRS inputs turned off"):
        build_taskpod_job(_task(f"drs://{HOST}/o"), _config())


def test_drs_is_listed_for_inputs_only_when_on(drs: Drs) -> None:
    assert "drs" in factory.supported_input_schemes()
    assert "drs" not in factory.supported_output_schemes()
    assert not factory.can_output(f"drs://{HOST}/o")


def test_drs_directory_input_is_refused(drs: Drs) -> None:
    task = _task(f"drs://{HOST}/o", kind=TesFileType.DIRECTORY)
    with pytest.raises(ValueError, match="DIRECTORY with a drs:// url"):
        build_taskpod_job(task, _config())


def test_token_reaches_tif_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    monkeypatch.setenv(DRS_ENABLED_ENV, "true")
    monkeypatch.setenv(DRS_ALLOWED_HOSTS_ENV, HOST)
    monkeypatch.setenv("POIESIS_TASKPOD_DRS_SECRET", "poiesis-drs")
    monkeypatch.setenv("POIESIS_S3_ENABLED", "true")
    config = Settings().runtime_config()
    assert config.drs_secret == "poiesis-drs"
    _pvc, job = build_taskpod_job(_task(f"drs://{HOST}/o"), config)
    spec = job.spec.template.spec
    for container in [*spec.init_containers, *spec.containers]:
        env = {e.name: e for e in container.env or []}
        if container.name == "tif":
            ref = env[DRS_BEARER_TOKEN_ENV].value_from.secret_key_ref
            assert (ref.name, ref.key) == ("poiesis-drs", DRS_BEARER_TOKEN_ENV)
            assert env[DRS_ALLOWED_HOSTS_ENV].value == HOST
            assert env[DRS_OBJECT_STORES_ENV].value == "s3"
        else:
            assert DRS_BEARER_TOKEN_ENV not in env, container.name
            assert DRS_ENABLED_ENV not in env, container.name


def test_settings_ignore_the_secret_while_drs_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    monkeypatch.delenv(DRS_ENABLED_ENV, raising=False)
    monkeypatch.setenv("POIESIS_TASKPOD_DRS_SECRET", "poiesis-drs")
    config = Settings().runtime_config()
    assert not config.drs_enabled
    assert config.drs_secret is None


def _config() -> RuntimeConfig:
    return RuntimeConfig(taskpod_namespace="po", poiesis_image="img")


def _task(url: str, kind: TesFileType = TesFileType.FILE) -> TesTask:
    return TesTask(
        id="11111111-1111-1111-1111-111111111111",
        executors=[TesExecutor(image="alpine", command=["true"])],
        inputs=[TesInput(url=url, path="/in/x", type=kind)],
    )


def test_token_cannot_be_set_through_extra_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """extraEnv would put the token on trec, tof and ack too."""
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    monkeypatch.setenv(
        "POIESIS_TASKPOD_EXTRA_ENV", json.dumps([{"name": DRS_BEARER_TOKEN_ENV}])
    )
    with pytest.raises(ValueError, match="collides"):
        Settings()
