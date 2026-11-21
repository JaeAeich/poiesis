"""`reconcile.decide`: one task's inputs → the actions tctl applies (#161).

Plain data in, frozen actions out: no fakes, no clock. Each row of `CASES`
names a rule, builds the inputs and states the actions expected. The same
rows are the decision table in the pull request that introduced `decide`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from poiesis.api.tes.models import TesState
from poiesis.core.reconcile import (
    Action,
    DeleteJob,
    TaskView,
    Timeouts,
    WriteTerminal,
    decide,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
TASK = "00000000-0000-4000-8000-000000000001"
SCHEDULER = "0/3 nodes are available: 3 Insufficient cpu."
ORPHAN = WriteTerminal(
    TesState.SYSTEM_ERROR,
    "Pod disappeared before reaching terminal phase",
    ("pod disappeared before reaching terminal phase",),
    "orphan",
)


def ago(seconds: float) -> datetime:
    return NOW - timedelta(seconds=seconds)


def job(
    age: float = 60, *conditions: dict[str, Any], deadline: int | None = 3600
) -> dict[str, Any]:
    """A task Job created `age` seconds before `NOW`."""
    spec = {} if deadline is None else {"active_deadline_seconds": deadline}
    return {
        "metadata": {"name": f"task-{TASK}", "creation_timestamp": ago(age)},
        "spec": spec,
        "status": {"conditions": list(conditions)},
    }


def condition(kind: str, reason: str | None = None, message: str | None = None) -> dict:
    return {"type": kind, "status": "True", "reason": reason, "message": message}


DEADLINE = condition("Failed", "DeadlineExceeded", "Job was active longer")
DEADLINE_TARGET = condition("FailureTarget", "DeadlineExceeded", "Job was active")
BACKOFF = condition("Failed", "BackoffLimitExceeded", "Job has reached the limit")


def deleting(obj: dict[str, Any]) -> dict[str, Any]:
    obj["metadata"]["deletion_timestamp"] = NOW
    return obj


def pod(phase: str, name: str = "abcde", **status: Any) -> dict[str, Any]:
    return {
        "metadata": {"name": f"task-{TASK}-{name}", "namespace": "tasks"},
        "status": {"phase": phase, **status},
    }


def terminated(name: str, exit_code: int, reason: str, **extra: Any) -> dict:
    return {
        "name": name,
        "state": {"terminated": {"exit_code": exit_code, "reason": reason, **extra}},
    }


def finished(phase: str, *containers: dict[str, Any], **status: Any) -> dict:
    return pod(
        phase,
        init_container_statuses=[terminated("trec", 0, "Completed"), *containers],
        **status,
    )


def scheduled(age: float, **metadata: Any) -> dict[str, Any]:
    """Pending on a node for `age` seconds, its image not pulled."""
    stuck = pod(
        "Pending",
        start_time=ago(age),
        init_container_statuses=[
            {"name": "exec-0", "state": {"waiting": {"reason": "ErrImagePull"}}}
        ],
    )
    stuck["metadata"] |= metadata
    return stuck


def unscheduled(age: float | None, **metadata: Any) -> dict[str, Any]:
    """Pending, not placed by the scheduler, created `age` seconds ago."""
    waiting = pod(
        "Pending",
        conditions=[
            {
                "type": "PodScheduled",
                "status": "False",
                "reason": "Unschedulable",
                "message": SCHEDULER,
            }
        ],
    )
    if age is not None:
        waiting["metadata"]["creation_timestamp"] = ago(age)
    waiting["metadata"] |= metadata
    return waiting


SUCCEEDED = finished(
    "Succeeded",
    terminated("exec-0", 0, "Completed"),
    container_statuses=[terminated("ack", 0, "Completed")],
)
FAILED = finished("Failed", terminated("exec-0", 1, "Error"))
OOM = finished("Failed", terminated("exec-0", 137, "OOMKilled"))
FILER = finished(
    "Failed", terminated("tif", 1, "Error", message="GET https://host/a failed: 503")
)
EVICTED = pod("Failed", reason="Evicted")
KILLED = deleting(
    pod("Running", init_container_statuses=[terminated("exec-0", 137, "Error")])
)
STUCK = scheduled(400)
UNPLACED = unscheduled(700)
SECOND_FAILED = finished("Failed", terminated("exec-0", 1, "Error"))
SECOND_FAILED["metadata"]["name"] = f"task-{TASK}-fghij"


def write(
    state: TesState,
    reason: str | None,
    *logs: str,
    source: str,
    pod: dict[str, Any] | None = None,
) -> WriteTerminal:
    return WriteTerminal(state, reason, logs, source, pod)


@dataclass(frozen=True)
class Case:
    """One row: the inputs `decide` gets and the actions it returns."""

    rule: str
    expected: list[Action]
    job: dict[str, Any] | None = None
    pods: list[dict[str, Any]] = field(default_factory=list)
    canceling: bool = False
    seen_for: float | None = 0
    unschedulable: float | None = None


CASES = [
    # The orphan check: neither a Pod nor a Job that accounts for the task.
    Case("task just seen, nothing in Kubernetes", []),
    Case("seen 29.9 s, nothing in Kubernetes", [], seen_for=29.9),
    Case(
        "seen 30 s, nothing in Kubernetes: orphan",
        [ORPHAN, DeleteJob(retry=False)],
        seen_for=30,
    ),
    Case("not non-terminal in the DB, nothing in Kubernetes", [], seen_for=None),
    Case(
        "CANCELING, seen 30 s, nothing in Kubernetes: orphan (stored as CANCELED)",
        [ORPHAN, DeleteJob(retry=False)],
        canceling=True,
        seen_for=30,
    ),
    Case(
        "Job complete, no Pod, seen 30 s: orphan",
        [ORPHAN, DeleteJob(retry=False)],
        job=job(60, condition("Complete")),
        seen_for=30,
    ),
    Case("Job complete, no Pod, just seen", [], job=job(60, condition("Complete"))),
    Case("Job being deleted, no Pod, just seen", [], job=deleting(job())),
    Case(
        "Job being deleted, no Pod, seen 30 s: orphan",
        [ORPHAN, DeleteJob(retry=False)],
        job=deleting(job()),
        seen_for=30,
    ),
    Case(
        "Running Pod, seen 30 s: not an orphan",
        [],
        job=job(),
        pods=[pod("Running")],
        seen_for=30,
    ),
    # CANCELING.
    Case(
        "CANCELING, live Job, Running Pod: delete the Job",
        [DeleteJob(retry=True)],
        job=job(),
        pods=[pod("Running")],
        canceling=True,
    ),
    Case(
        "CANCELING, live Job, no Pod: delete the Job",
        [DeleteJob(retry=True)],
        job=job(),
        canceling=True,
    ),
    Case(
        "CANCELING, Job being deleted: no second delete",
        [],
        job=deleting(job()),
        canceling=True,
    ),
    Case(
        "CANCELING, live Job, Pod past pending timeout: delete, write, delete",
        [
            DeleteJob(retry=True),
            write(
                TesState.SYSTEM_ERROR,
                "ErrImagePull",
                "pending timeout: ErrImagePull",
                source="pending-timeout",
                pod=STUCK,
            ),
            DeleteJob(retry=False),
        ],
        job=job(400),
        pods=[STUCK],
        canceling=True,
    ),
    # A finished Pod.
    Case("live Job, Running Pod", [], job=job(), pods=[pod("Running")]),
    Case(
        "Succeeded Pod: COMPLETE, no system logs",
        [write(TesState.COMPLETE, None, source="pod-terminal", pod=SUCCEEDED)],
        job=job(),
        pods=[SUCCEEDED],
    ),
    Case(
        "Failed Pod, executor exit 1: EXECUTOR_ERROR",
        [
            write(
                TesState.EXECUTOR_ERROR,
                "Error",
                "container exec-0 exited with code 1",
                source="pod-terminal",
                pod=FAILED,
            )
        ],
        job=job(),
        pods=[FAILED],
    ),
    Case(
        "Failed Pod, executor OOMKilled: SYSTEM_ERROR",
        [
            write(
                TesState.SYSTEM_ERROR,
                "OOMKilled",
                "container exec-0 OOMKilled",
                source="pod-terminal",
                pod=OOM,
            )
        ],
        job=job(),
        pods=[OOM],
    ),
    Case(
        "Failed Pod, filer said why: SYSTEM_ERROR with its cause",
        [
            write(
                TesState.SYSTEM_ERROR,
                "FilerError",
                "container tif exited with code 1: GET https://host/a failed: 503",
                source="pod-terminal",
                pod=FILER,
            )
        ],
        job=job(),
        pods=[FILER],
    ),
    Case(
        "Failed Pod, evicted: SYSTEM_ERROR",
        [
            write(
                TesState.SYSTEM_ERROR,
                "Evicted",
                "task ended in SYSTEM_ERROR",
                source="pod-terminal",
                pod=EVICTED,
            )
        ],
        job=job(),
        pods=[EVICTED],
    ),
    Case(
        "finished Pod without a Job",
        [
            write(
                TesState.EXECUTOR_ERROR,
                "Error",
                "container exec-0 exited with code 1",
                source="pod-terminal",
                pod=FAILED,
            )
        ],
        pods=[FAILED],
    ),
    Case(
        "finished Pod of a task not non-terminal in the DB: proposed anyway",
        [write(TesState.COMPLETE, None, source="pod-terminal", pod=SUCCEEDED)],
        job=job(),
        pods=[SUCCEEDED],
        seen_for=None,
    ),
    # The Job's time limit.
    Case(
        "Job past its time limit, Failed Pod: the limit is the cause",
        [
            write(
                TesState.SYSTEM_ERROR,
                "DeadlineExceeded",
                "task exceeded its time limit of 3600 seconds",
                source="job-deadline",
                pod=FAILED,
            )
        ],
        job=job(3600, DEADLINE),
        pods=[FAILED],
    ),
    Case(
        "Job past its time limit (FailureTarget), Pod terminating",
        [
            write(
                TesState.SYSTEM_ERROR,
                "DeadlineExceeded",
                "task exceeded its time limit of 3600 seconds",
                source="job-deadline",
                pod=KILLED,
            )
        ],
        job=job(3600, DEADLINE_TARGET),
        pods=[KILLED],
    ),
    Case(
        "Job past its time limit, unscheduled Pod",
        [
            write(
                TesState.SYSTEM_ERROR,
                "DeadlineExceeded",
                "task exceeded its time limit of 3600 seconds",
                source="job-deadline",
                pod=UNPLACED,
            )
        ],
        job=job(3600, DEADLINE),
        pods=[UNPLACED],
    ),
    Case(
        "Job past its time limit, no Pod",
        [
            write(
                TesState.SYSTEM_ERROR,
                "DeadlineExceeded",
                "task exceeded its time limit of 3600 seconds",
                source="job-deadline",
            )
        ],
        job=job(3600, DEADLINE),
    ),
    Case(
        "Job past its time limit, no activeDeadlineSeconds, no Pod",
        [
            write(
                TesState.SYSTEM_ERROR,
                "DeadlineExceeded",
                "task exceeded its time limit",
                source="job-deadline",
            )
        ],
        job=job(3600, DEADLINE, deadline=None),
    ),
    Case(
        "Job past its time limit, being deleted, no Pod: left to the orphan check",
        [],
        job=deleting(job(3600, DEADLINE)),
    ),
    # A Job without a Pod.
    Case(
        "Job failed otherwise, no Pod: SYSTEM_ERROR with its reason",
        [
            write(
                TesState.SYSTEM_ERROR,
                "Job failed: BackoffLimitExceeded: Job has reached the limit",
                "job failed without a pod: BackoffLimitExceeded: "
                "Job has reached the limit",
                source="job-failed",
            )
        ],
        job=job(60, BACKOFF),
    ),
    Case(
        "Job failed without reason or message, no Pod",
        [
            write(
                TesState.SYSTEM_ERROR,
                "Job failed: Failed",
                "job failed without a pod: Failed",
                source="job-failed",
            )
        ],
        job=job(60, condition("Failed")),
    ),
    Case(
        "Job failed otherwise, Running Pod: left to the Pod",
        [],
        job=job(60, BACKOFF),
        pods=[pod("Running")],
    ),
    Case(
        "live Job, no Pod, timeout unset: waits",
        [],
        job=job(3000),
        seen_for=3000,
    ),
    Case(
        "live Job, no Pod for 500 s, timeout 600 s: waits",
        [],
        job=job(500),
        unschedulable=600,
    ),
    Case(
        "live Job, no Pod for 700 s, timeout 600 s: SYSTEM_ERROR, delete",
        [
            write(
                TesState.SYSTEM_ERROR,
                "Job created no Pod",
                "unschedulable timeout: the Job created no Pod "
                "(see the Job's events: quota, admission)",
                source="job-no-pod",
            ),
            DeleteJob(retry=False),
        ],
        job=job(700),
        unschedulable=600,
    ),
    # A Pending Pod.
    Case(
        "Pod on a node, Pending 300 s: waits",
        [],
        job=job(400),
        pods=[scheduled(300)],
    ),
    Case(
        "Pod on a node, Pending 400 s: SYSTEM_ERROR, delete",
        [
            write(
                TesState.SYSTEM_ERROR,
                "ErrImagePull",
                "pending timeout: ErrImagePull",
                source="pending-timeout",
                pod=STUCK,
            ),
            DeleteJob(retry=False),
        ],
        job=job(400),
        pods=[STUCK],
    ),
    Case(
        "Pod on a node, Pending 400 s, no metadata.namespace: no delete",
        [
            write(
                TesState.SYSTEM_ERROR,
                "ErrImagePull",
                "pending timeout: ErrImagePull",
                source="pending-timeout",
                pod=scheduled(400, namespace=None),
            ),
        ],
        job=job(400),
        pods=[scheduled(400, namespace=None)],
    ),
    Case(
        "Pod not placed for 700 s, timeout unset: waits",
        [],
        job=job(700),
        pods=[UNPLACED],
    ),
    Case(
        "Pod not placed for 280 s, timeout 600 s: waits",
        [],
        job=job(280),
        pods=[unscheduled(280)],
        unschedulable=600,
    ),
    Case(
        "Pod not placed for 700 s, timeout 600 s: SYSTEM_ERROR, delete",
        [
            write(
                TesState.SYSTEM_ERROR,
                "Insufficient CPU",
                "unschedulable timeout: Insufficient CPU",
                f"scheduler: {SCHEDULER}",
                source="unschedulable-timeout",
                pod=UNPLACED,
            ),
            DeleteJob(retry=False),
        ],
        job=job(700),
        pods=[UNPLACED],
        unschedulable=600,
    ),
    Case(
        "Pod not placed, camelCase creationTimestamp string, timeout 600 s",
        [
            write(
                TesState.SYSTEM_ERROR,
                "Insufficient CPU",
                "unschedulable timeout: Insufficient CPU",
                f"scheduler: {SCHEDULER}",
                source="unschedulable-timeout",
                pod=unscheduled(None, creationTimestamp=ago(700).isoformat()),
            ),
            DeleteJob(retry=False),
        ],
        pods=[unscheduled(None, creationTimestamp=ago(700).isoformat())],
        unschedulable=600,
    ),
    Case(
        "Pod on a node 100 s, created 700 s ago, timeout 600 s: start time wins",
        [],
        pods=[scheduled(100, creation_timestamp=ago(700))],
        unschedulable=600,
    ),
    Case(
        "Pending Pod without any timestamp, timeout 600 s: waits",
        [],
        pods=[pod("Pending")],
        unschedulable=600,
    ),
    # Several Pods of one task: each is decided in turn.
    Case(
        "Running Pod, then a Failed one",
        [
            write(
                TesState.EXECUTOR_ERROR,
                "Error",
                "container exec-0 exited with code 1",
                source="pod-terminal",
                pod=SECOND_FAILED,
            )
        ],
        job=job(),
        pods=[pod("Running"), SECOND_FAILED],
    ),
    Case(
        "Pod past pending timeout, then a Failed one: both proposed",
        [
            write(
                TesState.SYSTEM_ERROR,
                "ErrImagePull",
                "pending timeout: ErrImagePull",
                source="pending-timeout",
                pod=STUCK,
            ),
            DeleteJob(retry=False),
            write(
                TesState.EXECUTOR_ERROR,
                "Error",
                "container exec-0 exited with code 1",
                source="pod-terminal",
                pod=SECOND_FAILED,
            ),
        ],
        job=job(),
        pods=[STUCK, SECOND_FAILED],
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[c.rule for c in CASES])
def test_decide(case: Case) -> None:
    task = TaskView(TASK, canceling=case.canceling, seen_for=case.seen_for)
    timeouts = Timeouts(pending=300, unschedulable=case.unschedulable, orphan_grace=30)
    assert decide(task, case.job, case.pods, NOW, timeouts) == case.expected


def test_rules_are_unique() -> None:
    assert len({c.rule for c in CASES}) == len(CASES)


def test_naive_start_time_is_utc() -> None:
    """A start time without a zone, as some clients give it, is UTC."""
    stuck = scheduled(400)
    stuck["status"]["start_time"] = ago(400).replace(tzinfo=None).isoformat()
    timeouts = Timeouts(pending=300, unschedulable=None, orphan_grace=30)
    actions = decide(TaskView(TASK), None, [stuck], NOW, timeouts)
    assert [type(a) for a in actions] == [WriteTerminal, DeleteJob]


def test_actions_are_frozen() -> None:
    action = DeleteJob(retry=True)
    with pytest.raises(AttributeError):
        action.retry = False  # ty: ignore
