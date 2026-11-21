"""What one tctl reconcile pass does, over a matrix of tasks, Jobs and Pods.

Characterisation, not specification: each case runs `tctl._reconcile_once`
once against the fakes of `test_tctl_reconcile` and records every effect in
order (terminal writes, system logs, executor log backfills, Job deletes and
tctl's own log lines). The results are compared with
`golden/tctl/reconcile.json`, written when missing or when
`POIESIS_WRITE_GOLDEN` is set. A change to the golden file is a change to
tctl's behaviour.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from test_tctl_reconcile import T1, T2, World, deadline, job, pod, unscheduled

from poiesis.api.tes.models import TesState
from poiesis.core import tctl

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

GOLDEN = Path(__file__).parent / "golden" / "tctl" / "reconcile.json"

#: How the task looks to tctl: its DB state and how long tctl has seen it.
TASKS: dict[str, tuple[TesState, float | None]] = {
    "queued-just-seen": (TesState.QUEUED, None),
    "queued-past-grace": (TesState.QUEUED, 31),
    "canceling-just-seen": (TesState.CANCELING, None),
    "canceling-past-grace": (TesState.CANCELING, 31),
    "complete": (TesState.COMPLETE, None),
}


def _deleting_job() -> dict[str, Any]:
    deleting = job(T1)
    deleting["metadata"]["deletion_timestamp"] = datetime.now(UTC)
    return deleting


JOBS: dict[str, Callable[[], dict[str, Any] | None]] = {
    "none": lambda: None,
    "live-young": lambda: job(T1, age=60),
    "live-old": lambda: job(T1, age=700),
    "being-deleted": _deleting_job,
    "deadline-failed": lambda: job(T1, age=3600, conditions=deadline()),
    "deadline-failure-target": lambda: job(
        T1, age=3600, conditions=deadline("FailureTarget")
    ),
    "failed-other": lambda: job(
        T1,
        conditions=[
            {
                "type": "Failed",
                "status": "True",
                "reason": "BackoffLimitExceeded",
                "message": "Job has reached the specified backoff limit",
            }
        ],
    ),
    "complete": lambda: job(T1, conditions=[{"type": "Complete", "status": "True"}]),
}


def _terminated(name: str, exit_code: int, reason: str, **extra: Any) -> dict:
    return {
        "name": name,
        "state": {
            "terminated": {"exit_code": exit_code, "reason": reason, **extra},
        },
    }


def _scheduled(age: float) -> dict[str, Any]:
    """Pending on a node `age` seconds, its executor's image not pulled."""
    return pod(
        T1,
        "Pending",
        start_time=datetime.now(UTC) - timedelta(seconds=age),
        init_container_statuses=[
            {"name": "exec-0", "state": {"waiting": {"reason": "ErrImagePull"}}}
        ],
    )


def _finished(phase: str, *containers: dict[str, Any], **status: Any) -> dict:
    return pod(
        T1,
        phase,
        init_container_statuses=[
            _terminated("trec", 0, "Completed"),
            *containers,
        ],
        **status,
    )


def _terminating() -> dict[str, Any]:
    stopping = pod(
        T1, "Running", init_container_statuses=[_terminated("exec-0", 137, "Error")]
    )
    stopping["metadata"]["deletion_timestamp"] = datetime.now(UTC)
    return stopping


PODS: dict[str, Callable[[], dict[str, Any] | None]] = {
    "none": lambda: None,
    "pending-scheduled-young": lambda: _scheduled(100),
    "pending-scheduled-old": lambda: _scheduled(400),
    "pending-unscheduled-young": lambda: unscheduled(T1, age=280),
    "pending-unscheduled-old": lambda: unscheduled(T1, age=700),
    "running": lambda: pod(T1),
    "succeeded": lambda: _finished(
        "Succeeded",
        _terminated("exec-0", 0, "Completed"),
        container_statuses=[_terminated("ack", 0, "Completed")],
    ),
    "failed-executor": lambda: _finished("Failed", _terminated("exec-0", 1, "Error")),
    "failed-filer": lambda: _finished(
        "Failed",
        _terminated("tif", 1, "Error", message="GET https://host/a failed: 503"),
    ),
    "failed-oom": lambda: _finished("Failed", _terminated("exec-0", 137, "OOMKilled")),
    "failed-evicted": lambda: pod(T1, "Failed", reason="Evicted"),
    "terminating": _terminating,
}

UNSCHEDULABLE_TIMEOUTS: dict[str, float | None] = {"unset": None, "600": 600}


class Recorder(World):
    """`World`, recording every effect of a pass in order."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(monkeypatch)
        self.effects: list[list[Any]] = []

    async def write(
        self, conn: Any, task_id: str, proposed: TesState, reason: str | None = None
    ) -> Any:
        result = await super().write(conn, task_id, proposed, reason)
        self.effects.append(["write", task_id, proposed.value, reason, result.value])
        return result

    async def append_log(self, conn: Any, task_id: str, message: str) -> None:
        await super().append_log(conn, task_id, message)
        self.effects.append(["system_log", task_id, message])

    async def backfill(self, conn: Any, task_id: str, rows: Any) -> None:
        await super().backfill(conn, task_id, rows)
        (p,) = rows  # `World.read_logs` stands for the rows with the Pod
        self.effects.append(["backfill", task_id, p["metadata"]["name"]])

    def delete_namespaced_job(self, **kwargs: Any) -> None:
        self.effects.append(["delete", kwargs["name"]])
        super().delete_namespaced_job(**kwargs)


class _Lines(logging.Handler):
    """Appends tctl's log lines to the current recorder's effects."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.recorder: Recorder | None = None

    def emit(self, record: logging.LogRecord) -> None:
        if self.recorder is not None:
            self.recorder.effects.append(["log", record.levelname, record.getMessage()])


def _run(
    monkeypatch: pytest.MonkeyPatch,
    lines: _Lines,
    setup: Callable[[Recorder], None],
) -> list[list[Any]]:
    recorder = Recorder(monkeypatch)
    lines.recorder = recorder
    setup(recorder)
    recorder.tick()
    lines.recorder = None
    return recorder.effects


def _matrix_case(task: str, job_kind: str, pod_kind: str, timeout: str) -> Callable:
    def setup(world: Recorder) -> None:
        state, seen_for = TASKS[task]
        world.states[T1] = state
        if seen_for is not None:
            world.first_seen[T1] = world.clock - seen_for
        made_job = JOBS[job_kind]()
        made_pod = PODS[pod_kind]()
        world.jobs = [made_job] if made_job is not None else []
        world.pods = [made_pod] if made_pod is not None else []
        world.unschedulable_timeout = UNSCHEDULABLE_TIMEOUTS[timeout]

    return setup


def _two_pods(world: Recorder) -> None:
    """A Running Pod and a Failed one of the same task."""
    world.states[T1] = TesState.RUNNING
    world.jobs = [job(T1)]
    second = PODS["failed-executor"]()
    assert second is not None
    second["metadata"]["name"] = f"task-{T1}-fghij"
    world.pods = [pod(T1), second]


def _stuck_and_failed(world: Recorder) -> None:
    """A Pod stuck in Pending, then a Failed one, of the same task."""
    world.states[T1] = TesState.QUEUED
    world.jobs = [job(T1)]
    second = PODS["failed-executor"]()
    assert second is not None
    second["metadata"]["name"] = f"task-{T1}-fghij"
    world.pods = [_scheduled(400), second]


def _no_namespace(world: Recorder) -> None:
    """A Pod past its pending timeout without `metadata.namespace`."""
    world.states[T1] = TesState.QUEUED
    world.jobs = [job(T1)]
    stuck = _scheduled(400)
    del stuck["metadata"]["namespace"]
    world.pods = [stuck]


def _canceling_and_untracked(world: Recorder) -> None:
    """CANCELING per the second read, and a Pod of a task not in the DB."""
    world.states[T1] = TesState.CANCELING
    world.jobs = [job(T1), job(T2)]
    world.pods = [PODS["failed-executor"](), PODS["failed-executor"]()]
    world.pods[1]["metadata"]["labels"]["poiesis.io/task"] = T2


def _delete_fails(world: Recorder) -> None:
    """The CANCELING delete and the orphan delete both get a 500."""
    from kubernetes.client.exceptions import ApiException  # noqa: PLC0415

    world.states = {T1: TesState.CANCELING, T2: TesState.QUEUED}
    world.first_seen[T2] = world.clock - 31
    world.jobs = [job(T1)]
    world.delete_error = ApiException(status=500, reason="boom")


def _unlabelled(world: Recorder) -> None:
    """A Job and a Pod without the task label are skipped."""
    world.states[T1] = TesState.QUEUED
    bare_job = job(T1)
    bare_pod = PODS["failed-executor"]()
    assert bare_pod is not None
    del bare_job["metadata"]["labels"]
    del bare_pod["metadata"]["labels"]
    world.jobs = [bare_job]
    world.pods = [bare_pod]


SCENARIOS: dict[str, Callable[[Recorder], None]] = {
    "two-pods": _two_pods,
    "stuck-and-failed-pods": _stuck_and_failed,
    "pending-timeout-pod-without-namespace": _no_namespace,
    "canceling-and-untracked-task": _canceling_and_untracked,
    "deletes-fail": _delete_fails,
    "unlabelled-objects": _unlabelled,
}


def _cases() -> dict[str, Callable[[Recorder], None]]:
    cases: dict[str, Callable[[Recorder], None]] = {}
    for task, job_kind, pod_kind, timeout in itertools.product(
        TASKS, JOBS, PODS, UNSCHEDULABLE_TIMEOUTS
    ):
        name = f"task={task} job={job_kind} pod={pod_kind} unschedulable={timeout}"
        cases[name] = _matrix_case(task, job_kind, pod_kind, timeout)
    for name, setup in SCENARIOS.items():
        cases[f"scenario={name}"] = setup
    return cases


def _dump(results: dict[str, list[list[Any]]]) -> str:
    """The results as JSON, one effect per line, so diffs show which changed."""
    cases = []
    for name in sorted(results):
        effects = ",\n".join(f"    {json.dumps(e)}" for e in results[name])
        body = f"[\n{effects}\n  ]" if effects else "[]"
        cases.append(f"  {json.dumps(name)}: {body}")
    return "{\n" + ",\n".join(cases) + "\n}\n"


def test_matrix_size() -> None:
    """Every combination is in the golden file, and nothing else."""
    assert len(_cases()) == (
        len(TASKS) * len(JOBS) * len(PODS) * len(UNSCHEDULABLE_TIMEOUTS)
        + len(SCENARIOS)
    )


def test_reconcile_pass_matches_golden(monkeypatch: pytest.MonkeyPatch) -> None:
    """One pass per case; the effects equal the recorded ones."""
    lines = _Lines()
    logger = logging.getLogger(tctl.__name__)
    logger.addHandler(lines)
    old_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        results = {
            name: _run(monkeypatch, lines, setup) for name, setup in _cases().items()
        }
    finally:
        logger.removeHandler(lines)
        logger.setLevel(old_level)

    if not GOLDEN.exists() or os.environ.get("POIESIS_WRITE_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(_dump(results))
    expected = json.loads(GOLDEN.read_text())
    differing = sorted(
        name
        for name in expected.keys() | results.keys()
        if expected.get(name) != results.get(name)
    )
    assert not differing, "\n".join(
        f"{name}\n  expected {expected.get(name)}\n  got      {results.get(name)}"
        for name in differing[:5]
    )
