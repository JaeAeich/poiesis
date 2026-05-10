"""Task Controller — backstop reconciler for un-self-reportable failures.

TCtl is the leader-elected global controller that watches TaskPods cluster-wide
(scoped here to a namespace for the dev RBAC story) and writes terminal state
for failures the in-Pod recorder cannot self-report: OOMKill before TRec
started, eviction, node loss, image-pull failure, PVC bind failure,
`activeDeadlineSeconds` exceeded.

Two race-correct guarantees from the writer:

  * `state.write_terminal_state` is conditional on the row being non-terminal,
    so whoever writes first (TCtl or TRec) wins — no overwrite.
  * The CANCELING precedence rule means a SIGTERMed pod observed terminating
    after a `CancelTask` still records as CANCELED.

Leader election uses `coordination.k8s.io/v1` Leases (see `core/leases.py`).
"""

from __future__ import annotations

import asyncio
import logging
import signal
import socket
import uuid
from typing import Any, cast

import asyncpg
import kubernetes
from kubernetes.client import CoordinationV1Api, CoreV1Api

from poiesis.core.leases import try_acquire_or_renew
from poiesis.core.pod_status import (
    PAUSE_NAME,
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
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
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
                pod = await asyncio.wait_for(
                    queue.get(), timeout=_LEASE_RENEW_INTERVAL_SECONDS
                )
            except TimeoutError:
                continue
            if pod is None:
                logger.warning("tctl: pod stream ended; restarting")
                return
            await _handle_pod(pool, pod)
    finally:
        producer.cancel()


def _stream_pods(
    core_v1: CoreV1Api,
    namespace: str,
    queue: asyncio.Queue[dict[str, Any] | None],
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Run in a worker thread: stream Pod events onto the async queue.

    A None sentinel is pushed when the stream ends or errors.
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
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    pod.to_dict() if hasattr(pod, "to_dict") else dict(pod),
                )
    except Exception:
        logger.exception("tctl: pod watch stream failed")
        loop.call_soon_threadsafe(queue.put_nowait, None)


async def _handle_pod(pool: asyncpg.Pool, pod: dict[str, Any]) -> None:
    """Inspect a Pod event and write terminal state if reconciliation is needed."""
    task_id = _task_id_from_pod(pod)
    if task_id is None:
        return
    phase = ((pod.get("status") or {}).get("phase") or "").lower()
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


def _task_id_from_pod(pod: dict[str, Any]) -> str | None:
    """Return the task UUID this Pod represents, if labelled."""
    metadata = pod.get("metadata") or {}
    labels = metadata.get("labels") or {}
    return labels.get(_TASK_LABEL)


def _derive_pod_reason(pod: dict[str, Any]) -> str | None:
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
        if cs.get("name") == PAUSE_NAME:
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
