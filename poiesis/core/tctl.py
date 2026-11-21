"""Task Controller — single writer for terminal task state.

TCtl is the leader-elected cluster-wide controller. Every TES task's
terminal write goes through this module — trec deliberately stays out of
that responsibility so there's exactly one place to debug a task stuck
in a non-terminal state.

The control loop is a polling reconciler: every `_RECONCILE_INTERVAL_SECONDS`
the leader lists every non-terminal task in the DB, then every task Job and
TaskPod, joins them, and writes terminal state for any combination that
warrants it. No watch, no event stream, no race between two writers.
Each pass gathers its inputs once (`_gather`), decides what to do about
each task without any I/O (`core/reconcile.py`) and applies the actions
(`_apply`).

Cases the reconciler covers:

    * Pod reached `Succeeded` or `Failed` → write the matching terminal,
    backfill any executor_logs trec didn't get to before its own
    sidecar SIGTERM (with the tail of each executor's log as stdout),
    append a system_logs entry describing the failure.
    * Job past its time limit (`DeadlineExceeded`) → SYSTEM_ERROR with
    "task exceeded its time limit", whether its Pod is gone, finished or
    still terminating; the killed executor's exit code is not the cause.
    * Pod bound to a node but stuck in `Pending` past
    `_PENDING_TIMEOUT_SECONDS` (image pull, volume mount) → SYSTEM_ERROR
    with the kubelet's pending reason in system_logs.
    * Pod the scheduler hasn't placed: the task is queued, not failed. It
    waits until the Job's time limit, or, when the operator set an
    unschedulable timeout, until that ends it as SYSTEM_ERROR with the
    scheduler's message.
    * Task `CANCELING` with a Job → delete the Job. The API deletes it on
    cancel; this covers a delete that failed and a Job created after it.
    * Job without a Pod: a failed Job → SYSTEM_ERROR with the Job's
    reason. A live Job that has made no Pod yet (ResourceQuota, admission)
    is queued like an unscheduled Pod: it waits, or hits the unschedulable
    timeout when one is set.
    * Task non-terminal in DB with neither a live Job nor a Pod, on every
    pass for `_ORPHAN_GRACE_SECONDS` (so we don't race with brand-new
    tasks whose Job hasn't been created yet) → SYSTEM_ERROR. The writer's
    CANCELING-precedence rule turns this into CANCELED for cancelled
    tasks; the orphan path covers true pod-gone-without-notice cases
    (manual kubectl delete, node loss before the pod was rescheduled).

The writer (`state.write_terminal_state`) is idempotent and
CANCELING-aware, so re-running the loop against an already-finalised
task is a no-op.

A terminal write that doesn't come from a finished Pod or Job (pending or
unschedulable timeout, orphan) is followed by a delete of the task's
Job, so a Pod that becomes runnable later can't run a task already reported
as failed. That delete is the only write tctl makes to Kubernetes.

Every Kubernetes call has a request timeout, and the Job and Pod lists are
read page by page. A pass that can't read a whole list acts on nothing.

Leader election uses `coordination.k8s.io/v1` Leases (see `core/leases.py`).
The leader renews its Lease on its own timer (`_keep_lease`), also while a
pass runs; a pass stops before the next task's actions once the Lease is
lost or its last renewal is too old to be sure no one else holds it.
The Lease lives in the namespace tctl runs in (the release namespace), which
is not the TaskPod namespace when the two are split.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, cast

import asyncpg
from kubernetes.client import BatchV1Api, CoordinationV1Api, CoreV1Api
from kubernetes.client.exceptions import ApiException

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from poiesis.api.tes.models import TesState

from poiesis.core import ignore_error
from poiesis.core.executor_logs import read_executor_streams, streams_from_pod
from poiesis.core.leases import try_acquire_or_renew
from poiesis.core.reconcile import (
    Action,
    DeleteJob,
    TaskView,
    Timeouts,
    WriteTerminal,
    decide,
)
from poiesis.core.reconcile import parse_kubelet_ts as _parse_kubelet_ts
from poiesis.core.reconcile import (  # noqa: F401 (still importable from here)
    terminal_system_logs as _terminal_system_logs,
)
from poiesis.core.taskpod import job_name_for
from poiesis.db import state as state_db

logger = logging.getLogger(__name__)

_TASK_LABEL = "poiesis.io/task"
_LEASE_NAME = "poiesis-tctl-leader"
_LEASE_DURATION_SECONDS = 30
_LEASE_RENEW_INTERVAL_SECONDS = 10
#: How long before the Lease could expire tctl stops acting as leader: a
#: renewal started at `t` is trusted until `t + duration - margin`. Covers
#: clock skew with the instance that would take the Lease over.
_LEASE_SAFETY_MARGIN_SECONDS = 10
#: How often the reconciler walks the world.
_RECONCILE_INTERVAL_SECONDS = 5
#: How long a TaskPod bound to a node may sit in Pending before the
#: controller times it out, counted from `status.startTime`. Covers
#: `ImagePullBackOff`, volumes that can't be mounted, etc. A Pod not bound
#: yet is waiting for capacity; the operator's unschedulable timeout, if
#: any, applies to it instead (see `_pending_timeout`).
_PENDING_TIMEOUT_SECONDS = 300
#: Grace before treating a non-terminal task with no live Job or Pod as
#: orphaned: how long tctl must have seen it that way, by its own monotonic
#: clock. Covers the window between the API's row insert and its Job create.
_ORPHAN_GRACE_SECONDS = 30
#: (connect, read) timeouts of every Kubernetes call tctl makes, so a stuck
#: API server can't hold a pass forever.
_REQUEST_TIMEOUT_SECONDS = (10, 30)
#: The Lease calls get shorter ones: a renewal must end well within
#: `_LEASE_DURATION_SECONDS`.
_LEASE_REQUEST_TIMEOUT_SECONDS = (5, 10)
#: Objects per page of a Job or Pod list.
_LIST_PAGE_SIZE = 500
#: How many times a list restarts after its continue token expired (410).
_LIST_RESTARTS = 3


async def run(
    namespace: str,
    dsn: str,
    *,
    lease_namespace: str | None = None,
    identity: str | None = None,
    unschedulable_timeout: float | None = None,
    heartbeat: Path | None = None,
) -> int:
    """Run the TCtl reconciliation loop until SIGTERM/SIGINT.

    `namespace` is where the TaskPods are; `lease_namespace` is where the
    leader Lease is kept (default: `namespace`). `unschedulable_timeout`
    is how many seconds a task may wait for its Pod to be created and
    scheduled; None waits until the Job's time limit. `heartbeat`, if set,
    is a file touched at startup and after each loop iteration, leader or
    standby, for a liveness probe to check its age. Holds the Lease while
    reconciling; gives it up cleanly on signal. Returns 0 on clean shutdown.
    """
    lease_namespace = lease_namespace or namespace
    identity = identity or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    cancelled = _install_signal_handlers()

    coord_v1 = CoordinationV1Api()
    core_v1 = CoreV1Api()
    batch_v1 = BatchV1Api()
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    try:
        while not cancelled.is_set():
            _beat(heartbeat)
            started = time.monotonic()
            acquired = await _hold_lease(coord_v1, lease_namespace, identity)
            if not acquired:
                logger.debug("tctl: not leader; sleeping")
                await _wait_or_cancel(cancelled, _LEASE_RENEW_INTERVAL_SECONDS)
                continue
            logger.info("tctl: acquired lease as %s", identity)
            await _reconcile_while_leader(
                core_v1,
                batch_v1,
                coord_v1,
                pool,
                namespace,
                lease_namespace,
                identity,
                cancelled,
                _Leadership(started),
                unschedulable_timeout,
                heartbeat=heartbeat,
            )
    finally:
        await pool.close()
    return 0


def _beat(heartbeat: Path | None) -> None:
    """Touch the heartbeat file: this loop is not hung.

    A failed touch is logged, not raised: the liveness probe then sees an
    old file and restarts tctl, which is the signal wanted.
    """
    if heartbeat is None:
        return
    try:
        heartbeat.touch()
    except OSError as exc:
        logger.warning("tctl: could not touch heartbeat %s: %s", heartbeat, exc)


async def _hold_lease(
    coord_v1: CoordinationV1Api, lease_namespace: str, identity: str
) -> bool:
    """Acquire or renew the leader Lease; False if `identity` doesn't hold it.

    A Kubernetes API error (a 403 from missing RBAC, a 5xx, a timeout) counts
    as not holding the Lease: it is logged and the caller tries again, so
    tctl neither exits nor reconciles while it can't prove it is the leader.
    """
    try:
        return await try_acquire_or_renew(
            coord_v1,
            name=_LEASE_NAME,
            namespace=lease_namespace,
            identity=identity,
            lease_duration_seconds=_LEASE_DURATION_SECONDS,
            request_timeout=_LEASE_REQUEST_TIMEOUT_SECONDS,
        )
    except ApiException as exc:
        logger.error(
            "tctl: lease %s/%s unavailable (%s %s); will retry",
            lease_namespace,
            _LEASE_NAME,
            exc.status,
            exc.reason,
        )
        return False
    except Exception as exc:  # noqa: BLE001 - a timeout or a dropped connection
        logger.error(
            "tctl: lease %s/%s unavailable (%s); will retry",
            lease_namespace,
            _LEASE_NAME,
            exc,
        )
        return False


class _Leadership:
    """Whether this instance may still act as the leader.

    It may until a renewal fails, and only while the last successful
    renewal is recent enough that no other instance can have taken the
    Lease over: a renewal started at monotonic time `t` is trusted until
    `t + _LEASE_DURATION_SECONDS - _LEASE_SAFETY_MARGIN_SECONDS`. A renewal
    that hangs therefore stops the pass too, before the Lease expires.
    """

    def __init__(self, renewed_at: float) -> None:
        """Start as leader, from a successful acquire or renewal at `renewed_at`."""
        self._lost = False
        self._valid_until = 0.0
        self.renewed(renewed_at)

    def renewed(self, at: float) -> None:
        """Record a successful renewal started at monotonic time `at`."""
        self._valid_until = at + _LEASE_DURATION_SECONDS - _LEASE_SAFETY_MARGIN_SECONDS

    def lose(self) -> None:
        """Record a failed renewal: this instance is no longer the leader."""
        self._lost = True

    def held(self) -> bool:
        """True while this instance may still act as the leader."""
        return not self._lost and time.monotonic() < self._valid_until


async def _keep_lease(
    coord_v1: CoordinationV1Api,
    lease_namespace: str,
    identity: str,
    leadership: _Leadership,
    cancelled: asyncio.Event,
) -> None:
    """Renew the Lease every `_LEASE_RENEW_INTERVAL_SECONDS`, until it fails.

    Runs as its own task beside the reconcile loop, so a pass longer than
    the Lease duration doesn't lose the Lease.
    """
    while not cancelled.is_set():
        await _wait_or_cancel(cancelled, _LEASE_RENEW_INTERVAL_SECONDS)
        if cancelled.is_set():
            return
        started = time.monotonic()
        if not await _hold_lease(coord_v1, lease_namespace, identity):
            leadership.lose()
            return
        leadership.renewed(started)


async def _reconcile_while_leader(  # noqa: PLR0913 (one pass's inputs and the Lease)
    core_v1: CoreV1Api,
    batch_v1: BatchV1Api,
    coord_v1: CoordinationV1Api,
    pool: asyncpg.Pool,
    namespace: str,
    lease_namespace: str,
    identity: str,
    cancelled: asyncio.Event,
    leadership: _Leadership,
    unschedulable_timeout: float | None = None,
    *,
    heartbeat: Path | None = None,
) -> None:
    """Reconcile every `_RECONCILE_INTERVAL_SECONDS` until the Lease is lost.

    The Lease is renewed by `_keep_lease` meanwhile. A pass checks
    `leadership` before each task's actions and stops once it no longer
    holds.
    """
    # Per leadership term: a new leader observes for a full grace period
    # before it calls any task an orphan.
    first_seen: dict[str, float] = {}
    renewer = asyncio.create_task(
        _keep_lease(coord_v1, lease_namespace, identity, leadership, cancelled)
    )
    try:
        while not cancelled.is_set():
            if not leadership.held():
                logger.warning("tctl: lost lease; standing down")
                return
            try:
                await _reconcile_once(
                    core_v1,
                    batch_v1,
                    pool,
                    namespace,
                    first_seen,
                    unschedulable_timeout=unschedulable_timeout,
                    still_leader=leadership.held,
                )
            except Exception:
                logger.exception(
                    "tctl: reconcile tick raised; will retry next interval"
                )
            _beat(heartbeat)
            await _wait_or_cancel(cancelled, _RECONCILE_INTERVAL_SECONDS)
    finally:
        renewer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await renewer


@dataclass(frozen=True)
class _Snapshot:
    """What one pass read, before deciding anything.

    Attributes:
        non_terminal: Non-terminal task ids, in the DB's order.
        canceling: `CANCELING` task ids, in the DB's order.
        seen_for: Seconds tctl has seen each non-terminal task (`first_seen`).
        jobs: Each task's Job, by task id, in list order.
        pods: Each task's Pods, by task id, in list order.
        now: The wall-clock time read after the lists.
    """

    non_terminal: list[str]
    canceling: list[str]
    seen_for: dict[str, float]
    jobs: dict[str, Mapping[str, Any]]
    pods: dict[str, list[Mapping[str, Any]]]
    now: datetime

    def tasks(self) -> list[TaskView]:
        """Every task the pass knows of: with a Pod, a Job, or in the DB."""
        task_ids = dict.fromkeys(
            [*self.pods, *self.jobs, *self.non_terminal, *self.canceling]
        )
        canceling = set(self.canceling)
        return [
            TaskView(
                task_id,
                canceling=task_id in canceling,
                seen_for=self.seen_for.get(task_id),
            )
            for task_id in task_ids
        ]


async def _reconcile_once(
    core_v1: CoreV1Api,
    batch_v1: BatchV1Api,
    pool: asyncpg.Pool,
    namespace: str,
    first_seen: dict[str, float],
    *,
    unschedulable_timeout: float | None = None,
    still_leader: Callable[[], bool] | None = None,
) -> None:
    """One pass over all non-terminal task rows, task Jobs and TaskPods.

    Gathers the inputs once (`_gather`), decides each task's actions
    (`reconcile.decide`) and applies them (`_apply`). A cancelled task's Job
    delete goes first, for every task: its Pods are stopped, and with the
    Job and Pod gone a later pass's orphan check finalises the task as
    CANCELED. The other actions follow, task by task. An error while
    applying one task's actions is logged and the pass goes on with the
    next task. `still_leader` is asked before each task's actions; once it
    says no, the pass stops.
    """
    snapshot = await _gather(core_v1, batch_v1, pool, namespace, first_seen)
    timeouts = Timeouts(
        pending=_PENDING_TIMEOUT_SECONDS,
        unschedulable=unschedulable_timeout,
        orphan_grace=_ORPHAN_GRACE_SECONDS,
    )
    plans = {
        task.task_id: decide(
            task,
            snapshot.jobs.get(task.task_id),
            snapshot.pods.get(task.task_id, []),
            snapshot.now,
            timeouts,
        )
        for task in snapshot.tasks()
    }

    steps = [
        (task_id, [a for a in plans[task_id] if isinstance(a, DeleteJob) and a.retry])
        for task_id in snapshot.canceling
    ] + [
        (task_id, [a for a in actions if not (isinstance(a, DeleteJob) and a.retry)])
        for task_id, actions in plans.items()
    ]
    for task_id, actions in steps:
        if not actions:
            continue
        if still_leader is not None and not still_leader():
            logger.warning("tctl: lease no longer held; stopping the pass")
            return
        try:
            await _apply(core_v1, batch_v1, pool, namespace, task_id, actions)
        except Exception:
            # One task's database or Kubernetes error must not stop the
            # others; its actions are decided again on the next pass.
            logger.exception(
                "tctl: applying the actions of task=%s raised; going on", task_id
            )


async def _gather(
    core_v1: CoreV1Api,
    batch_v1: BatchV1Api,
    pool: asyncpg.Pool,
    namespace: str,
    first_seen: dict[str, float],
) -> _Snapshot:
    """Read the task rows, then the task Jobs and TaskPods.

    The task rows are read first, so every task considered for the orphan
    check existed before the Jobs and Pods were listed: a slow pass can't
    mistake a task created meanwhile for one without a Pod. `first_seen`
    maps each non-terminal task to the monotonic time tctl first read it;
    it is the pass's memory between passes, updated here.
    """
    async with pool.acquire() as conn:
        non_terminal = await state_db.list_non_terminal_task_ids(
            cast("asyncpg.Connection", conn), older_than_seconds=0
        )
        canceling = await state_db.list_canceling_task_ids(
            cast("asyncpg.Connection", conn)
        )
    observed = time.monotonic()
    for task_id in first_seen.keys() - set(non_terminal):
        del first_seen[task_id]
    for task_id in non_terminal:
        first_seen.setdefault(task_id, observed)

    job_items = await asyncio.to_thread(
        _list_all, batch_v1.list_namespaced_job, namespace
    )
    pod_items = await asyncio.to_thread(
        _list_all, core_v1.list_namespaced_pod, namespace
    )

    pods: dict[str, list[Mapping[str, Any]]] = {}
    for pod in pod_items:
        pod_dict = pod.to_dict() if hasattr(pod, "to_dict") else dict(pod)
        task_id = _task_id_from_pod(pod_dict)
        if task_id is not None:
            pods.setdefault(task_id, []).append(pod_dict)

    return _Snapshot(
        non_terminal=list(non_terminal),
        canceling=list(canceling),
        seen_for={task_id: observed - first_seen[task_id] for task_id in non_terminal},
        jobs=_jobs_by_task(job_items),
        pods=pods,
        now=datetime.now(UTC),
    )


def _list_all(list_page: Callable[..., Any], namespace: str) -> list[Any]:
    """Every task object of one list call, page by page.

    A continue token the API server no longer has (410 Gone, after its
    etcd compaction) restarts the list from the first page, up to
    `_LIST_RESTARTS` times. Any other error, or a timeout, is raised: the
    pass then acts on nothing rather than on part of a list, where a task
    on an unread page would look as if it had no Job or Pod.
    """
    for restart in range(_LIST_RESTARTS + 1):
        items: list[Any] = []
        token: str | None = None
        try:
            while True:
                page = list_page(
                    namespace=namespace,
                    label_selector=_TASK_LABEL,
                    limit=_LIST_PAGE_SIZE,
                    _continue=token,
                    _request_timeout=_REQUEST_TIMEOUT_SECONDS,
                )
                items.extend(page.items)
                token = getattr(getattr(page, "metadata", None), "_continue", None)
                if not token:
                    return items
        except ApiException as exc:
            if exc.status != HTTPStatus.GONE or token is None:
                raise
            if restart == _LIST_RESTARTS:
                raise
            logger.info("tctl: list continue token expired; listing again")
    msg = "unreachable"
    raise AssertionError(msg)


def _jobs_by_task(jobs: list[Any]) -> dict[str, Mapping[str, Any]]:
    """Map each task id to its Job, from a Job list's items."""
    by_task: dict[str, Mapping[str, Any]] = {}
    for job in jobs:
        job_dict = job.to_dict() if hasattr(job, "to_dict") else dict(job)
        task_id = _task_id_from_pod(job_dict)
        if task_id is not None:
            by_task[task_id] = job_dict
    return by_task


async def _apply(
    core_v1: CoreV1Api,
    batch_v1: BatchV1Api,
    pool: asyncpg.Pool,
    namespace: str,
    task_id: str,
    actions: Sequence[Action],
) -> None:
    """Apply one task's actions in order.

    A `DeleteJob(retry=False)` runs only if the `WriteTerminal` before it
    finalised the task.
    """
    wrote = False
    for action in actions:
        if isinstance(action, WriteTerminal):
            pod = action.backfill_from_pod
            wrote = await _apply_terminal(
                pool,
                core_v1=core_v1 if pod is not None else None,
                task_id=task_id,
                pod=pod,
                proposed=action.state,
                reason=action.reason,
                system_logs=list(action.system_logs),
                source=action.source,
            )
        elif action.retry or wrote:
            await _delete_job(batch_v1, namespace, task_id)


async def _apply_terminal(
    pool: asyncpg.Pool,
    *,
    core_v1: CoreV1Api | None,
    task_id: str,
    pod: Mapping[str, Any] | None,
    proposed: TesState,
    reason: str | None,
    system_logs: list[str],
    source: str,
) -> bool:
    """Single point that writes terminal state and the surrounding logs.

    No-op when the task is already terminal in the DB. On a successful
    write, backfill executor_logs from the pod's container statuses (so
    a trec that got SIGTERMed mid-stream doesn't leave a task with a
    terminal state but missing per-executor rows) and append the
    system_logs strings describing the failure mode.

    The state, the executor_logs rows and the system_logs lines are
    written in one transaction: if any of it fails, none of it lands and
    the next pass tries again, instead of finding the task terminal and
    its diagnostics lost. The executor logs are read from Kubernetes
    before the transaction, so no database connection is held across a
    Kubernetes call.

    Returns True iff this call finalised the task. A write that doesn't
    come from a finished Pod or Job is then followed by a delete of the
    task's Job (`DeleteJob(retry=False)`), so that nothing of the task
    keeps running.
    """
    backfill = (
        await _read_executor_logs(pool, core_v1, task_id, pod)
        if pod is not None and core_v1 is not None
        else None
    )
    async with pool.acquire() as conn:
        c = cast("asyncpg.Connection", conn)
        async with c.transaction():
            result = await state_db.write_terminal_state(
                c, task_id, proposed, reason=reason
            )
            if result is state_db.TerminalWriteResult.NO_OP:
                return False

            if backfill is not None:
                await _write_executor_logs(c, task_id, backfill)

            # On the CANCELING precedence path, the proposed terminal was
            # rewritten to CANCELED. Make the system log honest about that.
            if result is state_db.TerminalWriteResult.CANCELED_INSTEAD:
                await state_db.append_system_log(c, task_id, "task cancelled by client")
            else:
                for line in system_logs:
                    await state_db.append_system_log(c, task_id, line)

    logger.info(
        "tctl: %s reconciled task=%s as %s (write=%s, reason=%s)",
        source,
        task_id,
        proposed.value,
        result.value,
        reason,
    )
    return True


async def _delete_job(batch_v1: BatchV1Api, namespace: str, task_id: str) -> None:
    """Delete a task's Job; its Pods and PVC go with it.

    Idempotent: a Job that is already gone is fine. Any other failure is
    logged, not raised, so one Job can't stop the pass. A `CANCELING`
    task's delete is tried again on the next pass; after a terminal write
    it is not: the Job's `activeDeadlineSeconds`, if set, is the backstop.
    """
    # The stubs don't list the client's `_request_timeout`.
    api: Any = batch_v1
    try:
        await asyncio.to_thread(
            api.delete_namespaced_job,
            name=job_name_for(task_id),
            namespace=namespace,
            propagation_policy="Background",
            _request_timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except ApiException as exc:
        if exc.status != HTTPStatus.NOT_FOUND:
            logger.warning(
                "tctl: could not delete the Job of task=%s (%s %s)",
                task_id,
                exc.status,
                exc.reason,
            )
        return
    logger.info("tctl: deleted the Job of task=%s", task_id)


@dataclass(frozen=True)
class _ExecutorLog:
    """One `executor_logs` row tctl backfills."""

    ordinal: int
    exit_code: int
    start_time: datetime | None
    end_time: datetime | None
    stdout: str | None
    stderr: str | None


async def _read_executor_logs(
    pool: asyncpg.Pool,
    core_v1: CoreV1Api,
    task_id: str,
    pod: Mapping[str, Any],
) -> list[_ExecutorLog]:
    """The executor_logs rows trec didn't get to, read from the Pod.

    Walks `initContainerStatuses` for containers named `exec-N`; ignores
    trec/tif/tof. Executors trec already recorded are skipped, so their
    logs aren't read again; for the others the tail of the container log
    is the `stdout`, or the `stderr` when the executor writes its stdout
    to a file. tctl doesn't mount task volumes, so such files aren't read.
    The database connection that reads the recorded ordinals is given back
    before the logs are read.
    """
    metadata = pod.get("metadata") or {}
    pod_name = metadata.get("name") or ""
    namespace = metadata.get("namespace") or ""
    streams = streams_from_pod(pod)
    async with pool.acquire() as conn:
        recorded = await state_db.recorded_executor_ordinals(
            cast("asyncpg.Connection", conn), task_id
        )
    statuses = (
        (pod.get("status") or {}).get("init_container_statuses")
        or (pod.get("status") or {}).get("initContainerStatuses")
        or []
    )
    rows: list[_ExecutorLog] = []
    for status in statuses:
        name = status.get("name") or ""
        if not name.startswith("exec-"):
            continue
        try:
            ordinal = int(name.removeprefix("exec-"))
        except ValueError:
            continue
        terminated = (status.get("state") or {}).get("terminated") or (
            status.get("last_state") or status.get("lastState") or {}
        ).get("terminated")
        if not terminated:
            continue
        exit_code = ignore_error.recorded_exit_code(terminated)
        if exit_code is None or ordinal in recorded:
            continue
        executor_streams = streams.get(ordinal)
        stdout, stderr = await read_executor_streams(
            core_v1,
            pod_name,
            namespace,
            ordinal,
            executor_streams.without_files() if executor_streams else None,
        )
        rows.append(
            _ExecutorLog(
                ordinal=ordinal,
                exit_code=int(exit_code),
                start_time=_parse_kubelet_ts(
                    terminated.get("started_at") or terminated.get("startedAt")
                ),
                end_time=_parse_kubelet_ts(
                    terminated.get("finished_at") or terminated.get("finishedAt")
                ),
                stdout=stdout,
                stderr=stderr,
            )
        )
    return rows


async def _write_executor_logs(
    conn: asyncpg.Connection, task_id: str, rows: Sequence[_ExecutorLog]
) -> None:
    """Write the rows `_read_executor_logs` read.

    Idempotent: `append_executor_log` is INSERT ON CONFLICT DO NOTHING
    keyed on `(task_log_id, ordinal)`, so a row trec wrote meanwhile wins.
    """
    for row in rows:
        await state_db.append_executor_log(
            conn,
            task_id,
            ordinal=row.ordinal,
            exit_code=row.exit_code,
            start_time=row.start_time,
            end_time=row.end_time,
            stdout=row.stdout,
            stderr=row.stderr,
        )


def _task_id_from_pod(pod: Mapping[str, Any]) -> str | None:
    """Return the task UUID this Pod represents, if labelled."""
    metadata = pod.get("metadata") or {}
    labels = metadata.get("labels") or {}
    return labels.get(_TASK_LABEL)


async def _wait_or_cancel(cancelled: asyncio.Event, seconds: float) -> None:
    """Sleep for `seconds`, returning early if `cancelled` fires."""
    try:
        await asyncio.wait_for(cancelled.wait(), timeout=seconds)
    except TimeoutError:
        return


def _install_signal_handlers() -> asyncio.Event:
    """Wire SIGTERM/SIGINT to set an asyncio Event the reconcile loop polls."""
    cancelled = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, cancelled.set)
    return cancelled
