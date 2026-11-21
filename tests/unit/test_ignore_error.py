"""Executors with ``ignore_error=true`` don't stop the task (#98).

Executors are init containers, and a failing init container fails the Pod.
An ``ignore_error`` executor runs under ``/bin/sh``, which records the
command's exit code in the termination message and exits 0. trec and tctl
read the code back so the task logs show it.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

import pytest

from poiesis.api.tes.models import TesExecutor, TesState, TesTask
from poiesis.core import ignore_error, tctl
from poiesis.core.pod_status import (
    EventKind,
    TaskStateSnapshot,
    extract_terminal_reason,
    pod_terminated_terminal,
    translate,
)
from poiesis.core.taskpod import RuntimeConfig, build_taskpod_job

if TYPE_CHECKING:
    from pathlib import Path

CONFIG = RuntimeConfig(taskpod_namespace="tasks", poiesis_image="poiesis:test")


def executors(task: TesTask) -> dict[str, Any]:
    """Executor init containers of the task's Job, by name."""
    _, job = build_taskpod_job(task, CONFIG)
    return {
        c.name: c
        for c in job.spec.template.spec.init_containers
        if c.name.startswith("exec-")
    }


def make_task() -> TesTask:
    """Executor 0 exits 3 with ignore_error; executor 1 prints hello."""
    return TesTask(
        id="t1",
        executors=[
            TesExecutor(
                image="alpine:3.20", command=["sh", "-c", "exit 3"], ignore_error=True
            ),
            TesExecutor(image="alpine:3.20", command=["echo", "hello"]),
        ],
    )


def test_ignore_error_executor_runs_under_shell() -> None:
    """The command is passed to the wrapper as positional arguments."""
    container = executors(make_task())["exec-0"]

    assert container.command == [
        "/bin/sh",
        "-c",
        ignore_error.SCRIPT,
        "sh",
        "sh",
        "-c",
        "exit 3",
    ]
    assert container.args is None
    assert container.termination_message_path == "/dev/termination-log"
    assert container.termination_message_policy == "File"
    assert ignore_error.is_wrapped(container.command)


def test_other_executors_are_not_wrapped() -> None:
    """Without ignore_error the command runs as submitted, with no shell."""
    for flag in (None, False):
        task = make_task()
        task.executors[1].ignore_error = flag
        container = executors(task)["exec-1"]

        assert container.command == ["echo", "hello"]
        assert container.termination_message_path is None
        assert not ignore_error.is_wrapped(container.command)


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
@pytest.mark.parametrize(
    ("command", "exit_code", "stdout"),
    [
        (["sh", "-c", "exit 3"], 3, ""),
        (["true"], 0, ""),
        (
            ["printf", "%s|", "a b", "$HOME", "'q'", '"d"', "*"],
            0,
            "a b|$HOME|'q'|\"d\"|*|",
        ),
        (["no-such-command-98"], 127, ""),
    ],
    ids=["exit-3", "success", "argv-unchanged", "not-found"],
)
def test_wrapper_records_exit_code_and_exits_zero(
    tmp_path: Path, command: list[str], exit_code: int, stdout: str
) -> None:
    """The wrapper runs argv unchanged, records its exit code and exits 0."""
    message = tmp_path / "termination-log"
    wrapped = ignore_error.wrap_command(command)
    wrapped[2] = wrapped[2].replace(ignore_error.TERMINATION_MESSAGE_PATH, str(message))

    result = subprocess.run(  # noqa: S603
        wrapped, capture_output=True, text=True, check=False, cwd=tmp_path
    )

    assert result.returncode == 0
    assert result.stdout == stdout
    terminated = {"exitCode": 0, "message": message.read_text()}
    assert ignore_error.recorded_exit_code(terminated) == exit_code


@pytest.mark.parametrize(
    ("terminated", "expected"),
    [
        ({"exitCode": 0, "message": "poiesis-exit-code=3\n"}, 3),
        ({"exit_code": 0, "message": "poiesis-exit-code=42"}, 42),
        ({"exitCode": 0}, 0),
        ({"exitCode": 0, "message": "something else"}, 0),
        ({"exitCode": 0, "message": "x poiesis-exit-code=3"}, 0),
        ({"exitCode": 128, "message": "poiesis-exit-code=3"}, 128),
        ({}, None),
    ],
)
def test_recorded_exit_code(terminated: dict[str, Any], expected: int | None) -> None:
    """Only a container that exited 0 reports a code from its message."""
    assert ignore_error.recorded_exit_code(terminated) == expected


def terminated_status(name: str, **terminated: Any) -> dict[str, Any]:
    """A container status in `state.terminated`."""
    return {"name": name, "state": {"terminated": terminated}}


def test_trec_records_real_exit_code() -> None:
    """The translator reports the ignored executor's real exit code."""
    status = {
        "phase": "Succeeded",
        "initContainerStatuses": [
            terminated_status("tif", exitCode=0, message="poiesis-exit-code=9"),
            terminated_status(
                "exec-0", exitCode=0, reason="Completed", message="poiesis-exit-code=3"
            ),
            terminated_status("exec-1", exitCode=0, reason="Completed"),
        ],
    }

    events = translate(status, TaskStateSnapshot())

    codes = {
        e.executor_index: e.exit_code
        for e in events
        if e.kind is EventKind.EXECUTOR_FINISHED
    }
    assert codes == {0: 3, 1: 0}
    (tif,) = [e for e in events if e.kind is EventKind.TIF_FINISHED]
    assert tif.exit_code == 0
    (pod,) = [e for e in events if e.kind is EventKind.POD_TERMINATED]
    assert pod_terminated_terminal(pod.reason) == (TesState.COMPLETE, None)


def test_tctl_backfills_real_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tctl backfill writes the same exit code trec would."""
    written: dict[int, int] = {}

    async def append_executor_log(_conn: Any, _task_id: str, **row: Any) -> None:
        written[row["ordinal"]] = row["exit_code"]

    monkeypatch.setattr(tctl.state_db, "append_executor_log", append_executor_log)
    pod = {
        "status": {
            "init_container_statuses": [
                terminated_status(
                    "exec-0", exit_code=0, message="poiesis-exit-code=3\n"
                ),
                terminated_status("exec-1", exit_code=0, message=None),
            ]
        }
    }

    asyncio.run(tctl._backfill_executor_logs(None, "t1", pod))

    assert written == {0: 3, 1: 0}


def failed_pod(executor: dict[str, Any], *, wrapped: bool) -> dict[str, Any]:
    """A Failed TaskPod whose exec-0 terminated with `executor`."""
    command = ignore_error.wrap_command(["run"]) if wrapped else ["run"]
    return {
        "spec": {"init_containers": [{"name": "exec-0", "command": command}]},
        "status": {
            "phase": "Failed",
            "init_container_statuses": [
                terminated_status("trec", exit_code=0, reason="Completed"),
                terminated_status("tif", exit_code=0, reason="Completed"),
                {"name": "exec-0", "state": {"terminated": executor}},
            ],
        },
    }


START_ERROR = {
    "exit_code": 128,
    "reason": "StartError",
    "message": 'exec: "/bin/sh": stat /bin/sh: no such file or directory',
}


def test_missing_shell_is_an_executor_error() -> None:
    """An image without /bin/sh fails the task, and the log says why."""
    pod = failed_pod(START_ERROR, wrapped=True)

    reason = extract_terminal_reason(pod)
    state, _ = pod_terminated_terminal(reason)
    (line,) = tctl._terminal_system_logs(pod, state)

    assert (reason, state) == ("StartError", TesState.EXECUTOR_ERROR)
    assert "ignore_error" in line
    assert "/bin/sh" in line
    assert "no such file or directory" in line


@pytest.mark.parametrize(
    ("executor", "wrapped", "expected"),
    [
        (START_ERROR, False, "container exec-0 exited with code 128"),
        (
            {"exit_code": 137, "reason": "OOMKilled"},
            True,
            "container exec-0 OOMKilled",
        ),
        (
            {"exit_code": 137, "reason": "Error"},
            True,
            "container exec-0 exited with code 137",
        ),
    ],
    ids=["not-wrapped", "wrapped-oom", "wrapped-killed"],
)
def test_other_failures_keep_their_log(
    executor: dict[str, Any], *, wrapped: bool, expected: str
) -> None:
    """The /bin/sh hint is only for wrapped executors that failed to start."""
    pod = failed_pod(executor, wrapped=wrapped)

    assert tctl._terminal_system_logs(pod, TesState.EXECUTOR_ERROR) == [expected]
