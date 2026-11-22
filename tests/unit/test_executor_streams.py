"""Executor ``stdin``/``stdout``/``stderr`` paths and task volume directories.

Executors that set TES ``stdin``, ``stdout`` or ``stderr`` run under a
``/bin/sh`` wrapper that opens those files and ``exec``s the command;
executors that don't run as before, with no shell. trec reads the tails of
the output files from the task volume into the task logs. TIF creates the
task's directories that have no mount of their own (Sprocket's
``/mnt/task/usage`` volume under ``/mnt/task``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import stat
import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from poiesis.tes.models import (
    TesExecutor,
    TesFileType,
    TesInput,
    TesOutput,
    TesState,
    TesTask,
)
from poiesis.core import executor_logs, executor_shell, ignore_error, reconcile, tctl
from poiesis.core.constants import EXECUTOR_STREAMS_ENV
from poiesis.core.executor_logs import (
    MAX_OUTPUT_BYTES,
    Streams,
    decode_streams,
    read_executor_streams,
    read_volume_file,
    streams_from_pod,
)
from poiesis.core.pod_status import extract_terminal_reason, pod_terminated_terminal
from poiesis.core.filer.tif import make_task_dirs
from poiesis.core.taskpod import RuntimeConfig, build_taskpod_job

if TYPE_CHECKING:
    from pathlib import Path

CONFIG = RuntimeConfig(taskpod_namespace="tasks", poiesis_image="poiesis:test")
needs_sh = pytest.mark.skipif(shutil.which("sh") is None, reason="needs /bin/sh")


def init_containers(task: TesTask) -> dict[str, Any]:
    _, job = build_taskpod_job(task, CONFIG)
    return {c.name: c for c in job.spec.template.spec.init_containers}


def task_with(*executors: TesExecutor, **fields: Any) -> TesTask:
    return TesTask(id="t1", executors=list(executors), **fields)


def sprocket_task() -> TesTask:
    """The shape of a task Sprocket 0.34.1 sends (cgroup_usage on)."""
    return TesTask(
        id="t1",
        inputs=[
            TesInput(path="/mnt/task/command", content="echo hi"),
            TesInput(url="s3://b/names.txt", path="/mnt/task/inputs/4/names.txt"),
        ],
        outputs=[
            TesOutput(
                url="s3://b/work", path="/mnt/task/work", type=TesFileType.DIRECTORY
            ),
            TesOutput(url="s3://b/stdout", path="/mnt/task/stdout"),
            TesOutput(url="s3://b/stderr", path="/mnt/task/stderr"),
            TesOutput(
                url="s3://b/usage/", path="/mnt/task/usage", type=TesFileType.DIRECTORY
            ),
        ],
        volumes=["/mnt/task/usage"],
        executors=[
            TesExecutor(
                image="ubuntu:24.04",
                command=["/bin/sh", "-c", 'bash "$1"', "sprocket", "/mnt/task/command"],
                workdir="/mnt/task/work",
                stdout="/mnt/task/stdout",
                stderr="/mnt/task/stderr",
                ignore_error=True,
            )
        ],
    )


# --- manifest -------------------------------------------------------------


def test_executor_without_stream_fields_is_unchanged() -> None:
    """No shell, no stdin, no termination message, nothing for trec or TIF."""
    task = task_with(
        TesExecutor(image="gcr.io/distroless/static", command=["/app", "a b"]),
        volumes=["/data"],
    )
    containers = init_containers(task)

    assert set(containers) == {"trec", "exec-0"}
    executor = containers["exec-0"]
    assert executor.command == ["/app", "a b"]
    assert executor.args is None
    assert executor.stdin is False
    assert executor.termination_message_path is None
    trec_env = {e.name for e in containers["trec"].env}
    assert EXECUTOR_STREAMS_ENV not in trec_env


@pytest.mark.parametrize(
    ("fields", "features"),
    [
        ({"stdin": "/data/in"}, ("stdin",)),
        ({"stdout": "/data/out"}, ("stdout",)),
        ({"stderr": "/data/err"}, ("stderr",)),
        (
            {"stdin": "/data/in", "stdout": "/data/out", "stderr": "/data/err"},
            ("stdin", "stdout", "stderr"),
        ),
        (
            {"stdout": "/data/out", "ignore_error": True},
            ("stdout", "ignore_error"),
        ),
    ],
)
def test_executor_with_stream_fields_runs_under_shell(
    fields: dict[str, Any], features: tuple[str, ...]
) -> None:
    """The command follows the wrapper's own arguments, unchanged."""
    command = ["printf", "%s", "a b", "$HOME", "'q'"]
    task = task_with(TesExecutor(image="alpine", command=command, **fields))
    executor = init_containers(task)["exec-0"]

    assert executor.command[:2] == ["/bin/sh", "-c"]
    assert executor.command[3] == "sh"
    assert executor.command[-len(command) :] == command
    assert executor.stdin is False
    assert executor_shell.features(executor.command) == features
    if fields.get("ignore_error"):
        assert executor.termination_message_path == "/dev/termination-log"
        assert executor.termination_message_policy == "File"
    else:
        assert executor.termination_message_path is None
        assert executor.command[2].splitlines()[-1].startswith("exec ")


def test_ignore_error_alone_keeps_its_wrapper() -> None:
    """Executors with only ignore_error get the wrapper they had before."""
    task = task_with(TesExecutor(image="alpine", command=["false"], ignore_error=True))
    executor = init_containers(task)["exec-0"]
    assert executor.command == ignore_error.wrap_command(["false"])


def test_relative_stream_path_is_rejected() -> None:
    """TES requires absolute stdin/stdout/stderr paths."""
    task = task_with(TesExecutor(image="alpine", command=["true"], stdout="out.txt"))
    with pytest.raises(
        ValueError, match=r"executors\[0\]\.stdout must be an absolute path"
    ):
        build_taskpod_job(task, CONFIG)


def test_sprocket_task() -> None:
    """Nested directories go to TIF, the output files to trec."""
    containers = init_containers(sprocket_task())

    tif = containers["tif"]
    assert tif.command == [
        "poiesis", "tif", "run", "--task-id", "t1",
        "--mkdir", "/mnt/task/usage", "--mkdir", "/mnt/task/work",
    ]  # fmt: skip
    trec_env = {e.name: e.value for e in containers["trec"].env}
    assert json.loads(trec_env[EXECUTOR_STREAMS_ENV]) == {
        "0": {
            "stdout": "/transfer/mnt/task/stdout",
            "stderr": "/transfer/mnt/task/stderr",
        }
    }
    assert executor_shell.features(containers["exec-0"].command) == (
        "stdout",
        "stderr",
        "ignore_error",
    )


@pytest.mark.parametrize(
    ("fields", "expected_dirs"),
    [
        ({"volumes": ["/data"]}, None),
        ({"volumes": ["/data", "/scratch"]}, None),
        ({"volumes": ["/data", "/data/a/b"]}, ["/data/a/b"]),
        (
            {
                "volumes": ["/data"],
                "outputs": [
                    TesOutput(
                        url="s3://b/o", path="/data/out", type=TesFileType.DIRECTORY
                    ),
                    TesOutput(url="s3://b/f", path="/data/res/f.txt"),
                ],
            },
            ["/data/out", "/data/res"],
        ),
        ({"inputs": [TesInput(path="/data/in", content="x")]}, []),
        (
            {
                "inputs": [TesInput(path="/data/in", content="x")],
                "volumes": ["/data", "/data/tmp"],
            },
            ["/data/tmp"],
        ),
    ],
    ids=[
        "mount-point",
        "two-mount-points",
        "nested-volume",
        "nested-outputs",
        "inputs-only",
        "inputs-and-nested",
    ],
)
def test_tif_creates_dirs_only_when_needed(
    fields: dict[str, Any], expected_dirs: list[str] | None
) -> None:
    """TIF runs for inputs, or for directories without a mount of their own."""
    task = task_with(TesExecutor(image="alpine", command=["true"]), **fields)
    tif = init_containers(task).get("tif")
    if expected_dirs is None:
        assert tif is None
        return
    assert tif is not None
    dirs = tif.command[5:]
    assert dirs[0::2] == ["--mkdir"] * len(expected_dirs)
    assert dirs[1::2] == expected_dirs


def test_stream_files_off_the_volume_are_not_read() -> None:
    """A file outside the task's paths is gone with the container."""
    task = task_with(
        TesExecutor(
            image="alpine", command=["true"], stdout="/data/out", stderr="/tmp/err"
        ),
        volumes=["/data"],
    )
    trec_env = {e.name: e.value for e in init_containers(task)["trec"].env}
    streams = decode_streams(trec_env[EXECUTOR_STREAMS_ENV])
    assert streams == {
        0: Streams(frozenset({"stdout", "stderr"}), {"stdout": "/transfer/data/out"})
    }


# --- the wrapper, run ------------------------------------------------------


def run_wrapped(
    tmp_path: Path, command: list[str], **fields: Any
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the wrapper `wrap` builds, with the termination log in `tmp_path`."""
    wrapped = executor_shell.wrap(TesExecutor(image="x", command=command, **fields))
    assert wrapped is not None
    wrapped[2] = wrapped[2].replace(
        ignore_error.TERMINATION_MESSAGE_PATH, str(tmp_path / "termination-log")
    )
    result = subprocess.run(  # noqa: S603
        wrapped, capture_output=True, text=True, check=False, cwd=tmp_path
    )
    return result, wrapped


@needs_sh
def test_wrapper_writes_stdout_and_stderr(tmp_path: Path) -> None:
    """Each stream goes to its file; the parent directory is created."""
    out, err = tmp_path / "logs/a/out", tmp_path / "logs/b/err"
    result, _ = run_wrapped(
        tmp_path,
        ["sh", "-c", "echo to-out; echo to-err >&2; exit 3"],
        stdout=str(out),
        stderr=str(err),
    )
    assert result.returncode == 3  # noqa: PLR2004
    assert (result.stdout, result.stderr) == ("", "")
    assert out.read_text() == "to-out\n"
    assert err.read_text() == "to-err\n"


@needs_sh
def test_wrapper_feeds_stdin(tmp_path: Path) -> None:
    """stdin comes from its file; unset streams stay with the container."""
    (tmp_path / "in").write_text("from-file\n")
    result, _ = run_wrapped(tmp_path, ["cat"], stdin=str(tmp_path / "in"))
    assert result.returncode == 0
    assert result.stdout == "from-file\n"


@needs_sh
def test_wrapper_same_file_for_stdout_and_stderr(tmp_path: Path) -> None:
    """Both streams in one file, in order, neither overwriting the other."""
    log = tmp_path / "log"
    result, _ = run_wrapped(
        tmp_path,
        ["sh", "-c", "echo one; echo two >&2; echo three"],
        stdout=str(log),
        stderr=str(log),
    )
    assert result.returncode == 0
    assert log.read_text() == "one\ntwo\nthree\n"


@needs_sh
def test_wrapper_passes_argv_unchanged(tmp_path: Path) -> None:
    """Spaces, quotes, `$`, globs and newlines reach the command as given."""
    argv = ["a b", "$HOME", "'q'", '"d"', "*", "x\ny", "", "--", "-n", "\\"]
    out = tmp_path / "out"
    result, _ = run_wrapped(
        tmp_path, ["printf", "[%s]", *argv], stdout=str(out), stderr=str(out)
    )
    assert result.returncode == 0
    assert out.read_text() == "".join(f"[{a}]" for a in argv)


@needs_sh
def test_wrapper_execs_the_command(tmp_path: Path) -> None:
    """The command replaces the shell: same PID, so signals reach it."""
    out = tmp_path / "out"
    wrapped = executor_shell.wrap(
        TesExecutor(image="x", command=["sh", "-c", "echo $$"], stdout=str(out))
    )
    assert wrapped is not None
    process = subprocess.Popen(wrapped, cwd=tmp_path)  # noqa: S603
    assert process.wait() == 0
    assert out.read_text() == f"{process.pid}\n"


@needs_sh
@pytest.mark.parametrize("exit_code", [0, 3])
def test_wrapper_with_ignore_error(tmp_path: Path, exit_code: int) -> None:
    """One wrapper: the streams go to files, the exit code to the message."""
    out = tmp_path / "out"
    result, _ = run_wrapped(
        tmp_path,
        ["sh", "-c", f"echo hi; exit {exit_code}"],
        stdout=str(out),
        ignore_error=True,
    )
    assert result.returncode == 0
    assert out.read_text() == "hi\n"
    message = (tmp_path / "termination-log").read_text()
    assert ignore_error.recorded_exit_code({"exitCode": 0, "message": message}) == (
        exit_code
    )


@needs_sh
def test_wrapper_with_ignore_error_records_a_file_it_cannot_open(
    tmp_path: Path,
) -> None:
    """A stdin file that doesn't exist is the executor's error, not the Pod's."""
    result, _ = run_wrapped(
        tmp_path, ["cat"], stdin=str(tmp_path / "missing"), ignore_error=True
    )
    assert result.returncode == 0
    message = (tmp_path / "termination-log").read_text()
    assert ignore_error.recorded_exit_code({"exitCode": 0, "message": message}) != 0


@needs_sh
def test_wrapper_fails_when_it_cannot_open_a_file(tmp_path: Path) -> None:
    """Without ignore_error, the executor fails and the container log says why."""
    result, _ = run_wrapped(tmp_path, ["cat"], stdin=str(tmp_path / "missing"))
    assert result.returncode != 0
    assert "missing" in result.stderr


# --- missing shell ---------------------------------------------------------


def failed_pod(command: list[str], terminated: dict[str, Any]) -> dict[str, Any]:
    return {
        "spec": {"init_containers": [{"name": "exec-0", "command": command}]},
        "status": {
            "phase": "Failed",
            "init_container_statuses": [
                {"name": "exec-0", "state": {"terminated": terminated}}
            ],
        },
    }


START_ERROR = {
    "exit_code": 128,
    "reason": "StartError",
    "message": 'exec: "/bin/sh": stat /bin/sh: no such file or directory',
}


def test_missing_shell_names_the_stream_fields() -> None:
    """An image without /bin/sh: EXECUTOR_ERROR and a log line saying why."""
    command = executor_shell.wrap(
        TesExecutor(image="x", command=["/app"], stdout="/d/o", stderr="/d/e")
    )
    assert command is not None
    pod = failed_pod(command, START_ERROR)

    state, _ = pod_terminated_terminal(extract_terminal_reason(pod))
    (line,) = reconcile.terminal_system_logs(pod, state)

    assert state is TesState.EXECUTOR_ERROR
    assert "executor 0 sets stdout, stderr, which needs /bin/sh in its image" in line
    assert "no such file or directory" in line


def test_command_not_found_is_not_a_shell_problem() -> None:
    """A wrapper that execs exits 127 when the command is missing."""
    command = executor_shell.wrap(
        TesExecutor(image="x", command=["nope"], stdout="/d/o")
    )
    assert command is not None
    pod = failed_pod(command, {"exit_code": 127, "reason": "Error"})
    lines = reconcile.terminal_system_logs(pod, TesState.EXECUTOR_ERROR)
    assert lines == ["container exec-0 exited with code 127"]


def test_user_shell_command_is_not_mistaken_for_a_wrapper() -> None:
    """A submitted `/bin/sh -c` command is the user's, not a wrapper."""
    assert executor_shell.features(["/bin/sh", "-c", "echo hi", "sh"]) == ()
    assert executor_shell.features(["/app"]) == ()
    assert executor_shell.features(None) == ()


# --- task directories --------------------------------------------------------


def test_make_task_dirs_uses_the_volume_root_mode(tmp_path: Path) -> None:
    """New directories, parents included, get the root's mode; others stay."""
    root = tmp_path / "transfer"
    root.mkdir()
    root.chmod(0o777)
    (root / "mnt").mkdir(mode=0o700)
    (root / "mnt").chmod(0o700)

    make_task_dirs(["/mnt/task/usage", "/scratch"], root=str(root))

    def mode(path: Path) -> int:
        return stat.S_IMODE(path.stat().st_mode)

    assert mode(root / "mnt") == 0o700  # it existed: untouched
    assert mode(root / "mnt/task") == 0o777
    assert mode(root / "mnt/task/usage") == 0o777
    assert mode(root / "scratch") == 0o777


def test_make_task_dirs_skips_what_it_cannot_create(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A path below a file can't be created: a warning, and the rest goes on."""
    (tmp_path / "file").write_text("x")
    make_task_dirs(["/file/sub", "/ok"], root=str(tmp_path))
    assert "Could not create directory /file/sub" in caplog.text
    assert (tmp_path / "ok").is_dir()


# --- task logs --------------------------------------------------------------


class FakeLogResponse:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def stream(self, amt: int) -> Any:
        yield self.data

    def release_conn(self) -> None:
        pass


class FakeCoreV1:
    def __init__(self, log: bytes) -> None:
        self.log = log

    def read_namespaced_pod_log(self, **_: Any) -> FakeLogResponse:
        return FakeLogResponse(self.log)


def read_streams(
    monkeypatch: pytest.MonkeyPatch,
    log: bytes,
    streams: Streams | None,
    files: dict[str, str | None],
) -> tuple[str | None, str | None]:
    async def read_file(path: str) -> str | None:
        return files.get(path)

    monkeypatch.setattr(executor_logs, "read_volume_file", read_file)
    return asyncio.run(
        read_executor_streams(FakeCoreV1(log), "pod", "tasks", 0, streams)
    )


BOTH = {"stdout", "stderr"}


@pytest.mark.parametrize(
    ("redirected", "files", "expected"),
    [
        (set(), {}, ("log", None)),
        ({"stdout"}, {"stdout": "out"}, ("out-file", "log")),
        ({"stderr"}, {"stderr": "err"}, ("log", "err-file")),
        (BOTH, {"stdout": "out", "stderr": "err"}, ("out-file", "err-file")),
        (BOTH, {"stdout": "out", "stderr": "out"}, ("out-file", "log")),
        ({"stdout"}, {}, (None, "log")),
        (BOTH, {"stdout": "missing", "stderr": "err"}, ("log", "err-file")),
    ],
    ids=[
        "none",
        "stdout",
        "stderr",
        "both",
        "same-file",
        "off-volume",
        "file-missing",
    ],
)  # fmt: skip
def test_output_comes_from_files_and_log(
    monkeypatch: pytest.MonkeyPatch,
    redirected: set[str],
    files: dict[str, str],
    expected: tuple[str | None, str | None],
) -> None:
    """Files fill their streams; the container log fills the first one left."""
    contents = {"out": "out-file", "err": "err-file", "missing": None}
    streams = Streams(frozenset(redirected), files) if redirected else None
    assert read_streams(monkeypatch, b"log", streams, contents) == expected


def test_empty_log_fills_nothing_when_both_streams_are_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = Streams(frozenset({"stdout", "stderr"}), {"stdout": "o", "stderr": "o"})
    assert read_streams(monkeypatch, b"", streams, {"o": "both"}) == ("both", None)


def test_reads_the_end_of_a_volume_file(tmp_path: Path) -> None:
    """Only the last `MAX_OUTPUT_BYTES` are kept, as for container logs."""
    (tmp_path / "mnt").mkdir()
    (tmp_path / "mnt/out").write_bytes(b"x" * (2 * MAX_OUTPUT_BYTES) + b"end\n")
    text = asyncio.run(read_volume_file(str(tmp_path / "mnt/out"), str(tmp_path)))
    assert text is not None
    assert len(text) == MAX_OUTPUT_BYTES
    assert text.endswith("end\n")


@pytest.mark.parametrize("link", ["file", "dir"])
def test_volume_file_symlinks_are_not_followed(
    tmp_path: Path, link: str, caplog: pytest.LogCaptureFixture
) -> None:
    """An executor can't make trec read its own secrets into the task log."""
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "token").write_text("s3cr3t")
    root = tmp_path / "transfer"
    root.mkdir()
    if link == "file":
        (root / "out").symlink_to(secret / "token")
        path = root / "out"
    else:
        (root / "logs").symlink_to(secret)
        path = root / "logs/token"

    assert asyncio.run(read_volume_file(str(path), str(root))) is None
    assert "could not read executor output file" in caplog.text


def test_volume_file_must_be_a_regular_file_below_the_root(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "fifo")
    assert asyncio.run(read_volume_file(str(tmp_path / "fifo"), str(tmp_path))) is None
    outside = str(tmp_path.parent / "elsewhere")
    assert asyncio.run(read_volume_file(outside, str(tmp_path))) is None


def test_tctl_backfill_labels_the_container_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tctl can't read the files: the container log becomes the stdout."""
    rows: list[dict[str, Any]] = []

    async def append(_conn: Any, _task_id: str, **row: Any) -> None:
        rows.append(row)

    async def recorded(_conn: Any, _task_id: str) -> set[int]:
        return set()

    monkeypatch.setattr(tctl.state_db, "append_executor_log", append)
    monkeypatch.setattr(tctl.state_db, "recorded_executor_ordinals", recorded)
    _, job = build_taskpod_job(sprocket_task(), CONFIG)
    pod = job.spec.template.to_dict()
    pod["metadata"] = {"name": "pod-1", "namespace": "tasks"}
    pod["status"] = {
        "init_container_statuses": [
            {"name": "exec-0", "state": {"terminated": {"exit_code": 0}}}
        ]
    }
    assert streams_from_pod(pod)[0].files  # what trec reads

    _tctl_backfill(FakeCoreV1(b"oops\n"), pod)

    (row,) = rows
    assert (row["stdout"], row["stderr"]) == ("oops\n", None)


def _tctl_backfill(core_v1: Any, pod: dict[str, Any]) -> None:
    """Run tctl's executor log backfill of `pod`: read, then write the rows."""

    async def backfill() -> None:
        pool = SimpleNamespace(acquire=contextlib.nullcontext)
        rows = await tctl._read_executor_logs(pool, core_v1, "t1", pod)  # ty: ignore
        await tctl._write_executor_logs(None, "t1", rows)  # ty: ignore

    asyncio.run(backfill())
