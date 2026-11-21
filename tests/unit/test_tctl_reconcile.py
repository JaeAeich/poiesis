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
    from collections.abc import AsyncIterator, Callable

NS = "tasks"
NOW = datetime.now(UTC)
T1 = "00000000-0000-4000-8000-000000000001"
T2 = "00000000-0000-4000-8000-000000000002"


def job(task_id: str, age: float = 60, **status: Any) -> dict[str, Any]:
    """A task Job created `age` seconds ago, with a time limit of 3600 s."""
    return {
        "metadata": {
            "name": f"task-{task_id}",
            "labels": {"poiesis.io/task": task_id},
            "creation_timestamp": datetime.now(UTC) - timedelta(seconds=age),
        },
        "spec": {"active_deadline_seconds": 3600},
        "status": status,
    }


def deadline(condition: str = "Failed") -> list[dict[str, Any]]:
    """The conditions of a Job whose time limit ran out."""
    return [
        {
            "type": condition,
            "status": "True",
            "reason": "DeadlineExceeded",
            "message": "Job was active longer than specified deadline",
        }
    ]


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
        self.delete_error: Exception | None = None
        self.clock = 1000.0
        self.first_seen: dict[str, float] = {}
        #: The operator's unschedulable timeout; None waits (the default).
        self.unschedulable_timeout: float | None = None
        #: Runs when the Pods are listed, i.e. in the middle of a pass.
        self.on_pod_list = lambda: None
        #: Asked by the pass before each task's actions; None: always leader.
        self.still_leader: Callable[[], bool] | None = None
        #: Raised once by the terminal write of a task.
        self.write_errors: dict[str, Exception] = {}
        #: Objects per list page; None returns each list in one page.
        self.page_size: int | None = None
        #: Raised once by the list of `kind` ("jobs", "pods") at `token`.
        self.list_errors: dict[tuple[str, str | None], Exception] = {}

        monkeypatch.setattr(tctl.time, "monotonic", lambda: self.clock)
        monkeypatch.setattr(
            tctl.state_db, "list_non_terminal_task_ids", self.non_terminal
        )
        monkeypatch.setattr(tctl.state_db, "list_canceling_task_ids", self.canceling)
        monkeypatch.setattr(tctl.state_db, "write_terminal_state", self.write)
        monkeypatch.setattr(tctl.state_db, "append_system_log", self.append_log)
        monkeypatch.setattr(tctl.state_db, "recorded_executor_ordinals", self.recorded)
        #: Tasks whose executor logs were backfilled from their Pod.
        self.backfilled: list[str] = []
        monkeypatch.setattr(tctl, "_read_executor_logs", self.read_logs)
        monkeypatch.setattr(tctl, "_write_executor_logs", self.backfill)

    async def read_logs(self, _pool: Any, _core: Any, _task_id: str, p: Any) -> Any:
        """Stands for the rows read from Pod `p`: `p` itself."""
        return [p]

    async def backfill(self, _conn: Any, task_id: str, _rows: Any) -> None:
        self.backfilled.append(task_id)

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
        error = self.write_errors.pop(task_id, None)
        if error is not None:
            raise error
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
    async def acquire(self) -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(transaction=contextlib.nullcontext)

    def list_namespaced_job(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append("jobs")
        return self.page("jobs", self.jobs, kwargs)

    def list_namespaced_pod(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append("pods")
        if kwargs.get("_continue") is None:
            self.on_pod_list()
        return self.page("pods", self.pods, kwargs)

    def page(
        self, kind: str, objects: list[dict[str, Any]], kwargs: dict[str, Any]
    ) -> Any:
        """One page of `objects`, `page_size` long, as the list API returns it."""
        assert kwargs.pop("_request_timeout") == tctl._REQUEST_TIMEOUT_SECONDS
        token = kwargs.pop("_continue")
        assert kwargs == {
            "namespace": NS,
            "label_selector": "poiesis.io/task",
            "limit": tctl._LIST_PAGE_SIZE,
        }
        error = self.list_errors.pop((kind, token), None)
        if error is not None:
            raise error
        start = int(token or 0)
        size = self.page_size or len(objects) or 1
        end = start + size
        return SimpleNamespace(
            items=list(objects[start:end]),
            metadata=SimpleNamespace(
                _continue=str(end) if end < len(objects) else None
            ),
        )

    def delete_namespaced_job(self, **kwargs: Any) -> None:
        assert kwargs["namespace"] == NS
        assert kwargs["_request_timeout"] == tctl._REQUEST_TIMEOUT_SECONDS
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
            tctl._reconcile_once(
                self,  # ty: ignore
                self,  # ty: ignore
                self,  # ty: ignore
                NS,
                self.first_seen,
                unschedulable_timeout=self.unschedulable_timeout,
                still_leader=self.still_leader,
            )
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

    def test_a_completed_job_without_pod_completes_the_task(
        self, world: World
    ) -> None:
        """The Job saw its Pod succeed: not an orphan, not an error (#163)."""
        world.states[T1] = TesState.RUNNING
        world.jobs = [job(T1, conditions=[{"type": "Complete", "status": "True"}])]
        world.tick()
        assert world.writes == {T1: (TesState.COMPLETE, None)}
        assert world.system_logs[T1] == [
            "the Job reports that its pod succeeded, but the pod was gone before "
            "tctl read it: executor logs that trec did not record are missing"
        ]
        assert world.deleted == []  # a finished Job is left to its TTL

    def test_pod_keeps_the_task(self, world: World) -> None:
        world.states[T1] = TesState.RUNNING
        world.pods = [pod(T1)]
        world.tick()
        world.tick(after=120)
        assert world.writes == {}


class TestLists:
    """Job and Pod lists are paginated; a pass acts on whole lists only (#163)."""

    def test_pages_are_joined(self, world: World) -> None:
        world.page_size = 1
        world.states = {T1: TesState.RUNNING, T2: TesState.RUNNING}
        world.pods = [pod(T1), pod(T2, "Failed")]
        world.first_seen = {T1: world.clock - 31, T2: world.clock - 31}
        world.tick()
        assert world.writes == {T2: (TesState.EXECUTOR_ERROR, "Error")}
        assert world.calls == ["db", "jobs", "pods", "pods"]

    def test_expired_continue_token_restarts_the_list(self, world: World) -> None:
        world.page_size = 1
        world.states = {T1: TesState.RUNNING, T2: TesState.RUNNING}
        world.pods = [pod(T1), pod(T2)]
        world.first_seen = {T1: world.clock - 31, T2: world.clock - 31}
        world.list_errors[("pods", "1")] = ApiException(status=410, reason="Gone")
        world.tick()
        assert world.writes == {}  # both Pods were read: no orphan
        assert world.calls == ["db", "jobs", "pods", "pods", "pods", "pods"]

    @pytest.mark.parametrize(
        "error",
        [ApiException(status=500, reason="boom"), TimeoutError("read timed out")],
    )
    def test_a_list_that_fails_midway_stops_the_pass(
        self, world: World, error: Exception
    ) -> None:
        """T2's Pod is on the unread page: it must not be called an orphan."""
        world.page_size = 1
        world.states = {T1: TesState.RUNNING, T2: TesState.RUNNING}
        world.pods = [pod(T1, "Failed"), pod(T2)]
        world.first_seen = {T1: world.clock - 31, T2: world.clock - 31}
        world.list_errors[("pods", "1")] = error
        with pytest.raises(type(error)):
            world.tick()
        assert world.writes == {}
        assert world.deleted == []

    def test_continue_token_that_keeps_expiring_stops_the_pass(
        self, world: World
    ) -> None:
        world.page_size = 1
        world.states = {T1: TesState.RUNNING}
        world.jobs = [job(T1), job(T2)]
        gone = ApiException(status=410, reason="Gone")

        def list_job(**kwargs: Any) -> SimpleNamespace:
            if kwargs.get("_continue") is not None:
                raise gone
            return World.list_namespaced_job(world, **kwargs)

        world.list_namespaced_job = list_job  # ty: ignore
        with pytest.raises(ApiException):
            world.tick()
        assert world.writes == {}


class TestErrorIsolation:
    """One task's error doesn't stop the pass for the others (#163)."""

    def test_a_failing_write_is_logged_and_the_pass_goes_on(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        world.states = {T1: TesState.RUNNING, T2: TesState.RUNNING}
        world.pods = [pod(T1, "Failed"), pod(T2, "Failed")]
        world.write_errors[T1] = OSError("connection reset")
        world.tick()
        assert set(world.writes) == {T2}
        assert f"applying the actions of task={T1} raised" in caplog.text
        world.tick()  # decided again on the next pass
        assert set(world.writes) == {T1, T2}

    def test_a_delete_that_times_out_does_not_stop_the_pass(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Only ApiException is handled in `_delete_job`; a timeout isn't one."""
        world.states = {T1: TesState.CANCELING, T2: TesState.RUNNING}
        world.jobs = [job(T1)]
        world.pods = [pod(T2, "Failed")]
        world.delete_error = TimeoutError("read timed out")
        world.tick()
        assert set(world.writes) == {T2}
        assert f"applying the actions of task={T1} raised" in caplog.text


def test_pass_stops_once_the_lease_is_no_longer_held(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    """Asked before each task's actions; nothing is applied after a no (#163)."""
    world.states = {T1: TesState.RUNNING, T2: TesState.RUNNING}
    world.pods = [pod(T1, "Failed"), pod(T2, "Failed")]
    answers = iter([True, False])
    world.still_leader = lambda: next(answers)
    world.tick()
    assert set(world.writes) == {T1}
    assert "lease no longer held; stopping the pass" in caplog.text


def test_pod_stuck_terminating_on_a_lost_node_ends_the_task(world: World) -> None:
    """Without the Job's time limit the task stayed RUNNING forever (#163)."""
    world.states[T1] = TesState.RUNNING
    no_limit = job(T1)
    no_limit["spec"] = {}
    world.jobs = [no_limit]
    stuck = pod(T1)
    stuck["metadata"]["deletion_timestamp"] = datetime.now(UTC) - timedelta(
        seconds=200
    )
    world.pods = [stuck]
    world.tick()
    assert world.writes == {}  # within the grace: the kubelet may still stop it
    stuck["metadata"]["deletion_timestamp"] -= timedelta(seconds=200)
    world.tick()
    assert world.writes == {T1: (TesState.SYSTEM_ERROR, "Pod stuck terminating")}
    assert world.deleted == [f"task-{T1}"]


class TestPodlessJobs:
    """Job-level failures end the task with their own reason (#158)."""

    def test_job_past_its_time_limit_reports_it(self, world: World) -> None:
        """The deadline ran out: the Job controller removed the Pod (#150)."""
        world.states[T1] = TesState.RUNNING
        world.jobs = [job(T1, age=3600, conditions=deadline())]
        world.tick()
        assert world.writes == {T1: (TesState.SYSTEM_ERROR, "DeadlineExceeded")}
        assert world.system_logs[T1] == ["task exceeded its time limit of 3600 seconds"]
        assert world.deleted == []

    def test_failed_job_reports_its_reason(self, world: World) -> None:
        """Any other failure keeps the Job's own reason and message."""
        world.states[T1] = TesState.RUNNING
        world.jobs = [
            job(
                T1,
                conditions=[
                    {
                        "type": "Failed",
                        "status": "True",
                        "reason": "BackoffLimitExceeded",
                        "message": "Job has reached the specified backoff limit",
                    }
                ],
            )
        ]
        world.tick()
        reason = (
            "Job failed: BackoffLimitExceeded: "
            "Job has reached the specified backoff limit"
        )
        assert world.writes == {T1: (TesState.SYSTEM_ERROR, reason)}
        assert world.system_logs[T1] == [
            "job failed without a pod: BackoffLimitExceeded: "
            "Job has reached the specified backoff limit"
        ]

    def test_job_without_a_pod_waits_by_default(self, world: World) -> None:
        """A ResourceQuota holds the Pod back: the task is queued (#151)."""
        world.states[T1] = TesState.QUEUED
        world.jobs = [job(T1, age=3000)]
        world.tick()
        world.tick(after=600)
        assert world.writes == {}
        assert world.deleted == []

    def test_job_without_a_pod_hits_the_unschedulable_timeout(
        self, world: World
    ) -> None:
        world.states[T1] = TesState.QUEUED
        world.unschedulable_timeout = 600
        world.jobs = [job(T1, age=590)]
        world.tick()
        assert world.writes == {}
        world.jobs = [job(T1, age=610)]
        world.tick()
        assert world.writes == {T1: (TesState.SYSTEM_ERROR, "Job created no Pod")}
        assert world.system_logs[T1] == [
            "unschedulable timeout: the Job created no Pod "
            "(see the Job's events: quota, admission)"
        ]

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
        world.unschedulable_timeout = 300
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
    """A scheduled Pod times out; an unscheduled one is queued (#151)."""

    def test_unschedulable_pod_waits_by_default(self, world: World) -> None:
        """1,000 tasks on room for 100: 900 Pods wait for a node, not fail."""
        world.states[T1] = TesState.QUEUED
        world.jobs = [job(T1, age=3000)]
        world.pods = [unscheduled(T1, age=3000)]
        world.tick()
        assert world.writes == {}
        assert world.deleted == []

    def test_unschedulable_pod_ends_at_the_time_limit(self, world: World) -> None:
        """The Job's deadline is what ends the wait by default."""
        world.states[T1] = TesState.QUEUED
        world.jobs = [job(T1, age=3600, conditions=deadline("FailureTarget"))]
        world.pods = [unscheduled(T1, age=3600)]
        world.tick()
        assert world.writes == {T1: (TesState.SYSTEM_ERROR, "DeadlineExceeded")}

    def test_unschedulable_timeout(self, world: World) -> None:
        """Set: counted from the Pod's creation, with the scheduler's message."""
        world.states[T1] = TesState.QUEUED
        world.unschedulable_timeout = 600
        world.jobs = [job(T1, age=700)]
        world.pods = [unscheduled(T1, age=700)]
        world.tick()
        assert world.writes == {T1: (TesState.SYSTEM_ERROR, "Insufficient CPU")}
        assert world.system_logs[T1] == [
            "unschedulable timeout: Insufficient CPU",
            "scheduler: 0/3 nodes are available: 3 Insufficient cpu.",
        ]
        assert world.deleted == [f"task-{T1}"]

    def test_camel_case_timestamp_string(self, world: World) -> None:
        """As in a raw API object, not a client model's `to_dict()`."""
        world.states[T1] = TesState.QUEUED
        world.unschedulable_timeout = 300
        created = (datetime.now(UTC) - timedelta(seconds=400)).isoformat()
        world.pods = [unscheduled(T1, age=0, creationTimestamp=created)]
        world.tick()
        assert world.writes[T1][0] is TesState.SYSTEM_ERROR

    def test_unschedulable_pod_within_the_timeout_waits(self, world: World) -> None:
        world.states[T1] = TesState.QUEUED
        world.unschedulable_timeout = 300
        world.pods = [unscheduled(T1, age=280)]
        world.tick()
        assert world.writes == {}

    def test_scheduled_pod_times_out_after_five_minutes(self, world: World) -> None:
        """Bound to a node, not starting (image pull): 5 minutes, as before."""
        world.states[T1] = TesState.QUEUED
        waiting = unscheduled(T1, age=400)
        waiting["status"] = {
            "phase": "Pending",
            "start_time": datetime.now(UTC) - timedelta(seconds=310),
        }
        world.pods = [waiting]
        world.tick()
        assert world.writes == {T1: (TesState.SYSTEM_ERROR, "Pending timeout")}
        assert world.system_logs[T1] == ["pending timeout: Pending timeout"]

    def test_start_time_wins_over_creation(self, world: World) -> None:
        """A scheduled Pod is timed from when it was bound, as before."""
        world.states[T1] = TesState.QUEUED
        world.unschedulable_timeout = 300
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
        world.unschedulable_timeout = 300
        world.pods = [pod(T1, "Pending")]
        world.tick()
        assert world.writes == {}


class TestTimeLimit:
    """A Pod killed by the Job's time limit ends with that cause (#150)."""

    def killed(self, phase: str, **metadata: Any) -> dict[str, Any]:
        """A Pod whose executor was stopped by SIGKILL."""
        killed = pod(
            T1,
            phase,
            init_container_statuses=[
                {
                    "name": "exec-0",
                    "state": {"terminated": {"exit_code": 137, "reason": "Error"}},
                }
            ],
        )
        killed["metadata"] |= metadata
        return killed

    def test_failed_pod_of_a_job_past_its_deadline(self, world: World) -> None:
        """Not EXECUTOR_ERROR exit 137: the time limit is the cause."""
        world.states[T1] = TesState.RUNNING
        world.jobs = [job(T1, age=3600, conditions=deadline())]
        world.pods = [self.killed("Failed")]
        world.tick()
        assert world.writes == {T1: (TesState.SYSTEM_ERROR, "DeadlineExceeded")}
        assert world.system_logs[T1] == ["task exceeded its time limit of 3600 seconds"]
        assert world.backfilled == [T1]
        assert world.deleted == []

    def test_terminating_pod_of_a_job_past_its_deadline(self, world: World) -> None:
        """Newer clusters set `FailureTarget` while the Pod still stops."""
        world.states[T1] = TesState.RUNNING
        world.jobs = [job(T1, age=3600, conditions=deadline("FailureTarget"))]
        world.pods = [self.killed("Running", deletion_timestamp=NOW)]
        world.tick()
        assert world.writes == {T1: (TesState.SYSTEM_ERROR, "DeadlineExceeded")}

    def test_failed_pod_of_a_live_job_is_classified_from_its_containers(
        self, world: World
    ) -> None:
        world.states[T1] = TesState.RUNNING
        world.jobs = [job(T1)]
        world.pods = [self.killed("Failed")]
        world.tick()
        assert world.writes[T1][0] is TesState.EXECUTOR_ERROR


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


@needs_postgres
def test_state_and_diagnostics_land_together(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing system log write rolls the state back; the next pass redoes it.

    Before #163 the state committed first: the failed log left the task
    terminal without its diagnostics, and the next pass was a no-op.
    """
    failed = pod(
        T1,
        "Failed",
        init_container_statuses=[
            {"name": "trec", "state": {"terminated": {"exit_code": 0}}},
            {"name": "exec-0", "state": {"terminated": {"exit_code": 1}}},
        ],
    )

    def no_logs(**_: Any) -> Any:
        raise ApiException(status=500, reason="no logs")

    kube = SimpleNamespace(
        list_namespaced_job=lambda **_: SimpleNamespace(items=[]),
        list_namespaced_pod=lambda **_: SimpleNamespace(items=[failed]),
        read_namespaced_pod_log=no_logs,
    )
    append = state_db.append_system_log
    failures = [OSError("connection reset")]

    async def flaky_append(conn: Any, task_id: str, message: str) -> None:
        if failures:
            raise failures.pop()
        await append(conn, task_id, message)

    monkeypatch.setattr(tctl.state_db, "append_system_log", flaky_append)

    async def test(pool: Any) -> None:
        task = TesTask(
            state=TesState.QUEUED,
            executors=[TesExecutor(image="alpine", command=["false"])],
        )
        async with pool.acquire() as conn:
            task_id = await tasks_db.create_task(conn, task, "owner")
        failed["metadata"]["labels"]["poiesis.io/task"] = task_id

        await tctl._reconcile_once(kube, kube, pool, NS, {})  # ty: ignore
        async with pool.acquire() as conn:
            after_failure = await tasks_db.get_task(conn, task_id)
        await tctl._reconcile_once(kube, kube, pool, NS, {})  # ty: ignore
        async with pool.acquire() as conn:
            after_retry = await tasks_db.get_task(conn, task_id)

        assert after_failure is not None
        assert after_failure.state == TesState.QUEUED
        assert after_retry is not None
        assert after_retry.state == TesState.EXECUTOR_ERROR
        (log,) = after_retry.logs or []
        # The reason (from the write), then the diagnostics: each once.
        assert log.system_logs == ["Error", "container exec-0 exited with code 1"]
        assert [(e.exit_code, e.stdout) for e in log.logs] == [(1, None)]

    run(test)


def test_no_database_connection_is_held_across_kubernetes_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The executor logs are read before the transaction opens (#163)."""
    held = 0
    events: list[str] = []

    class Conn:
        @contextlib.asynccontextmanager
        async def transaction(self) -> AsyncIterator[None]:
            events.append("begin")
            yield
            events.append("commit")

    class Pool:
        @contextlib.asynccontextmanager
        async def acquire(self) -> AsyncIterator[Conn]:
            nonlocal held
            held += 1
            try:
                yield Conn()
            finally:
                held -= 1

    async def read_streams(*_: Any) -> tuple[str, None]:
        assert held == 0
        events.append("read log")
        return "out\n", None

    async def recorded(_conn: Any, _task_id: str) -> set[int]:
        return set()

    async def write(*_: Any, **__: Any) -> state_db.TerminalWriteResult:
        events.append("write")
        return state_db.TerminalWriteResult.APPLIED

    async def append_executor_log(*_: Any, **row: Any) -> None:
        events.append(f"executor log {row['stdout']!r}")

    async def append_system_log(*_: Any) -> None:
        events.append("system log")

    monkeypatch.setattr(tctl, "read_executor_streams", read_streams)
    monkeypatch.setattr(tctl.state_db, "recorded_executor_ordinals", recorded)
    monkeypatch.setattr(tctl.state_db, "write_terminal_state", write)
    monkeypatch.setattr(tctl.state_db, "append_executor_log", append_executor_log)
    monkeypatch.setattr(tctl.state_db, "append_system_log", append_system_log)
    failed = pod(
        T1,
        "Failed",
        init_container_statuses=[
            {"name": "exec-0", "state": {"terminated": {"exit_code": 1}}}
        ],
    )

    wrote = asyncio.run(
        tctl._apply_terminal(
            Pool(),  # ty: ignore
            core_v1=object(),  # ty: ignore
            task_id=T1,
            pod=failed,
            proposed=TesState.EXECUTOR_ERROR,
            reason="Error",
            system_logs=["container exec-0 exited with code 1"],
            source="pod-terminal",
        )
    )

    assert wrote
    assert events == [
        "read log",
        "begin",
        "write",
        "executor log 'out\\n'",
        "system log",
        "commit",
    ]
