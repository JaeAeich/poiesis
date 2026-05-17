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
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping

import asyncpg
from kubernetes import client

from poiesis.api.tes.models import TesState
from poiesis.core.k8s_watch import PodEvent, PodSelector, watch_pods
from poiesis.core.pod_status import (
    EventKind,
    TaskEvent,
    TaskStateSnapshot,
    pod_terminated_terminal,
    translate,
)
from poiesis.db import state as state_db

logger = logging.getLogger(__name__)


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
    """Drive the Pod watch and apply each event to Postgres."""
    snapshot = TaskStateSnapshot()
    cancelled = _install_signal_handlers()

    core_v1 = client.CoreV1Api()
    selector = PodSelector(
        namespace=namespace, field_selector=f"metadata.name={pod_name}"
    )
    events = watch_pods(core_v1, selector)
    try:
        while True:
            wait_for_event = asyncio.create_task(_next(events))
            wait_for_signal = asyncio.create_task(cancelled.wait())
            done, _ = await asyncio.wait(
                {wait_for_event, wait_for_signal},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if wait_for_signal in done:
                wait_for_event.cancel()
                await _on_signal(conn, task_id, pod_name, namespace, snapshot)
                return 0
            event = wait_for_event.result()
            if event is None:
                # Watch ended unexpectedly — give up cleanly.
                return 1
            pod_status = (event.pod.get("status") or {}) if event.pod else {}
            terminal = await _apply_pod_snapshot(conn, task_id, pod_status, snapshot)
            if terminal:
                return 0
    finally:
        await events.aclose()


async def _next(events: AsyncGenerator[PodEvent]) -> PodEvent | None:
    """Return the next watch event or None on stream end."""
    try:
        return await events.__anext__()
    except StopAsyncIteration:
        return None


async def _apply_pod_snapshot(
    conn: asyncpg.Connection,
    task_id: str,
    pod_status: Mapping[str, Any],
    snapshot: TaskStateSnapshot,
) -> bool:
    """Translate one Pod.status snapshot and apply each new event.

    Returns True if the Pod has reached a terminal state.
    """
    for event in translate(pod_status, snapshot):
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
        proposed, reason = pod_terminated_terminal(event.reason)
        await state_db.write_terminal_state(conn, task_id, proposed, reason=reason)
        return

    if event.kind is EventKind.EXECUTOR_FINISHED:
        if event.executor_index is not None and event.exit_code is not None:
            await state_db.append_executor_log(
                conn,
                task_id,
                ordinal=event.executor_index,
                exit_code=event.exit_code,
                start_time=_parse_iso(event.started_at),
                end_time=_parse_iso(event.finished_at),
            )
        if (event.exit_code or 0) != 0:
            await state_db.write_terminal_state(
                conn,
                task_id,
                TesState.EXECUTOR_ERROR,
                reason=event.reason or "executor exited non-zero",
            )
        return

    if event.kind in _FILER_FINISHED_KINDS and (event.exit_code or 0) != 0:
        await state_db.append_system_log(
            conn, task_id, event.reason or _FILER_DEFAULT_REASON[event.kind]
        )


_FILER_DEFAULT_REASON = {
    EventKind.TIF_FINISHED: "input filer exited non-zero",
    EventKind.TOF_FINISHED: "output filer exited non-zero",
}
_FILER_FINISHED_KINDS = frozenset(_FILER_DEFAULT_REASON)


def _parse_iso(value: str | None) -> datetime | None:
    """Parse a kubelet ISO-8601 timestamp into a datetime; None passes through."""
    if value is None:
        return None
    return datetime.fromisoformat(value)


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


async def _on_signal(
    conn: asyncpg.Connection,
    task_id: str,
    pod_name: str,
    namespace: str,
    snapshot: TaskStateSnapshot,
) -> None:
    """Best-effort terminal write on shutdown.

    Two cases the watch may have raced past:

    * Pod was canceled — the API set CANCELING; we land CANCELED.
    * Pod ran to terminal cleanly — kubelet is now stopping us; we do
        one final pod read and apply the translator so we don't lose the
        Succeeded/Failed observation.
    """
    logger.info("trec: shutdown signal received; checking task state")
    row = await conn.fetchrow(
        "SELECT state FROM tasks WHERE id = $1",
        uuid.UUID(task_id),
    )
    current = row["state"] if row is not None else None
    logger.info("trec: shutdown — db state=%s", current)
    if current == TesState.CANCELING.value:
        await state_db.write_terminal_state(
            conn,
            task_id,
            TesState.CANCELED,
            reason="Cancelled",
        )
        logger.info("trec: wrote CANCELED on shutdown")
        return
    if current in {
        TesState.COMPLETE.value,
        TesState.EXECUTOR_ERROR.value,
        TesState.SYSTEM_ERROR.value,
        TesState.CANCELED.value,
        TesState.PREEMPTED.value,
    }:
        logger.info("trec: already terminal; nothing to do")
        return

    # Watch hasn't observed the terminal phase yet; ask the K8s API directly.
    logger.info("trec: doing final pod read")
    try:
        pod = await asyncio.to_thread(
            client.CoreV1Api().read_namespaced_pod, pod_name, namespace
        )
    except Exception:
        logger.exception("trec: final pod read failed during shutdown")
        return
    if pod.status is None:
        logger.info("trec: final pod read returned no status")
        return
    await _apply_pod_snapshot(conn, task_id, pod.status.to_dict(), snapshot)
    logger.info("trec: applied final pod snapshot on shutdown")


def _install_signal_handlers() -> asyncio.Event:
    """Wire SIGTERM/SIGINT to set an asyncio Event the watch loop polls."""
    cancelled = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, cancelled.set)
    return cancelled
