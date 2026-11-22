"""A failing filer says why in its termination message, without secrets.

tif and tof write one line to the file Kubernetes reads the termination
message from; here that file is a temporary one.
"""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING

import pytest
import requests

from poiesis.api.tes.models import TesFileType, TesInput, TesOutput, TesState
from poiesis.cli import tif as tif_cli
from poiesis.cli import tof as tof_cli
from poiesis.core import filer_error, reconcile
from poiesis.core.pod_status import extract_terminal_reason, pod_terminated_terminal
from poiesis.core.services.filer.strategy import filer_strategy, http_filer
from poiesis.core.services.filer.tif import Tif
from poiesis.core.services.filer.tof import Tof

if TYPE_CHECKING:
    from pathlib import Path

SECRET = "0123456789abcdef"  # noqa: S105
URL = f"https://storage.example/bucket/object?X-Amz-Signature={SECRET}"


@pytest.fixture
def message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The file standing in for the container's termination message."""
    path = tmp_path / "termination-log"
    monkeypatch.setattr(filer_error, "TERMINATION_MESSAGE_PATH", str(path))
    return path


@pytest.fixture
def pvc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary directory standing in for the task's volume."""
    volume = tmp_path / "transfer"
    volume.mkdir()
    monkeypatch.setattr(filer_strategy, "FILER_PVC_PATH", str(volume))
    return volume


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Storage that answers every request 403, echoing the URL it was sent."""
    urls: list[str] = []

    def request(_: str, url: str, **__: object) -> requests.Response:
        urls.append(url)
        response = requests.Response()
        response.status_code = 403
        body = f"<Error>\n  <Code>AccessDenied</Code>\n  <Url>{url}</Url>\n</Error>"
        response.raw = Body(body.encode())
        return response

    monkeypatch.setattr(http_filer.requests, "request", request)
    return urls


class Body(io.BytesIO):
    """A response body read as urllib3's is."""

    def read(self, size: int | None = -1, **_: object) -> bytes:
        """Read up to `size` bytes; `decode_content` is accepted."""
        return super().read(size)


def failed_pod(name: str, message: str | None, reason: str = "Error") -> dict:
    """A Failed Pod whose container `name` exited 1 with `message`."""

    def status(container: str, exit_code: int, reason: str) -> dict:
        return {
            "name": container,
            "state": {"terminated": {"exit_code": exit_code, "reason": reason}},
        }

    failed = status(name, 1, reason)
    failed["state"]["terminated"]["message"] = message
    return {
        "status": {
            "phase": "Failed",
            "init_container_statuses": [status("trec", 0, "Completed"), failed],
        }
    }


def terminal(pod: dict) -> tuple[TesState, str | None, list[str]]:
    """The state, reason and system logs tctl records for `pod`."""
    state, reason = pod_terminated_terminal(extract_terminal_reason(pod))
    return state, reason, reconcile.terminal_system_logs(pod, state)


def run(filer: Tif | Tof) -> None:
    """Run `filer` as its command does, expecting it to fail."""
    with pytest.raises(SystemExit) as exit_info:
        asyncio.run(filer.execute())
    assert exit_info.value.code == 1


def test_sanitise_gives_one_line_without_secrets() -> None:
    """Query strings and URL credentials are cut; line breaks become spaces."""
    text = (
        "GET https://user:hunter2@host.example/a/b?sig=abc&x=1 failed\n"
        "\twith url: /a/b?sig=abc (Caused by 'x')\x00"
    )
    assert filer_error.sanitise(text) == (
        "GET https://<redacted>@host.example/a/b?<redacted> failed "
        "with url: /a/b?<redacted> (Caused by 'x')"
    )


def test_sanitise_leaves_a_glob_alone() -> None:
    """A `?` without a `=` after it isn't a query string."""
    assert filer_error.sanitise("output /out/a?.txt missing") == (
        "output /out/a?.txt missing"
    )


def test_sanitise_cuts_at_one_kibibyte() -> None:
    """The cut falls between characters, not inside one."""
    line = filer_error.sanitise("é" * 2000)
    assert len(line.encode()) == filer_error.MAX_BYTES
    assert set(line) == {"é"}


def test_write_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Outside a container the termination message can't be written."""
    missing = tmp_path / "missing" / "termination-log"
    monkeypatch.setattr(filer_error, "TERMINATION_MESSAGE_PATH", str(missing))
    filer_error.write("cause")
    assert not missing.exists()


def test_failed_download_reports_the_input_and_status(
    message: Path, pvc: Path, storage: list[str]
) -> None:
    """The cause names the input and the response, on one line, no query."""
    run(Tif("task", [TesInput(url=URL, path="/inputs/reads.fq")]))
    text = message.read_text()
    assert text == (
        "input /inputs/reads.fq: HTTPError: GET https://storage.example/bucket/object "
        "returned 403: <Error> <Code>AccessDenied</Code> "
        "<Url>https://storage.example/bucket/object?<redacted></Url> </Error>\n"
    )
    assert storage == [URL]
    assert SECRET not in text


def test_failed_upload_reports_the_output_and_status(
    message: Path, pvc: Path, storage: list[str]
) -> None:
    """A rejected upload is the system's failure, with its cause."""
    (pvc / "outputs").mkdir()
    (pvc / "outputs/out.bam").write_bytes(b"data")
    run(Tof("task", [TesOutput(url=URL, path="/outputs/out.bam")]))
    text = message.read_text()
    assert text.startswith(
        "output /outputs/out.bam: HTTPError: PUT https://storage.example/"
    )
    assert "returned 403" in text
    assert SECRET not in text
    state, reason, logs = terminal(failed_pod("tof", text))
    assert (state, reason) == (TesState.SYSTEM_ERROR, "FilerError")
    assert logs == [f"container tof exited with code 1: {text.strip()}"]


def test_long_cause_is_cut(message: Path, pvc: Path) -> None:
    """The termination message stays within a kibibyte."""
    inputs = [TesInput(url="ftp://host.example/" + "x" * 4096, path="/inputs/in")]
    run(Tif("task", inputs))
    assert len(message.read_bytes()) <= filer_error.MAX_BYTES + 1
    assert message.read_text().count("\n") == 1


@pytest.mark.parametrize("url", [URL, "s3://bucket/out.txt"])
def test_output_the_executors_did_not_produce_is_the_users_error(
    message: Path,
    pvc: Path,
    storage: list[str],
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    """The task ends in EXECUTOR_ERROR, with a log naming the output."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    run(Tof("task", [TesOutput(url=url, path="/outputs/missing.txt")]))
    text = message.read_text()
    state, reason, logs = terminal(failed_pod("tof", text))
    assert (state, reason) == (TesState.EXECUTOR_ERROR, "Error")
    assert logs == [
        "container tof exited with code 1: "
        "output /outputs/missing.txt was not produced by the executors"
    ]
    assert storage == []


def test_output_symlink_leaving_the_volume_is_the_users_error(
    message: Path, pvc: Path, storage: list[str], tmp_path: Path
) -> None:
    """The executors left the link, so the task ends in EXECUTOR_ERROR."""
    secret = tmp_path / "environ"
    secret.write_text("DATABASE_URL=postgres://secret")
    (pvc / "outputs").mkdir(parents=True, exist_ok=True)
    (pvc / "outputs" / "leak").symlink_to(secret)
    run(Tof("task", [TesOutput(url="https://example.org/up", path="/outputs/leak")]))
    state, reason, logs = terminal(failed_pod("tof", message.read_text()))
    assert (state, reason) == (TesState.EXECUTOR_ERROR, "Error")
    assert logs == [
        "container tof exited with code 1: "
        "output /outputs/leak is a symlink that points outside the task volume"
    ]
    assert storage == []


def test_directory_output_that_is_a_file_is_the_users_error(
    message: Path, pvc: Path
) -> None:
    """An output of the wrong type wasn't produced as declared either."""
    (pvc / "outputs").mkdir()
    (pvc / "outputs/out").write_bytes(b"data")
    output = TesOutput(url=URL, path="/outputs/out", type=TesFileType.DIRECTORY)
    run(Tof("task", [output]))
    state, _, logs = terminal(failed_pod("tof", message.read_text()))
    assert state is TesState.EXECUTOR_ERROR
    assert logs == [
        "container tof exited with code 1: "
        "output /outputs/out is declared a DIRECTORY but is not one"
    ]


def test_glob_that_matches_nothing_still_succeeds(message: Path, pvc: Path) -> None:
    """No output for a glob isn't a failure, so there is no cause."""
    asyncio.run(Tof("task", [TesOutput(url=URL, path="/outputs/*.vcf")]).execute())
    assert not message.exists()


@pytest.mark.parametrize("module", [tif_cli, tof_cli], ids=["tif", "tof"])
def test_unreachable_database_is_reported(
    message: Path, monkeypatch: pytest.MonkeyPatch, module
) -> None:
    """A filer that can't read its task says so, without the DSN's password."""

    async def connect(dsn: str) -> None:
        raise OSError(f"Connect call failed for {dsn}")

    monkeypatch.setattr(module.asyncpg, "connect", connect)
    dsn = "postgresql://poiesis:hunter2@db.example:5432/poiesis"
    with pytest.raises(OSError, match="Connect call failed"):
        asyncio.run(module._run("task-1", dsn))
    assert message.read_text() == (
        "reading the task from the database: OSError: Connect call failed for "
        "postgresql://<redacted>@db.example:5432/poiesis\n"
    )
