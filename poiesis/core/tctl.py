"""Task Controller — single writer for terminal task state.

TCtl is the leader-elected cluster-wide controller. Every TES task's
terminal write goes through this module — trec deliberately stays out of
that responsibility so there's exactly one place to debug a task stuck
in a non-terminal state.

The control loop is a polling reconciler: every `_RECONCILE_INTERVAL_SECONDS`
the leader lists every non-terminal task in the DB, then every task Job and
TaskPod, joins them, and writes terminal state for any combination that
warrants it. No watch, no event stream, no race between two writers.

Cases the reconciler covers:

    * Pod reached `Succeeded` or `Failed` → write the matching terminal,
    backfill any executor_logs trec didn't get to before its own
    sidecar SIGTERM (with the tail of each executor's log as stdout),
    append a system_logs entry describing the failure.
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

Leader election uses `coordination.k8s.io/v1` Leases (see `core/leases.py`).
The Lease lives in the namespace tctl runs in (the release namespace), which
is not the TaskPod namespace when the two are split.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import socket
import time
import uuid
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, cast

import asyncpg
from kubernetes.client import BatchV1Api, CoordinationV1Api, CoreV1Api
from kubernetes.client.exceptions import ApiException

if TYPE_CHECKING:
    from collections.abc import Mapping

from poiesis.api.tes.models import TesState
from poiesis.core import executor_shell, ignore_error
from poiesis.core.executor_logs import read_executor_streams, streams_from_pod
from poiesis.core.leases import try_acquire_or_renew
from poiesis.core.pod_status import (
    created_at,
    extract_job_failure,
    extract_pending_failure_reason,
    extract_terminal_reason,
    extract_unschedulable_message,
    filer_failure_log,
    is_lifecycle_stop,
    pod_terminated_terminal,
)
from poiesis.core.taskpod import job_name_for
from poiesis.db import state as state_db

logger = logging.getLogger(__name__)

_TASK_LABEL = "poiesis.io/task"
_LEASE_NAME = "poiesis-tctl-leader"
_LEASE_DURATION_SECONDS = 30
_LEASE_RENEW_INTERVAL_SECONDS = 10
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


async def run(
    namespace: str,
    dsn: str,
    *,
    lease_namespace: str | None = None,
    identity: str | None = None,
    unschedulable_timeout: float | None = None,
) -> int:
    """Run the TCtl reconciliation loop until SIGTERM/SIGINT.

    `namespace` is where the TaskPods are; `lease_namespace` is where the
    leader Lease is kept (default: `namespace`). `unschedulable_timeout`
    is how many seconds a task may wait for its Pod to be created and
    scheduled; None waits until the Job's time limit. Holds the Lease while
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
                unschedulable_timeout,
            )
    finally:
        await pool.close()
    return 0


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


async def _reconcile_while_leader(  # noqa: PLR0913 (one pass's inputs and the Lease)
    core_v1: CoreV1Api,
    batch_v1: BatchV1Api,
    coord_v1: CoordinationV1Api,
    pool: asyncpg.Pool,
    namespace: str,
    lease_namespace: str,
    identity: str,
    cancelled: asyncio.Event,
    unschedulable_timeout: float | None = None,
) -> None:
    """Reconcile every `_RECONCILE_INTERVAL_SECONDS` until lease is lost."""
    # Per leadership term: a new leader observes for a full grace period
    # before it calls any task an orphan.
    first_seen: dict[str, float] = {}
    while not cancelled.is_set():
        renewed = await _hold_lease(coord_v1, lease_namespace, identity)
        if not renewed:
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
            )
        except Exception:
            logger.exception("tctl: reconcile tick raised; will retry next interval")
        await _wait_or_cancel(cancelled, _RECONCILE_INTERVAL_SECONDS)


async def _reconcile_once(
    core_v1: CoreV1Api,
    batch_v1: BatchV1Api,
    pool: asyncpg.Pool,
    namespace: str,
    first_seen: dict[str, float],
    *,
    unschedulable_timeout: float | None = None,
) -> None:
    """One pass over all non-terminal task rows, task Jobs and TaskPods.

    The task rows are read first, so every task considered for the orphan
    check existed before the Jobs and Pods were listed: a slow pass can't
    mistake a task created meanwhile for one without a Pod. `first_seen`
    maps each non-terminal task to the monotonic time tctl first read it;
    it is this function's memory between passes.
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

    job_list = await asyncio.to_thread(
        batch_v1.list_namespaced_job,
        namespace=namespace,
        label_selector=_TASK_LABEL,
    )
    pod_list = await asyncio.to_thread(
        core_v1.list_namespaced_pod,
        namespace=namespace,
        label_selector=_TASK_LABEL,
    )

    jobs = _jobs_by_task(job_list.items)

    # A cancelled task's Job goes first: its Pods are stopped, and with the
    # Job and Pod gone the orphan check below finalises the task as CANCELED.
    for task_id in canceling:
        if task_id in jobs and not _being_deleted(jobs[task_id]):
            await _delete_job(batch_v1, namespace, task_id)

    now = datetime.now(UTC)
    seen_task_ids: set[str] = set()
    for pod in pod_list.items:
        pod_dict = pod.to_dict() if hasattr(pod, "to_dict") else dict(pod)
        task_id = _task_id_from_pod(pod_dict)
        if task_id is None:
            continue
        seen_task_ids.add(task_id)
        await _reconcile_pod(
            core_v1,
            batch_v1,
            pool,
            pod_dict,
            task_id,
            now,
            unschedulable_timeout=unschedulable_timeout,
        )

    for task_id, job_dict in jobs.items():
        if task_id in seen_task_ids:
            continue
        if await _reconcile_podless_job(
            batch_v1,
            pool,
            namespace,
            job_dict,
            task_id,
            now,
            unschedulable_timeout=unschedulable_timeout,
        ):
            seen_task_ids.add(task_id)

    await _reconcile_orphans(
        batch_v1,
        pool,
        namespace,
        [
            task_id
            for task_id in non_terminal
            if task_id not in seen_task_ids
            and observed - first_seen[task_id] >= _ORPHAN_GRACE_SECONDS
        ],
    )


def _jobs_by_task(jobs: list[Any]) -> dict[str, Mapping[str, Any]]:
    """Map each task id to its Job, from a Job list's items."""
    by_task: dict[str, Mapping[str, Any]] = {}
    for job in jobs:
        job_dict = job.to_dict() if hasattr(job, "to_dict") else dict(job)
        task_id = _task_id_from_pod(job_dict)
        if task_id is not None:
            by_task[task_id] = job_dict
    return by_task


async def _reconcile_pod(
    core_v1: CoreV1Api,
    batch_v1: BatchV1Api,
    pool: asyncpg.Pool,
    pod: Mapping[str, Any],
    task_id: str,
    now: datetime,
    *,
    unschedulable_timeout: float | None = None,
) -> None:
    """Apply terminal state for one pod when its phase warrants it."""
    phase = ((pod.get("status") or {}).get("phase") or "").lower()

    if phase in {"succeeded", "failed"}:
        pod_reason = extract_terminal_reason(pod)
        proposed, reason = pod_terminated_terminal(pod_reason)
        system_logs = _terminal_system_logs(pod, proposed)
        await _apply_terminal(
            pool,
            core_v1=core_v1,
            task_id=task_id,
            pod=pod,
            proposed=proposed,
            reason=reason,
            system_logs=system_logs,
            source="pod-terminal",
        )
        return

    timeout = (
        _pending_timeout(pod, now, unschedulable_timeout)
        if phase == "pending"
        else None
    )
    if timeout is not None:
        pending_reason = extract_pending_failure_reason(pod)
        namespace = (pod.get("metadata") or {}).get("namespace")
        wrote = await _apply_terminal(
            pool,
            core_v1=core_v1,
            task_id=task_id,
            pod=pod,
            proposed=TesState.SYSTEM_ERROR,
            reason=pending_reason,
            system_logs=_pending_system_logs(pod, timeout, pending_reason),
            source=timeout.replace(" ", "-"),
        )
        if wrote and namespace:
            await _delete_job(batch_v1, namespace, task_id)


async def _reconcile_podless_job(
    batch_v1: BatchV1Api,
    pool: asyncpg.Pool,
    namespace: str,
    job: Mapping[str, Any],
    task_id: str,
    now: datetime,
    *,
    unschedulable_timeout: float | None = None,
) -> bool:
    """Reconcile a task Job that has no Pod; True iff the Job accounts for it.

    A Job that is being deleted or has completed stands for nothing any
    more: False leaves its task to the orphan check. A failed Job (its
    time limit ran out and the Job controller removed the Pod) ends the
    task with its own reason. Any other Job is alive, and its task waits
    for a Pod: a ResourceQuota or an admission webhook may hold the Pod
    back until capacity frees up. Only `unschedulable_timeout`, when set,
    ends that wait.
    """
    if _being_deleted(job):
        return False

    finished, failure = extract_job_failure(job)
    if failure is not None:
        await _apply_terminal(
            pool,
            core_v1=None,
            task_id=task_id,
            pod=None,
            proposed=TesState.SYSTEM_ERROR,
            reason=f"Job failed: {failure}",
            system_logs=[f"job failed without a pod: {failure}"],
            source="job-failed",
        )
        return True
    if finished:
        return False

    created = created_at(job)
    if (
        unschedulable_timeout is not None
        and created is not None
        and (now - created).total_seconds() > unschedulable_timeout
    ):
        wrote = await _apply_terminal(
            pool,
            core_v1=None,
            task_id=task_id,
            pod=None,
            proposed=TesState.SYSTEM_ERROR,
            reason="Job created no Pod",
            system_logs=[
                "unschedulable timeout: the Job created no Pod "
                "(see the Job's events: quota, admission)"
            ],
            source="job-no-pod",
        )
        if wrote:
            await _delete_job(batch_v1, namespace, task_id)
    return True


async def _reconcile_orphans(
    batch_v1: BatchV1Api,
    pool: asyncpg.Pool,
    namespace: str,
    orphans: list[str],
) -> None:
    """Write SYSTEM_ERROR for non-terminal tasks whose pod has disappeared.

    `orphans` are the tasks with neither a live Job nor a Pod for the whole
    grace period. The CANCELING precedence rule on the writer turns the
    proposal into CANCELED for cancelled tasks; this path covers the rest
    (manual pod delete, node loss, etc.).
    """
    for task_id in orphans:
        wrote = await _apply_terminal(
            pool,
            core_v1=None,
            task_id=task_id,
            pod=None,
            proposed=TesState.SYSTEM_ERROR,
            reason="Pod disappeared before reaching terminal phase",
            system_logs=["pod disappeared before reaching terminal phase"],
            source="orphan",
        )
        if wrote:
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

    Returns True iff this call finalised the task. A caller whose write
    doesn't come from a finished Pod or Job then deletes the task's Job
    (`_delete_job`), so that nothing of the task keeps running.
    """
    async with pool.acquire() as conn:
        c = cast("asyncpg.Connection", conn)
        result = await state_db.write_terminal_state(
            c, task_id, proposed, reason=reason
        )
        if result is state_db.TerminalWriteResult.NO_OP:
            return False

        if pod is not None and core_v1 is not None:
            await _backfill_executor_logs(c, core_v1, task_id, pod)

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
    try:
        await asyncio.to_thread(
            batch_v1.delete_namespaced_job,
            name=job_name_for(task_id),
            namespace=namespace,
            propagation_policy="Background",
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


def _being_deleted(obj: Mapping[str, Any]) -> bool:
    """True iff the object carries a `deletionTimestamp`."""
    metadata = obj.get("metadata") or {}
    return bool(metadata.get("deletion_timestamp") or metadata.get("deletionTimestamp"))


async def _backfill_executor_logs(
    conn: asyncpg.Connection,
    core_v1: CoreV1Api,
    task_id: str,
    pod: Mapping[str, Any],
) -> None:
    """Write any executor_logs rows trec didn't get to.

    Idempotent: `append_executor_log` is INSERT ON CONFLICT DO NOTHING
    keyed on `(task_log_id, ordinal)`. Walks `initContainerStatuses` for
    containers named `exec-N`; ignores trec/tif/tof. Executors trec
    already recorded are skipped, so their logs aren't read again; for
    the others the tail of the container log is stored as `stdout`, or as
    `stderr` when the executor writes its stdout to a file. tctl doesn't
    mount task volumes, so such files aren't read.
    """
    metadata = pod.get("metadata") or {}
    pod_name = metadata.get("name") or ""
    namespace = metadata.get("namespace") or ""
    streams = streams_from_pod(pod)
    recorded = await state_db.recorded_executor_ordinals(conn, task_id)
    statuses = (
        (pod.get("status") or {}).get("init_container_statuses")
        or (pod.get("status") or {}).get("initContainerStatuses")
        or []
    )
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
        await state_db.append_executor_log(
            conn,
            task_id,
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


def _terminal_system_logs(
    pod: Mapping[str, Any],
    proposed: TesState,
) -> list[str]:
    """Emit human-readable diagnostics for non-COMPLETE terminal writes.

    Walks every container status and surfaces termination reasons that
    operators care about: OOMKill, non-zero exit, specific waiting
    reasons. trec and `ack` stopped as the Pod ends are left out
    (`is_lifecycle_stop`). Returns an empty list for COMPLETE (happy path
    needs no system_logs noise).
    """
    if proposed is TesState.COMPLETE:
        return []

    lines: list[str] = []
    wrapped = executor_shell.wrapped_executors(pod)
    status = pod.get("status") or {}
    for key in (
        "init_container_statuses",
        "initContainerStatuses",
        "container_statuses",
        "containerStatuses",
    ):
        for entry in status.get(key) or []:
            name = entry.get("name") or "?"
            terminated = (entry.get("state") or {}).get("terminated")
            if not terminated or is_lifecycle_stop(status, name, terminated):
                continue
            reason = terminated.get("reason")
            exit_code = terminated.get("exit_code") or terminated.get("exitCode")
            shell_failure = (
                executor_shell.start_failure_log(name, terminated, wrapped[name])
                if name in wrapped
                else None
            )
            filer_failure = filer_failure_log(name, terminated)
            if reason == "OOMKilled":
                lines.append(f"container {name} OOMKilled")
            elif shell_failure is not None:
                lines.append(shell_failure)
            elif filer_failure is not None:
                lines.append(filer_failure)
            elif exit_code not in (None, 0):
                lines.append(f"container {name} exited with code {exit_code}")
    if not lines:
        lines.append(f"task ended in {proposed.value}")
    return lines


def _pending_system_logs(
    pod: Mapping[str, Any], timeout: str, reason: str
) -> list[str]:
    """The system_logs of a timeout in Pending: the reason, then the scheduler's.

    `timeout` names which timeout ran out (`_pending_timeout`); `reason` is
    a stable classification. The scheduler's own message says which nodes
    it tried and why none fits, so it is kept as a second line.
    """
    lines = [f"{timeout}: {reason}"]
    message = extract_unschedulable_message(pod)
    if message:
        lines.append(f"scheduler: {message}")
    return lines


def _parse_kubelet_ts(value: Any) -> datetime | None:
    """Best-effort parse of a kubelet ISO-8601 timestamp."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _pending_timeout(
    pod: Mapping[str, Any], now: datetime, unschedulable_timeout: float | None
) -> str | None:
    """Which timeout a Pending `pod` has run out of, if any.

    A Pod bound to a node has a `status.startTime`; after
    `_PENDING_TIMEOUT_SECONDS` from it, "pending timeout". A Pod the
    scheduler hasn't placed (no node with room, unbindable PVC, taints) has
    none: on a busy cluster that is queueing, not a fault. It is timed from
    `metadata.creationTimestamp` against `unschedulable_timeout`, and
    never when that is None: "unschedulable timeout".
    """
    status = pod.get("status") or {}
    started = _parse_kubelet_ts(status.get("startTime") or status.get("start_time"))
    if started is not None:
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if (now - started).total_seconds() > _PENDING_TIMEOUT_SECONDS:
            return "pending timeout"
        return None
    if unschedulable_timeout is None:
        return None
    created = created_at(pod)
    if created is not None and (now - created).total_seconds() > unschedulable_timeout:
        return "unschedulable timeout"
    return None


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
