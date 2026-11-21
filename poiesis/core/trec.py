"""Task Recorder — the native sidecar that records its Pod's lifecycle.

TRec runs inside the TaskPod and watches its own Pod via the Kubernetes
API. Each watch event is translated by `pod_status.translate` into a
list of `TaskEvent`s; the recorder applies them by writing executor and
filer log rows to Postgres. An executor's row carries the tail of its
output as `stdout` and `stderr`: from its container log, or from the
files on the task volume it writes them to (see
`poiesis.core.executor_logs`).

Trec writes two non-terminal states: INITIALIZING when it starts, while
images are pulled and inputs staged, and RUNNING once it sees the first
executor start (or finish, if the watch missed its start).

Trec does NOT write terminal state. The cluster-wide controller (tctl)
owns terminal transitions exclusively — see `poiesis/core/tctl.py`. Trec's
job ends when either the Pod reaches a terminal phase (it returns 0 and
lets the sidecar wind down naturally) or it receives SIGTERM from kubelet
during pod teardown. The kubelet stops the sidecar once the other
containers have ended, so on SIGTERM trec reads the Pod once more, records
what the watch hadn't delivered yet, and exits 0 at once: the Pod, and so
the task, ends when trec does.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping

    #: Reads executor N's (stdout, stderr); None for what can't be read.
    ReadOutput = Callable[[int], Awaitable[tuple[str | None, str | None]]]

import asyncpg
from kubernetes import client

from poiesis.core.executor_logs import Streams, read_executor_streams
from poiesis.core.k8s_watch import PodEvent, PodSelector, watch_pods
from poiesis.core.pod_status import (
    EventKind,
    TaskEvent,
    TaskStateSnapshot,
    translate,
)
from poiesis.db import state as state_db

logger = logging.getLogger(__name__)

#: Budget for the last read of the Pod on SIGTERM, well inside the Pod's
#: termination grace period.
_LAST_STATE_TIMEOUT_SECONDS = 10
_LAST_STATE_REQUEST_TIMEOUT = (5, 5)


async def run(
    task_id: str,
    pod_name: str,
    namespace: str,
    dsn: str,
    streams: Mapping[int, Streams] | None = None,
) -> int:
    """Record the Pod's lifecycle into Postgres until terminal or signalled.

    `streams` says which executors write stdout/stderr to files on the task
    volume. Returns 0 on a clean exit (terminal pod or SIGTERM), 1 on an
    unrecoverable watch error.
    """
    conn = await asyncpg.connect(dsn)
    try:
        await _mark_initializing(conn, task_id)
        return await _run_until_terminal(
            conn, task_id, pod_name, namespace, streams or {}
        )
    finally:
        await conn.close()


async def _run_until_terminal(
    conn: asyncpg.Connection,
    task_id: str,
    pod_name: str,
    namespace: str,
    streams: Mapping[int, Streams],
) -> int:
    """Drive the Pod watch and apply each event to Postgres."""
    snapshot = TaskStateSnapshot()
    cancelled = _install_signal_handlers()

    core_v1 = client.CoreV1Api()

    async def read_output(ordinal: int) -> tuple[str | None, str | None]:
        return await read_executor_streams(
            core_v1, pod_name, namespace, ordinal, streams.get(ordinal)
        )

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
                with contextlib.suppress(asyncio.CancelledError):
                    await wait_for_event
                logger.info("trec: SIGTERM received; recording the last state")
                await _record_last_state(
                    conn, task_id, core_v1, pod_name, namespace, snapshot, read_output
                )
                logger.info("trec: exiting")
                return 0
            wait_for_signal.cancel()
            event = wait_for_event.result()
            if event is None:
                logger.warning("trec: watch stream ended unexpectedly")
                return 1
            pod_status = (event.pod.get("status") or {}) if event.pod else {}
            terminal = await _apply_pod_snapshot(
                conn, task_id, pod_status, snapshot, read_output
            )
            if terminal:
                logger.info("trec: pod reached terminal phase; exiting")
                return 0
    finally:
        await events.aclose()


async def _record_last_state(
    conn: asyncpg.Connection,
    task_id: str,
    core_v1: client.CoreV1Api,
    pod_name: str,
    namespace: str,
    snapshot: TaskStateSnapshot,
    read_output: ReadOutput,
) -> None:
    """Apply the Pod's current status once more, within a time budget.

    The watch may lag behind the executors' last transitions, and only
    trec can read output files on the task volume, so this is the last
    chance to record them; tctl backfills whatever is still missing.
    Never raises.
    """
    # The stubs don't list the client's `_request_timeout`.
    api: Any = core_v1
    try:
        async with asyncio.timeout(_LAST_STATE_TIMEOUT_SECONDS):
            pod = await asyncio.to_thread(
                api.read_namespaced_pod,
                name=pod_name,
                namespace=namespace,
                _request_timeout=_LAST_STATE_REQUEST_TIMEOUT,
            )
            status = pod.to_dict().get("status") or {}
            await _apply_pod_snapshot(conn, task_id, status, snapshot, read_output)
    except Exception as exc:  # noqa: BLE001 - exiting promptly matters more
        logger.warning("trec: could not record the Pod's last state: %s", exc)


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
    read_output: ReadOutput,
) -> bool:
    """Translate one Pod.status snapshot and apply each new event.

    Returns True iff the translator emitted a POD_TERMINATED event, in
    which case the caller should stop watching. The terminal *write* to
    the tasks row is tctl's job, not trec's.
    """
    pod_terminated = False
    events = translate(pod_status, snapshot)
    if not snapshot.running and any(e.kind in _EXECUTOR_KINDS for e in events):
        await _mark_running(conn, task_id)
        object.__setattr__(snapshot, "running", True)
    for event in events:
        await _apply_event(conn, task_id, event, read_output)
        _advance_snapshot(snapshot, event)
        if event.kind is EventKind.POD_TERMINATED:
            pod_terminated = True
    return pod_terminated


async def _apply_event(
    conn: asyncpg.Connection,
    task_id: str,
    event: TaskEvent,
    read_output: ReadOutput,
) -> None:
    """Persist a single non-terminal observation.

    Executor finishes land as `executor_logs` rows, with the tail of the
    executor's output as `stdout` and `stderr` (None if it can't be read);
    filer non-zero exits land as `system_logs` strings. Terminal state is
    tctl's exclusive write — trec touches neither the tasks row nor
    `write_terminal_state`.
    """
    if event.kind is EventKind.EXECUTOR_FINISHED:
        if event.executor_index is not None and event.exit_code is not None:
            stdout, stderr = await read_output(event.executor_index)
            await state_db.append_executor_log(
                conn,
                task_id,
                ordinal=event.executor_index,
                exit_code=event.exit_code,
                start_time=_parse_iso(event.started_at),
                end_time=_parse_iso(event.finished_at),
                stdout=stdout,
                stderr=stderr,
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
_EXECUTOR_KINDS = frozenset({EventKind.EXECUTOR_STARTED, EventKind.EXECUTOR_FINISHED})


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


async def _mark_initializing(conn: asyncpg.Connection, task_id: str) -> None:
    """Transition a QUEUED task to INITIALIZING; no-op in any other state.

    Trec is the Pod's first container, so it starts once the Pod is
    scheduled, before images are pulled and inputs staged.
    """
    await conn.execute(
        """
        UPDATE tasks
            SET state = 'INITIALIZING'
        WHERE id = $1
            AND state = 'QUEUED'
        """,
        uuid.UUID(task_id),
    )


async def _mark_running(conn: asyncpg.Connection, task_id: str) -> None:
    """Transition the task to RUNNING once the first executor has started.

    A no-op if it's already past that: CANCELING or terminal.
    """
    await conn.execute(
        """
        UPDATE tasks
            SET state = 'RUNNING'
        WHERE id = $1
            AND state IN ('QUEUED', 'INITIALIZING')
        """,
        uuid.UUID(task_id),
    )


def _install_signal_handlers() -> asyncio.Event:
    """Wire SIGTERM/SIGINT to set an asyncio Event the watch loop polls."""
    cancelled = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, cancelled.set)
    return cancelled
