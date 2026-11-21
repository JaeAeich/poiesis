"""tctl's reconcile pass over task rows, Jobs and Pods, with all three faked.

`World` holds what Postgres and Kubernetes would answer; a test sets it up,
runs passes with `World.tick`, and reads the terminal writes from
`World.writes`.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from kubernetes.client.exceptions import ApiException
from postgres import needs_postgres, run

from poiesis.api.tes.models import TesExecutor, TesState, TesTask
from poiesis.core import tctl
from poiesis.db import state as state_db
from poiesis.db import tasks as tasks_db

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

NS = "tasks"
NOW = datetime.now(UTC)
T1 = "00000000-0000-4000-8000-000000000001"
T2 = "00000000-0000-4000-8000-000000000002"


def job(task_id: str, age: float = 60, **status: Any) -> dict[str, Any]:
    """A task Job created `age` seconds ago."""
    return {
        "metadata": {
            "name": f"task-{task_id}",
            "labels": {"poiesis.io/task": task_id},
            "creation_timestamp": datetime.now(UTC) - timedelta(seconds=age),
        },
        "status": status,
    }


def pod(task_id: str, phase: str = "Running", **status: Any) -> dict[str, Any]:
    """A TaskPod in `phase`."""
    return {
        "metadata": {
            "name": f"task-{task_id}-abcde",
            "namespace": NS,
            "labels": {"poiesis.io/task": task_id},
        },
        "status": {"phase": phase, **status},
    }


class World:
    """Fake Postgres rows and Kubernetes objects for `tctl._reconcile_once`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Start empty, at monotonic time 1000."""
        self.states: dict[str, TesState] = {}
        self.jobs: list[dict[str, Any]] = []
        self.pods: list[dict[str, Any]] = []
        self.writes: dict[str, tuple[TesState, str | None]] = {}
        self.system_logs: dict[str, list[str]] = {}
        self.calls: list[str] = []
        self.deleted: list[str] = []
        self.delete_error: ApiException | None = None
        self.clock = 1000.0
        self.first_seen: dict[str, float] = {}
        #: Runs when the Pods are listed, i.e. in the middle of a pass.
        self.on_pod_list = lambda: None

        monkeypatch.setattr(tctl.time, "monotonic", lambda: self.clock)
        monkeypatch.setattr(
            tctl.state_db, "list_non_terminal_task_ids", self.non_terminal
        )
        monkeypatch.setattr(tctl.state_db, "list_canceling_task_ids", self.canceling)
        monkeypatch.setattr(tctl.state_db, "write_terminal_state", self.write)
        monkeypatch.setattr(tctl.state_db, "append_system_log", self.append_log)
        monkeypatch.setattr(tctl.state_db, "recorded_executor_ordinals", self.recorded)

    async def non_terminal(self, _conn: Any, **_: Any) -> list[str]:
        self.calls.append("db")
        return [
            task_id
            for task_id, state in self.states.items()
            if state not in state_db.TERMINAL_STATES
        ]

    async def canceling(self, _conn: Any) -> list[str]:
        return [t for t, state in self.states.items() if state is TesState.CANCELING]

    async def write(
        self, _conn: Any, task_id: str, proposed: TesState, reason: str | None = None
    ) -> state_db.TerminalWriteResult:
        current = self.states.get(task_id)
        if current is None or current in state_db.TERMINAL_STATES:
            return state_db.TerminalWriteResult.NO_OP
        canceling = current is TesState.CANCELING
        self.states[task_id] = TesState.CANCELED if canceling else proposed
        self.writes[task_id] = (self.states[task_id], reason)
        return (
            state_db.TerminalWriteResult.CANCELED_INSTEAD
            if canceling
            else state_db.TerminalWriteResult.APPLIED
        )

    async def recorded(self, _conn: Any, _task_id: str) -> set[int]:
        return set()

    async def append_log(self, _conn: Any, task_id: str, message: str) -> None:
        self.system_logs.setdefault(task_id, []).append(message)

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        yield None

    def list_namespaced_job(self, **kwargs: Any) -> SimpleNamespace:
        assert kwargs == {"namespace": NS, "label_selector": "poiesis.io/task"}
        self.calls.append("jobs")
        return SimpleNamespace(items=list(self.jobs))

    def list_namespaced_pod(self, **kwargs: Any) -> SimpleNamespace:
        assert kwargs == {"namespace": NS, "label_selector": "poiesis.io/task"}
        self.calls.append("pods")
        self.on_pod_list()
        return SimpleNamespace(items=list(self.pods))

    def delete_namespaced_job(self, **kwargs: Any) -> None:
        assert kwargs["namespace"] == NS
        assert kwargs["propagation_policy"] == "Background"
        self.deleted.append(kwargs["name"])
        if self.delete_error is not None:
            raise self.delete_error
        self.jobs = [j for j in self.jobs if j["metadata"]["name"] != kwargs["name"]]
        self.pods = [
            p for p in self.pods if not p["metadata"]["name"].startswith(kwargs["name"])
        ]

    def tick(self, after: float = 0) -> None:
        """Run one reconcile pass, `after` seconds after the last one."""
        self.clock += after
        asyncio.run(
            tctl._reconcile_once(self, self, self, NS, self.first_seen)  # ty: ignore
        )


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    return World(monkeypatch)


class TestOrphans:
    """A task is an orphan only without a live Job or Pod for the grace (#158)."""

    def test_task_with_a_live_job_is_not_an_orphan(self, world: World) -> None:
        """A Job whose Pod isn't created yet (quota, backlog) keeps the task."""
        world.states[T1] = TesState.QUEUED
        world.jobs = [job(T1)]
        world.tick()
        world.tick(after=120)
        assert world.writes == {}

    def test_task_rows_are_read_before_jobs_and_pods(self, world: World) -> None:
        """A task created while a pass runs isn't judged by that pass."""
        world.states[T1] = TesState.QUEUED
        world.on_pod_list = lambda: world.states.setdefault(T2, TesState.QUEUED)
        world.tick()
        world.tick(after=31)
        assert world.calls[:3] == ["db", "jobs", "pods"]
        assert set(world.writes) == {T1}

    def test_grace_runs_on_tctls_own_clock(self, world: World) -> None:
        """However old the row's `creation_time` says it is, tctl waits 30 s."""
        world.states[T1] = TesState.QUEUED
        world.tick()
        world.tick(after=29)
        assert world.writes == {}
        world.tick(after=1)
        assert world.writes == {
            T1: (
                TesState.SYSTEM_ERROR,
                "Pod disappeared before reaching terminal phase",
            )
        }
        assert world.system_logs[T1] == [
            "pod disappeared before reaching terminal phase"
        ]

    def test_new_leader_waits_the_grace_again(self, world: World) -> None:
        """`first_seen` is per leadership term: nothing is carried over."""
        world.states[T1] = TesState.QUEUED
        world.tick()
        world.first_seen = {}
        world.tick(after=31)
        assert world.writes == {}

    def test_a_job_being_deleted_does_not_keep_the_task(self, world: World) -> None:
        """Foreground deletion leaves the Job listed; the task is still gone."""
        world.states[T1] = TesState.CANCELING
        deleted = job(T1)
        deleted["metadata"]["deletion_timestamp"] = NOW
        world.jobs = [deleted]
        world.tick()
        world.tick(after=31)
        assert world.writes[T1][0] is TesState.CANCELED
        assert world.deleted == [f"task-{T1}"]  # after the write, as for any orphan

    def test_a_completed_job_without_pod_does_not_keep_the_task(
        self, world: World
    ) -> None:
        world.states[T1] = TesState.RUNNING
        world.jobs = [job(T1, conditions=[{"type": "Complete", "status": "True"}])]
        world.tick()
        world.tick(after=31)
        assert world.writes[T1][0] is TesState.SYSTEM_ERROR

    def test_pod_keeps_the_task(self, world: World) -> None:
        world.states[T1] = TesState.RUNNING
        world.pods = [pod(T1)]
        world.tick()
        world.tick(after=120)
        assert world.writes == {}


class TestPodlessJobs:
    """Job-level failures end the task with their own reason (#158)."""

    def test_failed_job_reports_its_reason(self, world: World) -> None:
        """The deadline ran out: the Job controller removed the Pod."""
        world.states[T1] = TesState.RUNNING
        world.jobs = [
            job(
                T1,
                age=3600,
                conditions=[
                    {
                        "type": "Failed",
                        "status": "True",
                        "reason": "DeadlineExceeded",
                        "message": "Job was active longer than specified deadline",
                    }
                ],
            )
        ]
        world.tick()
        reason = (
            "Job failed: DeadlineExceeded: "
            "Job was active longer than specified deadline"
        )
        assert world.writes == {T1: (TesState.SYSTEM_ERROR, reason)}
        assert world.system_logs[T1] == [
            "job failed without a pod: DeadlineExceeded: "
            "Job was active longer than specified deadline"
        ]

    def test_job_that_never_makes_a_pod_times_out(self, world: World) -> None:
        """A ResourceQuota rejects the Pod: 5 minutes, like a Pending Pod."""
        world.states[T1] = TesState.QUEUED
        world.jobs = [job(T1, age=290)]
        world.tick()
        assert world.writes == {}
        world.jobs = [job(T1, age=310)]
        world.tick()
        assert world.writes == {T1: (TesState.SYSTEM_ERROR, "Job created no Pod")}
        assert world.system_logs[T1][0].startswith("pending timeout: the Job created")

    def test_job_with_a_pod_is_left_to_the_pod(self, world: World) -> None:
        world.states[T1] = TesState.RUNNING
        world.jobs = [job(T1, age=900)]
        world.pods = [pod(T1)]
        world.tick()
        assert world.writes == {}


class TestJobDeletes:
    """tctl deletes the Jobs of tasks that must not run any more (#155)."""

    def test_canceling_task_loses_its_job(self, world: World) -> None:
        """A cancel whose Job delete failed, or came before the Job existed."""
        world.states[T1] = TesState.CANCELING
        world.jobs = [job(T1)]
        world.pods = [pod(T1)]
        world.tick()
        assert world.deleted == [f"task-{T1}"]
        assert world.writes == {}
        world.tick(after=31)
        assert world.writes[T1][0] is TesState.CANCELED
        assert world.system_logs[T1] == ["task cancelled by client"]

    def test_failed_delete_is_tried_again(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The pass goes on; the next one deletes the Job again."""
        world.states = {T1: TesState.CANCELING, T2: TesState.CANCELING}
        world.jobs = [job(T1), job(T2)]
        world.delete_error = ApiException(status=500, reason="boom")
        world.tick()
        assert world.deleted == [f"task-{T1}", f"task-{T2}"]
        assert "could not delete the Job of task=" in caplog.text
        world.delete_error = None
        world.tick(after=5)
        assert world.deleted[2:] == [f"task-{T1}", f"task-{T2}"]
        assert world.jobs == []

    def test_job_already_being_deleted_is_left_alone(self, world: World) -> None:
        world.states[T1] = TesState.CANCELING
        deleting = job(T1)
        deleting["metadata"]["deletion_timestamp"] = NOW
        world.jobs = [deleting]
        world.tick()
        assert world.deleted == []

    def test_running_task_keeps_its_job(self, world: World) -> None:
        world.states[T1] = TesState.RUNNING
        world.jobs = [job(T1)]
        world.pods = [pod(T1)]
        world.tick()
        world.tick(after=600)
        assert world.deleted == []

    def test_pending_timeout_deletes_the_job(self, world: World) -> None:
        """Else the Pod runs once its image can be pulled, for a failed task."""
        world.states[T1] = TesState.QUEUED
        world.jobs = [job(T1, age=400)]
        world.pods = [
            pod(
                T1,
                "Pending",
                start_time=datetime.now(UTC) - timedelta(seconds=400),
                init_container_statuses=[
                    {"name": "exec-0", "state": {"waiting": {"reason": "ErrImagePull"}}}
                ],
            )
        ]
        world.tick()
        assert world.writes == {T1: (TesState.SYSTEM_ERROR, "ErrImagePull")}
        assert world.deleted == [f"task-{T1}"]

    def test_job_without_pod_timeout_deletes_the_job(self, world: World) -> None:
        world.states[T1] = TesState.QUEUED
        world.jobs = [job(T1, age=400)]
        world.tick()
        assert world.writes[T1][0] is TesState.SYSTEM_ERROR
        assert world.deleted == [f"task-{T1}"]

    def test_orphan_deletes_the_job(self, world: World) -> None:
        """A Job created after the lists must not start a failed task."""
        world.states[T1] = TesState.QUEUED
        world.tick()
        world.tick(after=31)
        assert world.writes[T1][0] is TesState.SYSTEM_ERROR
        assert world.deleted == [f"task-{T1}"]

    def test_missing_job_is_not_an_error(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        world.states[T1] = TesState.QUEUED
        world.delete_error = ApiException(status=404, reason="Not Found")
        world.tick()
        world.tick(after=31)
        assert world.deleted == [f"task-{T1}"]
        assert "could not delete" not in caplog.text

    @pytest.mark.parametrize("phase", ["Succeeded", "Failed"])
    def test_finished_pod_keeps_its_job(self, world: World, phase: str) -> None:
        """The Job of a finished Pod is left to its TTL, with the PVC."""
        world.states[T1] = TesState.RUNNING
        world.jobs = [job(T1)]
        world.pods = [pod(T1, phase)]
        world.tick()
        assert T1 in world.writes
        assert world.deleted == []

    def test_failed_job_is_kept(self, world: World) -> None:
        world.states[T1] = TesState.RUNNING
        world.jobs = [job(T1, conditions=[{"type": "Failed", "status": "True"}])]
        world.tick()
        assert world.writes == {T1: (TesState.SYSTEM_ERROR, "Job failed: Failed")}
        assert world.deleted == []

    def test_nothing_is_deleted_for_a_task_already_final(self, world: World) -> None:
        """Nor for a Pod of another installation sharing the namespace."""
        world.states[T1] = TesState.COMPLETE
        world.jobs = [job(T1, age=400), job(T2, age=400)]
        world.pods = [
            pod(T2, "Pending", start_time=datetime.now(UTC) - timedelta(seconds=400))
        ]
        world.tick()
        world.tick(after=31)
        assert world.writes == {}
        assert world.deleted == []


def unscheduled(task_id: str, age: float, **metadata: Any) -> dict[str, Any]:
    """A Pod the scheduler couldn't place: Pending, no `start_time`."""
    pending = pod(
        task_id,
        "Pending",
        conditions=[
            {
                "type": "PodScheduled",
                "status": "False",
                "reason": "Unschedulable",
                "message": "0/3 nodes are available: 3 Insufficient cpu.",
            }
        ],
    )
    pending["metadata"] |= metadata or {
        "creation_timestamp": datetime.now(UTC) - timedelta(seconds=age)
    }
    return pending


class TestPendingTimeout:
    """A Pod that is never scheduled hits the pending timeout too (#151)."""

    def test_unschedulable_pod_times_out(self, world: World) -> None:
        """No `startTime`: 5 minutes are counted from the Pod's creation."""
        world.states[T1] = TesState.QUEUED
        world.jobs = [job(T1, age=400)]
        world.pods = [unscheduled(T1, age=400)]
        world.tick()
        assert world.writes == {T1: (TesState.SYSTEM_ERROR, "Insufficient CPU")}
        assert world.system_logs[T1] == [
            "pending timeout: Insufficient CPU",
            "scheduler: 0/3 nodes are available: 3 Insufficient cpu.",
        ]
        assert world.deleted == [f"task-{T1}"]

    def test_camel_case_timestamp_string(self, world: World) -> None:
        """As in a raw API object, not a client model's `to_dict()`."""
        world.states[T1] = TesState.QUEUED
        created = (datetime.now(UTC) - timedelta(seconds=400)).isoformat()
        world.pods = [unscheduled(T1, age=0, creationTimestamp=created)]
        world.tick()
        assert world.writes[T1][0] is TesState.SYSTEM_ERROR

    def test_unschedulable_pod_waits_five_minutes(self, world: World) -> None:
        """A cluster autoscaler has that long to add a node."""
        world.states[T1] = TesState.QUEUED
        world.pods = [unscheduled(T1, age=280)]
        world.tick()
        assert world.writes == {}

    def test_start_time_wins_over_creation(self, world: World) -> None:
        """A scheduled Pod is timed from when it was bound, as before."""
        world.states[T1] = TesState.QUEUED
        waiting = unscheduled(T1, age=400)
        waiting["status"] = {
            "phase": "Pending",
            "start_time": datetime.now(UTC) - timedelta(seconds=100),
        }
        world.pods = [waiting]
        world.tick()
        assert world.writes == {}

    def test_pod_without_any_timestamp_waits(self, world: World) -> None:
        world.states[T1] = TesState.QUEUED
        world.pods = [pod(T1, "Pending")]
        world.tick()
        assert world.writes == {}


@needs_postgres
def test_canceling_tasks_are_listed() -> None:
    """`list_canceling_task_ids` returns the CANCELING tasks only (#155)."""

    async def test(pool: Any) -> None:
        task = TesTask(
            state=TesState.QUEUED,
            executors=[TesExecutor(image="alpine", command=["true"])],
        )
        async with pool.acquire() as conn:
            queued = await tasks_db.create_task(conn, task, "owner")
            cancelled = await tasks_db.create_task(conn, task, "owner")
            done = await tasks_db.create_task(conn, task, "owner")
            for task_id in (cancelled, done):
                assert await state_db.mark_canceling(conn, task_id)
            await state_db.write_terminal_state(conn, done, TesState.SYSTEM_ERROR)
            assert await state_db.list_canceling_task_ids(conn) == [cancelled]
            assert queued not in await state_db.list_canceling_task_ids(conn)

    run(test)


@needs_postgres
def test_old_creation_time_does_not_shorten_the_grace() -> None:
    """A row stamped by a slow API clock looks old; tctl still waits (#158)."""
    never = SimpleNamespace(
        list_namespaced_job=lambda **_: SimpleNamespace(items=[]),
        list_namespaced_pod=lambda **_: SimpleNamespace(items=[]),
        delete_namespaced_job=lambda **_: None,
    )

    async def test(pool: Any) -> None:
        task = TesTask(
            state=TesState.QUEUED,
            executors=[TesExecutor(image="alpine", command=["true"])],
            creation_time=(NOW - timedelta(hours=1)).isoformat(),
        )
        async with pool.acquire() as conn:
            task_id = await tasks_db.create_task(conn, task, "owner")
        first_seen: dict[str, float] = {}
        await tctl._reconcile_once(never, never, pool, NS, first_seen)  # ty: ignore
        async with pool.acquire() as conn:
            waiting = await tasks_db.get_task(conn, task_id)
        first_seen[task_id] -= 31
        await tctl._reconcile_once(never, never, pool, NS, first_seen)  # ty: ignore
        async with pool.acquire() as conn:
            ended = await tasks_db.get_task(conn, task_id)
        assert waiting is not None
        assert ended is not None
        assert waiting.state == TesState.QUEUED
        assert ended.state == TesState.SYSTEM_ERROR

    run(test)
