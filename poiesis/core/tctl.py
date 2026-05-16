"""Task Controller — backstop reconciler for un-self-reportable failures.

TCtl is the leader-elected global controller that watches TaskPods cluster-wide
(scoped here to a namespace for the dev RBAC story) and writes terminal state
for failures the in-Pod recorder cannot self-report: OOMKill before TRec
started, eviction, node loss, image-pull failure, PVC bind failure,
`activeDeadlineSeconds` exceeded.

Two race-correct guarantees from the writer:

    * `state.write_terminal_state` is conditional on the row being
        non-terminal, so whoever writes first (TCtl or TRec) wins.
    * The CANCELING precedence rule means a SIGTERMed pod observed
        terminating after a `CancelTask` still records as CANCELED.

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
import kubernetes
from kubernetes.client import CoordinationV1Api, CoreV1Api

if TYPE_CHECKING:
    from collections.abc import Mapping

from poiesis.api.tes.models import TesState
from poiesis.core.leases import try_acquire_or_renew
from poiesis.core.pod_status import (
    ACK_NAME,
    PodTerminationReason,
    pod_terminated_terminal,
)
from poiesis.db import state as state_db

logger = logging.getLogger(__name__)

_TASK_LABEL = "poiesis.io/task"
_LEASE_NAME = "poiesis-tctl-leader"
_LEASE_DURATION_SECONDS = 30
_LEASE_RENEW_INTERVAL_SECONDS = 10
_WATCH_STREAM_TIMEOUT_SECONDS = 300
#: How long a TaskPod may sit in Pending before the controller times it out.
#: Covers `ImagePullBackOff`, unbindable PVCs, no schedulable node, etc.
_PENDING_TIMEOUT_SECONDS = 300


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
    """Run the Pod informer + lease renewal until lease is lost or signalled."""
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    producer = loop.run_in_executor(None, _stream_pods, core_v1, namespace, queue, loop)
    try:
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
                item = await asyncio.wait_for(
                    queue.get(), timeout=_LEASE_RENEW_INTERVAL_SECONDS
                )
            except TimeoutError:
                # No watch event this tick — sweep for stuck-Pending pods so a
                # task that can't be scheduled (bad image, unbindable pvc) is
                # eventually moved out of QUEUED/INITIALIZING.
                await _sweep_pending(core_v1, pool, namespace)
                continue
            if item is None:
                logger.warning("tctl: pod stream ended; restarting")
                return
            event_type, pod = item
            await _handle_pod(pool, event_type, pod)
    finally:
        producer.cancel()


def _stream_pods(
    core_v1: CoreV1Api,
    namespace: str,
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None],
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Run in a worker thread: stream Pod events onto the async queue.

    Each enqueued item is `(event_type, pod_dict)`. A None sentinel is
    pushed when the stream ends or errors.
    """
    try:
        while True:
            # `kubernetes-stubs` does not export the `watch` submodule.
            w = kubernetes.watch.Watch()  # ty: ignore[unresolved-attribute]
            for event in w.stream(
                core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=_TASK_LABEL,
                timeout_seconds=_WATCH_STREAM_TIMEOUT_SECONDS,
            ):
                pod = event["object"]
                event_type = event.get("type", "MODIFIED")
                pod_dict = pod.to_dict() if hasattr(pod, "to_dict") else dict(pod)
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    (event_type, pod_dict),
                )
    except Exception:
        logger.exception("tctl: pod watch stream failed")
        loop.call_soon_threadsafe(queue.put_nowait, None)


async def _handle_pod(
    pool: asyncpg.Pool,
    event_type: str,
    pod: dict[str, Any],
) -> None:
    """Inspect a Pod event and write terminal state if reconciliation is needed."""
    task_id = _task_id_from_pod(pod)
    if task_id is None:
        return

    phase = ((pod.get("status") or {}).get("phase") or "").lower()

    # DELETED: pod is gone. If the task is still non-terminal, we have to
    # synthesise a terminal write — kubelet won't ever publish Succeeded/Failed
    # for a hard-deleted pod (the common path after CancelTask).
    if event_type == "DELETED":
        proposed = TesState.SYSTEM_ERROR
        reason = "Pod deleted before reaching terminal phase"
        # CANCELING precedence rule on the writer handles the cancel case.
        async with pool.acquire() as conn:
            result = await state_db.write_terminal_state(
                cast("asyncpg.Connection", conn), task_id, proposed, reason=reason
            )
        if result is not state_db.TerminalWriteResult.NO_OP:
            logger.info(
                "tctl: pod-deleted reconciled task=%s (write=%s)",
                task_id,
                result.value,
            )
        return

    if phase not in {"succeeded", "failed"}:
        return

    pod_reason = _derive_pod_reason(pod)
    proposed, reason = pod_terminated_terminal(pod_reason)
    async with pool.acquire() as conn:
        # asyncpg's pool yields `PoolConnectionProxy` which forwards every
        # Connection method but doesn't formally subclass it.
        result = await state_db.write_terminal_state(
            cast("asyncpg.Connection", conn), task_id, proposed, reason=reason
        )
    if result is not state_db.TerminalWriteResult.NO_OP:
        logger.info(
            "tctl: reconciled task=%s as %s (reason=%s, write=%s)",
            task_id,
            proposed.value,
            reason,
            result.value,
        )


async def _sweep_pending(
    core_v1: CoreV1Api,
    pool: asyncpg.Pool,
    namespace: str,
) -> None:
    """List Pending taskpods and time out any that have been stuck too long."""
    try:
        pod_list = await asyncio.to_thread(
            core_v1.list_namespaced_pod,
            namespace=namespace,
            label_selector=_TASK_LABEL,
            field_selector="status.phase=Pending",
        )
    except Exception:
        logger.exception("tctl: pending sweep — list pods failed")
        return

    now = datetime.now(UTC)
    for pod in pod_list.items:
        pod_dict = pod.to_dict() if hasattr(pod, "to_dict") else dict(pod)
        if not _pending_too_long(pod_dict, now):
            continue
        task_id = _task_id_from_pod(pod_dict)
        if task_id is None:
            continue
        reason = _pending_failure_reason(pod_dict)
        async with pool.acquire() as conn:
            result = await state_db.write_terminal_state(
                cast("asyncpg.Connection", conn),
                task_id,
                TesState.SYSTEM_ERROR,
                reason=reason,
            )
        if result is not state_db.TerminalWriteResult.NO_OP:
            logger.info(
                "tctl: pending timeout reconciled task=%s (reason=%s, write=%s)",
                task_id,
                reason,
                result.value,
            )


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


def _pending_failure_reason(pod: Mapping[str, Any]) -> str:
    """Best-effort human-readable cause for a stuck-Pending pod."""
    status = pod.get("status") or {}

    # Container-level waiting reasons (image pull, config, etc).
    init_statuses = (
        status.get("initContainerStatuses")
        or status.get("init_container_statuses")
        or []
    )
    container_statuses = (
        status.get("containerStatuses") or status.get("container_statuses") or []
    )
    for cs in (*init_statuses, *container_statuses):
        waiting = (cs.get("state") or {}).get("waiting") or {}
        reason = waiting.get("reason")
        if reason and reason not in {"PodInitializing", "ContainerCreating"}:
            return str(reason)

    # Pod-level scheduling failure (FailedScheduling, Unschedulable).
    for cond in status.get("conditions") or []:
        if cond.get("type") == "PodScheduled" and cond.get("status") == "False":
            return str(cond.get("reason") or "Unschedulable")

    return "Pending timeout"


def _task_id_from_pod(pod: Mapping[str, Any]) -> str | None:
    """Return the task UUID this Pod represents, if labelled."""
    metadata = pod.get("metadata") or {}
    labels = metadata.get("labels") or {}
    return labels.get(_TASK_LABEL)


def _derive_pod_reason(pod: Mapping[str, Any]) -> str | None:
    """Map kubelet's Pod-level reason to one of `PodTerminationReason.*.value`.

    Most Pod terminations carry a `status.reason` we can pass through; we
    only translate the common categories TRec can't observe (NodeLost,
    Evicted, DeadlineExceeded). The non-init `pause` container completing
    successfully means the Pod ran to terminal cleanly.
    """
    status = pod.get("status") or {}
    raw_reason = status.get("reason")
    if raw_reason == "Evicted":
        return PodTerminationReason.EVICTED.value
    if raw_reason == "NodeLost":
        return PodTerminationReason.NODE_LOST.value
    if raw_reason == "DeadlineExceeded":
        return PodTerminationReason.DEADLINE_EXCEEDED.value
    if status.get("phase") == "Succeeded":
        return PodTerminationReason.COMPLETED.value

    container_statuses = (
        status.get("containerStatuses") or status.get("container_statuses") or []
    )
    init_statuses = (
        status.get("initContainerStatuses")
        or status.get("init_container_statuses")
        or []
    )
    for cs in (*init_statuses, *container_statuses):
        if cs.get("name") == ACK_NAME:
            continue
        terminated = (cs.get("state") or {}).get("terminated") or {}
        cs_reason = terminated.get("reason")
        if cs_reason:
            return str(cs_reason)
    return PodTerminationReason.ERROR.value


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
