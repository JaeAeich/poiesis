"""Task Controller — single writer for terminal task state.

TCtl is the leader-elected cluster-wide controller. Every TES task's
terminal write goes through this module — trec deliberately stays out of
that responsibility so there's exactly one place to debug a task stuck
in a non-terminal state.

The control loop is a polling reconciler: every `_RECONCILE_INTERVAL_SECONDS`
the leader lists every TaskPod and every non-terminal task in the DB,
joins them, and writes terminal state for any combination that warrants
it. No watch, no event stream, no race between two writers.

Cases the reconciler covers:

    * Pod reached `Succeeded` or `Failed` → write the matching terminal,
    backfill any executor_logs trec didn't get to before its own
    sidecar SIGTERM, append a system_logs entry describing the failure.
    * Pod stuck in `Pending` past `_PENDING_TIMEOUT_SECONDS` → SYSTEM_ERROR
    with the kubelet's pending reason in system_logs.
    * Task non-terminal in DB but no matching live pod (and older than
    `_ORPHAN_GRACE_SECONDS` so we don't race with brand-new tasks
    whose pod hasn't been created yet) → SYSTEM_ERROR. The writer's
    CANCELING-precedence rule turns this into CANCELED for cancelled
    tasks; the orphan path covers true pod-gone-without-notice cases
    (manual kubectl delete, node loss before the pod was rescheduled).

The writer (`state.write_terminal_state`) is idempotent and
CANCELING-aware, so re-running the loop against an already-finalised
task is a no-op.

Leader election uses `coordination.k8s.io/v1` Leases (see `core/leases.py`).
"""

from __future__ import annotations

import asyncio
import logging
import signal
import socket
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import asyncpg
from kubernetes.client import CoordinationV1Api, CoreV1Api

if TYPE_CHECKING:
    from collections.abc import Mapping

from poiesis.api.tes.models import TesState
from poiesis.core.leases import try_acquire_or_renew
from poiesis.core.pod_status import (
    extract_pending_failure_reason,
    extract_terminal_reason,
    pod_terminated_terminal,
)
from poiesis.db import state as state_db

logger = logging.getLogger(__name__)

_TASK_LABEL = "poiesis.io/task"
_LEASE_NAME = "poiesis-tctl-leader"
_LEASE_DURATION_SECONDS = 30
_LEASE_RENEW_INTERVAL_SECONDS = 10
#: How often the reconciler walks the world.
_RECONCILE_INTERVAL_SECONDS = 5
#: How long a TaskPod may sit in Pending before the controller times it out.
#: Covers `ImagePullBackOff`, unbindable PVCs, no schedulable node, etc.
_PENDING_TIMEOUT_SECONDS = 300
#: Grace before treating a non-terminal task with no live pod as orphaned.
#: Covers the window between API CreateTask and the kubelet observing the Pod.
_ORPHAN_GRACE_SECONDS = 30


async def run(
    namespace: str,
    dsn: str,
    *,
    identity: str | None = None,
) -> int:
    """Run the TCtl reconciliation loop until SIGTERM/SIGINT.

    Holds the Lease while reconciling; gives it up cleanly on signal.
    Returns 0 on clean shutdown.
    """
    identity = identity or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    cancelled = _install_signal_handlers()

    coord_v1 = CoordinationV1Api()
    core_v1 = CoreV1Api()
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    try:
        while not cancelled.is_set():
            acquired = await try_acquire_or_renew(
                coord_v1,
                name=_LEASE_NAME,
                namespace=namespace,
                identity=identity,
                lease_duration_seconds=_LEASE_DURATION_SECONDS,
            )
            if not acquired:
                logger.debug("tctl: not leader; sleeping")
                await _wait_or_cancel(cancelled, _LEASE_RENEW_INTERVAL_SECONDS)
                continue
            logger.info("tctl: acquired lease as %s", identity)
            await _reconcile_while_leader(
                core_v1, coord_v1, pool, namespace, identity, cancelled
            )
    finally:
        await pool.close()
    return 0


async def _reconcile_while_leader(
    core_v1: CoreV1Api,
    coord_v1: CoordinationV1Api,
    pool: asyncpg.Pool,
    namespace: str,
    identity: str,
    cancelled: asyncio.Event,
) -> None:
    """Reconcile every `_RECONCILE_INTERVAL_SECONDS` until lease is lost."""
    while not cancelled.is_set():
        renewed = await try_acquire_or_renew(
            coord_v1,
            name=_LEASE_NAME,
            namespace=namespace,
            identity=identity,
            lease_duration_seconds=_LEASE_DURATION_SECONDS,
        )
        if not renewed:
            logger.warning("tctl: lost lease; standing down")
            return
        try:
            await _reconcile_once(core_v1, pool, namespace)
        except Exception:
            logger.exception("tctl: reconcile tick raised; will retry next interval")
        await _wait_or_cancel(cancelled, _RECONCILE_INTERVAL_SECONDS)


async def _reconcile_once(
    core_v1: CoreV1Api,
    pool: asyncpg.Pool,
    namespace: str,
) -> None:
    """One pass over all TaskPods + all non-terminal task rows."""
    pod_list = await asyncio.to_thread(
        core_v1.list_namespaced_pod,
        namespace=namespace,
        label_selector=_TASK_LABEL,
    )

    now = datetime.now(UTC)
    seen_task_ids: set[str] = set()
    for pod in pod_list.items:
        pod_dict = pod.to_dict() if hasattr(pod, "to_dict") else dict(pod)
        task_id = _task_id_from_pod(pod_dict)
        if task_id is None:
            continue
        seen_task_ids.add(task_id)
        await _reconcile_pod(pool, pod_dict, task_id, now)

    await _reconcile_orphans(pool, seen_task_ids)


async def _reconcile_pod(
    pool: asyncpg.Pool,
    pod: Mapping[str, Any],
    task_id: str,
    now: datetime,
) -> None:
    """Apply terminal state for one pod when its phase warrants it."""
    phase = ((pod.get("status") or {}).get("phase") or "").lower()

    if phase in {"succeeded", "failed"}:
        pod_reason = extract_terminal_reason(pod)
        proposed, reason = pod_terminated_terminal(pod_reason)
        system_logs = _terminal_system_logs(pod, proposed)
        await _apply_terminal(
            pool,
            task_id=task_id,
            pod=pod,
            proposed=proposed,
            reason=reason,
            system_logs=system_logs,
            source="pod-terminal",
        )
        return

    if phase == "pending" and _pending_too_long(pod, now):
        pending_reason = extract_pending_failure_reason(pod)
        await _apply_terminal(
            pool,
            task_id=task_id,
            pod=pod,
            proposed=TesState.SYSTEM_ERROR,
            reason=pending_reason,
            system_logs=[f"pending timeout: {pending_reason}"],
            source="pending-timeout",
        )


async def _reconcile_orphans(pool: asyncpg.Pool, seen_task_ids: set[str]) -> None:
    """Write SYSTEM_ERROR for non-terminal tasks whose pod has disappeared.

    The CANCELING precedence rule on the writer turns the proposal into
    CANCELED for cancelled tasks; this path covers the rest (manual pod
    delete, node loss, etc.).
    """
    async with pool.acquire() as conn:
        candidates = await state_db.list_non_terminal_task_ids(
            cast("asyncpg.Connection", conn),
            older_than_seconds=_ORPHAN_GRACE_SECONDS,
        )
    orphans = [tid for tid in candidates if tid not in seen_task_ids]
    for task_id in orphans:
        await _apply_terminal(
            pool,
            task_id=task_id,
            pod=None,
            proposed=TesState.SYSTEM_ERROR,
            reason="Pod disappeared before reaching terminal phase",
            system_logs=["pod disappeared before reaching terminal phase"],
            source="orphan",
        )


async def _apply_terminal(
    pool: asyncpg.Pool,
    *,
    task_id: str,
    pod: Mapping[str, Any] | None,
    proposed: TesState,
    reason: str | None,
    system_logs: list[str],
    source: str,
) -> None:
    """Single point that writes terminal state and the surrounding logs.

    No-op when the task is already terminal in the DB. On a successful
    write, backfill executor_logs from the pod's container statuses (so
    a trec that got SIGTERMed mid-stream doesn't leave a task with a
    terminal state but missing per-executor rows) and append the
    system_logs strings describing the failure mode.
    """
    async with pool.acquire() as conn:
        c = cast("asyncpg.Connection", conn)
        result = await state_db.write_terminal_state(
            c, task_id, proposed, reason=reason
        )
        if result is state_db.TerminalWriteResult.NO_OP:
            return

        if pod is not None:
            await _backfill_executor_logs(c, task_id, pod)

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


async def _backfill_executor_logs(
    conn: asyncpg.Connection,
    task_id: str,
    pod: Mapping[str, Any],
) -> None:
    """Write any executor_logs rows trec didn't get to.

    Idempotent: `append_executor_log` is INSERT ON CONFLICT DO NOTHING
    keyed on `(task_log_id, ordinal)`. Walks `initContainerStatuses` for
    containers named `exec-N`; ignores trec/tif/tof.
    """
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
        exit_code = terminated.get("exit_code")
        if exit_code is None:
            exit_code = terminated.get("exitCode")
        if exit_code is None:
            continue
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
        )


def _terminal_system_logs(
    pod: Mapping[str, Any],
    proposed: TesState,
) -> list[str]:
    """Emit human-readable diagnostics for non-COMPLETE terminal writes.

    Walks every container status and surfaces termination reasons that
    operators care about: OOMKill, non-zero exit, specific waiting
    reasons. Returns an empty list for COMPLETE (happy path needs no
    system_logs noise).
    """
    if proposed is TesState.COMPLETE:
        return []

    lines: list[str] = []
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
            if not terminated:
                continue
            reason = terminated.get("reason")
            exit_code = terminated.get("exit_code") or terminated.get("exitCode")
            if reason == "OOMKilled":
                lines.append(f"container {name} OOMKilled")
            elif exit_code not in (None, 0):
                lines.append(f"container {name} exited with code {exit_code}")
    if not lines:
        lines.append(f"task ended in {proposed.value}")
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


def _pending_too_long(pod: Mapping[str, Any], now: datetime) -> bool:
    """True iff `pod` has been Pending longer than the configured threshold."""
    status = pod.get("status") or {}
    start_time = status.get("startTime") or status.get("start_time")
    if start_time is None:
        return False
    if isinstance(start_time, datetime):
        start = start_time
    else:
        try:
            start = datetime.fromisoformat(str(start_time))
        except ValueError:
            return False
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    return (now - start).total_seconds() > _PENDING_TIMEOUT_SECONDS


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
