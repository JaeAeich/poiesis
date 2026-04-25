"""Task Recorder — the native sidecar that records its Pod's lifecycle.

TRec runs inside the TaskPod and watches its own Pod via the Kubernetes
API. Each watch event is translated by `pod_status.translate` into a
list of `TaskEvent`s; the recorder applies them by writing to Postgres.

A `TaskStateSnapshot` is kept in memory so the translator doesn't re-emit
events the recorder has already persisted. On a terminal Pod event the
recorder writes the final state and returns; on SIGTERM it checks the
DB for a CANCELING marker (set by the API on `CancelTask`) and writes
CANCELED if present.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import uuid

import asyncpg
import kubernetes
from kubernetes import client

from poiesis.api.tes.models import TesState
from poiesis.core.pod_status import (
    EventKind,
    PodTerminationReason,
    TaskEvent,
    TaskStateSnapshot,
    translate,
)
from poiesis.db import state as state_db

logger = logging.getLogger(__name__)

#: Per-event-stream timeout for the K8s watch. The stream is restarted
#: on timeout — this caps how long a stale connection lingers.
_WATCH_STREAM_TIMEOUT_SECONDS = 300


async def run(task_id: str, pod_name: str, namespace: str, dsn: str) -> int:
    """Record the Pod's lifecycle into Postgres until terminal or signalled.

    Returns 0 on a clean terminal observation, 1 on an unrecoverable error.
    """
    conn = await asyncpg.connect(dsn)
    try:
        await _mark_running(conn, task_id)
        return await _run_until_terminal(conn, task_id, pod_name, namespace)
    finally:
        await conn.close()


async def _run_until_terminal(
    conn: asyncpg.Connection,
    task_id: str,
    pod_name: str,
    namespace: str,
) -> int:
    """Drive the watch-stream producer and apply each event to Postgres."""
    snapshot = TaskStateSnapshot()
    queue: asyncio.Queue[_PodSnap | None] = asyncio.Queue()
    cancelled = _install_signal_handlers()

    loop = asyncio.get_running_loop()
    producer = loop.run_in_executor(
        None,
        _stream_pod_status,
        pod_name,
        namespace,
        queue,
        loop,
    )

    try:
        while True:
            wait_for_event = asyncio.create_task(queue.get())
            wait_for_signal = asyncio.create_task(cancelled.wait())
            done, _ = await asyncio.wait(
                {wait_for_event, wait_for_signal},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if wait_for_signal in done:
                wait_for_event.cancel()
                await _on_signal(conn, task_id)
                return 0
            snap = wait_for_event.result()
            if snap is None:
                # Producer terminated unexpectedly — give up cleanly.
                return 1
            terminal = await _apply_pod_snapshot(conn, task_id, snap, snapshot)
            if terminal:
                return 0
    finally:
        producer.cancel()


class _PodSnap:
    """A single watch event reduced to its Pod.status dict."""

    __slots__ = ("status",)

    def __init__(self, status: dict[str, object]) -> None:
        self.status = status


def _stream_pod_status(
    pod_name: str,
    namespace: str,
    queue: asyncio.Queue[_PodSnap | None],
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Run in a worker thread: stream Pod events onto the async queue.

    A None sentinel is pushed when the stream ends or errors so the
    consumer can detect termination.
    """
    core_v1 = client.CoreV1Api()
    try:
        while True:
            # `kubernetes-stubs` does not export the `watch` submodule that
            # the runtime kubernetes client publishes.
            w = kubernetes.watch.Watch()  # ty: ignore[unresolved-attribute]
            for event in w.stream(
                core_v1.list_namespaced_pod,
                namespace=namespace,
                field_selector=f"metadata.name={pod_name}",
                timeout_seconds=_WATCH_STREAM_TIMEOUT_SECONDS,
            ):
                pod = event["object"]
                status = pod.status.to_dict() if pod.status is not None else {}
                loop.call_soon_threadsafe(queue.put_nowait, _PodSnap(status))
            # Stream timed out; reconnect on the next loop iteration.
    except Exception:
        logger.exception("TRec watch stream failed")
        loop.call_soon_threadsafe(queue.put_nowait, None)


async def _apply_pod_snapshot(
    conn: asyncpg.Connection,
    task_id: str,
    snap: _PodSnap,
    snapshot: TaskStateSnapshot,
) -> bool:
    """Translate one Pod.status snapshot and apply each new event.

    Returns True if the Pod has reached a terminal state.
    """
    for event in translate(snap.status, snapshot):  # type: ignore[arg-type]
        await _apply_event(conn, task_id, event)
        _advance_snapshot(snapshot, event)
        if event.kind is EventKind.POD_TERMINATED:
            return True
    return False


async def _apply_event(
    conn: asyncpg.Connection,
    task_id: str,
    event: TaskEvent,
) -> None:
    """Persist a single task event."""
    if event.kind is EventKind.POD_TERMINATED:
        proposed, reason = _pod_terminated_terminal(event.reason)
        await state_db.write_terminal_state(conn, task_id, proposed, reason=reason)
        return

    if event.kind is EventKind.EXECUTOR_FINISHED and (event.exit_code or 0) != 0:
        await state_db.write_terminal_state(
            conn,
            task_id,
            TesState.EXECUTOR_ERROR,
            reason=event.reason or "executor exited non-zero",
        )


def _pod_terminated_terminal(
    pod_reason: str | None,
) -> tuple[TesState, str | None]:
    """Map a Pod-termination reason to a terminal TES state + reason string."""
    if pod_reason == PodTerminationReason.COMPLETED.value:
        return TesState.COMPLETE, None
    if pod_reason in {
        PodTerminationReason.OOM_KILLED.value,
        PodTerminationReason.EVICTED.value,
        PodTerminationReason.NODE_LOST.value,
        PodTerminationReason.DEADLINE_EXCEEDED.value,
        PodTerminationReason.PVC_BIND_FAILURE.value,
    }:
        return TesState.SYSTEM_ERROR, pod_reason
    return TesState.EXECUTOR_ERROR, pod_reason


def _advance_snapshot(snapshot: TaskStateSnapshot, event: TaskEvent) -> None:
    """Update the local snapshot so the translator doesn't re-emit `event`."""
    if event.kind is EventKind.TIF_FINISHED:
        object.__setattr__(snapshot, "tif_finished", True)
    elif event.kind is EventKind.EXECUTOR_FINISHED and event.executor_index is not None:
        finished = snapshot.executors_finished | {event.executor_index}
        object.__setattr__(snapshot, "executors_finished", finished)
    elif event.kind is EventKind.TOF_FINISHED:
        object.__setattr__(snapshot, "tof_finished", True)
    elif event.kind is EventKind.POD_TERMINATED:
        object.__setattr__(snapshot, "pod_terminated", True)


async def _mark_running(conn: asyncpg.Connection, task_id: str) -> None:
    """Transition the task to RUNNING; no-op if it's already past that."""
    await conn.execute(
        """
        UPDATE tasks
            SET state = 'RUNNING'
        WHERE id = $1
            AND state IN ('QUEUED', 'INITIALIZING')
        """,
        uuid.UUID(task_id),
    )


async def _on_signal(conn: asyncpg.Connection, task_id: str) -> None:
    """Honour a pending CANCELING marker when the process is signalled."""
    row = await conn.fetchrow(
        "SELECT state FROM tasks WHERE id = $1",
        uuid.UUID(task_id),
    )
    if row is not None and row["state"] == TesState.CANCELING.value:
        await state_db.write_terminal_state(
            conn,
            task_id,
            TesState.CANCELED,
            reason="Cancelled",
        )


def _install_signal_handlers() -> asyncio.Event:
    """Wire SIGTERM/SIGINT to set an asyncio Event the watch loop polls."""
    cancelled = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, cancelled.set)
    return cancelled
