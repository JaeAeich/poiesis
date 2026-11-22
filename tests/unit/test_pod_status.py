"""A failed TaskPod maps to a failed task, whatever completed before it.

On a Failed Pod, trec, a filer or an earlier executor has usually exited 0
with reason ``Completed``. Taking that reason as the Pod's would record the
task as ``COMPLETE``.
"""

from __future__ import annotations

from typing import Any

import pytest

from poiesis.api.tes.models import TesState
from poiesis.core import tctl
from poiesis.core.pod_status import extract_terminal_reason, pod_terminated_terminal


def status(name: str, exit_code: int, reason: str) -> dict[str, Any]:
    """A container status in `state.terminated`."""
    return {
        "name": name,
        "state": {"terminated": {"exit_code": exit_code, "reason": reason}},
    }


@pytest.mark.parametrize(
    ("failed", "expected"),
    [
        (status("exec-1", 1, "Error"), (TesState.EXECUTOR_ERROR, "Error")),
        (status("exec-1", 128, "StartError"), (TesState.EXECUTOR_ERROR, "StartError")),
        (
            status("exec-1", 137, "OOMKilled"),
            (TesState.EXECUTOR_ERROR, "OOMKilled"),
        ),
    ],
    ids=["error", "start-error", "oom"],
)
def test_completed_containers_dont_hide_a_failure(
    failed: dict[str, Any], expected: tuple[TesState, str]
) -> None:
    """The failing container's reason wins over earlier ones that exited 0."""
    pod = {
        "status": {
            "phase": "Failed",
            "init_container_statuses": [
                status("trec", 0, "Completed"),
                status("tif", 0, "Completed"),
                status("exec-0", 0, "Completed"),
                failed,
            ],
            "container_statuses": [status("ack", 0, "Completed")],
        }
    }

    assert pod_terminated_terminal(extract_terminal_reason(pod)) == expected


def test_failed_pod_without_a_reason_is_an_error() -> None:
    """A Failed Pod whose containers all exited 0 is still not COMPLETE."""
    pod = {
        "status": {
            "phase": "Failed",
            "init_container_statuses": [status("trec", 0, "Completed")],
        }
    }

    assert pod_terminated_terminal(extract_terminal_reason(pod)) == (
        TesState.EXECUTOR_ERROR,
        "Error",
    )


def failed_pod(failed: dict[str, Any]) -> dict[str, Any]:
    """A Failed Pod in which `failed` is the container that failed."""
    return {
        "status": {
            "phase": "Failed",
            "initContainerStatuses": [
                status("trec", 0, "Completed"),
                status("exec-0", 0, "Completed"),
                failed,
            ],
        }
    }


def with_message(
    container: dict[str, Any], message: str, *, camel_case: bool = False
) -> dict[str, Any]:
    """`container` with `message` as its termination message."""
    terminated = container["state"]["terminated"]
    terminated["message"] = message
    if camel_case:
        terminated["exitCode"] = terminated.pop("exit_code")
    return container


CAUSE = "input /in/reads.fq: HTTPError: GET https://host.example/reads.fq returned 403"
MISSING = "poiesis-user-error: output /out.txt was not produced by the executors"


@pytest.mark.parametrize("name", ["tif", "tof"])
@pytest.mark.parametrize("camel_case", [False, True], ids=["snake", "camel"])
def test_filer_failure_is_a_system_error_with_its_cause(
    name: str, camel_case: bool
) -> None:
    """Staging failed, not an executor; the system log says why."""
    container = with_message(status(name, 1, "Error"), CAUSE, camel_case=camel_case)
    pod = failed_pod(container)

    state, reason = pod_terminated_terminal(extract_terminal_reason(pod))

    assert (state, reason) == (TesState.SYSTEM_ERROR, "FilerError")
    assert tctl._terminal_system_logs(pod, state) == [
        f"container {name} exited with code 1: {CAUSE}"
    ]


@pytest.mark.parametrize("name", ["tif", "tof"])
def test_filer_failure_without_a_cause_is_a_system_error(name: str) -> None:
    """A filer killed before it could say why still isn't the executor."""
    pod = failed_pod(status(name, 137, "Error"))

    state, reason = pod_terminated_terminal(extract_terminal_reason(pod))

    assert (state, reason) == (TesState.SYSTEM_ERROR, "FilerError")
    assert tctl._terminal_system_logs(pod, state) == [
        f"container {name} exited with code 137"
    ]


def test_filer_start_failure_is_a_system_error() -> None:
    """A filer that can't start is the deployment's failure."""
    pod = failed_pod(status("tif", 128, "StartError"))

    assert pod_terminated_terminal(extract_terminal_reason(pod)) == (
        TesState.SYSTEM_ERROR,
        "FilerError",
    )


def test_oom_killed_filer_is_a_system_error() -> None:
    """A filer over its own memory limit is the system's fault, not the task's."""
    pod = failed_pod(status("tif", 137, "OOMKilled"))

    state, reason = pod_terminated_terminal(extract_terminal_reason(pod))

    assert (state, reason) == (TesState.SYSTEM_ERROR, "SystemOOMKilled")
    assert tctl._terminal_system_logs(pod, state) == ["container tif OOMKilled"]


def test_output_the_executors_did_not_produce_is_an_executor_error() -> None:
    """tof marks that failure as the user's; the log names the output."""
    pod = failed_pod(with_message(status("tof", 1, "Error"), MISSING))

    state, reason = pod_terminated_terminal(extract_terminal_reason(pod))

    assert (state, reason) == (TesState.EXECUTOR_ERROR, "Error")
    assert tctl._terminal_system_logs(pod, state) == [
        "container tof exited with code 1: "
        "output /out.txt was not produced by the executors"
    ]


def test_executor_message_is_not_read_as_a_filer_cause() -> None:
    """Only tif and tof are trusted to say why they failed."""
    pod = failed_pod(with_message(status("exec-1", 1, "Error"), CAUSE))

    state, reason = pod_terminated_terminal(extract_terminal_reason(pod))

    assert (state, reason) == (TesState.EXECUTOR_ERROR, "Error")
    assert tctl._terminal_system_logs(pod, state) == [
        "container exec-1 exited with code 1"
    ]


def test_filer_cause_is_cut_to_one_line_without_a_query() -> None:
    """Whatever is in the message, the system log gets a short, safe line."""
    message = "first\nsecond https://host.example/x?sig=abcdef " + "y" * 4096
    pod = failed_pod(with_message(status("tif", 1, "Error"), message))

    (line,) = tctl._terminal_system_logs(pod, TesState.SYSTEM_ERROR)

    assert line.startswith(
        "container tif exited with code 1: "
        "first second https://host.example/x?<redacted> yyy"
    )
    assert len(line) < 1100  # noqa: PLR2004
