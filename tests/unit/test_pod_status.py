"""A failed TaskPod maps to a failed task, whatever completed before it.

On a Failed Pod, trec, a filer or an earlier executor has usually exited 0
with reason ``Completed``. Taking that reason as the Pod's would record the
task as ``COMPLETE``.
"""

from __future__ import annotations

from typing import Any

import pytest

from poiesis.api.tes.models import TesState
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
        (status("exec-1", 137, "OOMKilled"), (TesState.SYSTEM_ERROR, "OOMKilled")),
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
