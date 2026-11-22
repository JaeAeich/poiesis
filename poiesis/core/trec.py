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

Trec holds no database connection between writes: each write opens one,
retrying with backoff while Postgres can't be reached, and closes it. An
event is marked recorded only once its write succeeded, so one that
couldn't be written is tried again with the next Pod status.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
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
    parse_timestamp,
    translate,
)
from poiesis.core.shutdown import stop_on_signals
from poiesis.db import state as state_db

logger = logging.getLogger(__name__)

#: Budget for the last read of the Pod on SIGTERM, well inside the Pod's
#: termination grace period.
_LAST_STATE_TIMEOUT_SECONDS = 10
_LAST_STATE_REQUEST_TIMEOUT = (5, 5)

#: Seconds to wait between attempts to connect to Postgres; after the last
#: one the error is raised. About a minute in all: trec then exits, and
#: the kubelet restarts it.
_CONNECT_BACKOFF_SECONDS = (0.5, 1, 2, 4, 8, 15, 30)
#: Per attempt: seconds to connect, and seconds a statement may run.
_CONNECT_TIMEOUT_SECONDS = 10
_COMMAND_TIMEOUT_SECONDS = 30
#: Errors that mean Postgres can't be reached right now, not a bad query
#: or bad credentials.
_CONNECT_ERRORS = (
    OSError,
    TimeoutError,
    asyncpg.PostgresConnectionError,
    asyncpg.OperatorInterventionError,
    asyncpg.TooManyConnectionsError,
)


class _Database:
    """Opens a Postgres connection for each write and closes it after.

    So N running tasks don't hold N connections between their events.
    Connecting is retried with backoff (`_CONNECT_BACKOFF_SECONDS`); once
    `stop` is set, the next failure is raised at once.
    """

    def __init__(self, dsn: str, stop: asyncio.Event | None = None) -> None:
        """Connect to `dsn`; give up retrying once `stop` is set."""
        self._dsn = dsn
        self._stop = stop

    def until(self, stop: asyncio.Event) -> _Database:
        """The same database, retrying only until `stop` is set."""
        return _Database(self._dsn, stop)

    async def write(
        self,
        statement: Callable[..., Awaitable[object]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Run `statement(conn, *args, **kwargs)` on a new connection."""
        conn = await self._connect()
        try:
            await statement(conn, *args, **kwargs)
        finally:
            try:
                await conn.close(timeout=_CONNECT_TIMEOUT_SECONDS)
            except Exception:  # noqa: BLE001 - a dead connection is just dropped
                conn.terminate()

    async def _connect(self) -> asyncpg.Connection:
        """Connect, retrying while Postgres can't be reached."""
        for delay in (*_CONNECT_BACKOFF_SECONDS, None):
            try:
                return await asyncpg.connect(
                    self._dsn,
                    timeout=_CONNECT_TIMEOUT_SECONDS,
                    command_timeout=_COMMAND_TIMEOUT_SECONDS,
                )
            except _CONNECT_ERRORS as exc:
                if delay is None or (self._stop is not None and self._stop.is_set()):
                    raise
                logger.warning(
                    "trec: cannot connect to Postgres (%s); retrying in %ss",
                    type(exc).__name__,
                    delay,
                )
                await self._sleep(delay)
        raise AssertionError  # pragma: no cover - the loop returns or raises

    async def _sleep(self, seconds: float) -> None:
        """Wait `seconds`, or until `stop` is set."""
        if self._stop is None:
            await asyncio.sleep(seconds)
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)


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
    db = _Database(dsn)
    await db.write(_mark_initializing, task_id)
    return await _run_until_terminal(db, task_id, pod_name, namespace, streams or {})


async def _run_until_terminal(
    db: _Database,
    task_id: str,
    pod_name: str,
    namespace: str,
    streams: Mapping[int, Streams],
) -> int:
    """Drive the Pod watch and apply each event to Postgres."""
    snapshot = TaskStateSnapshot()
    cancelled = stop_on_signals()
    # While watching, a SIGTERM ends a wait for Postgres; the last read
    # below then tries again within its own time budget.
    watch_db = db.until(cancelled)

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
                    db, task_id, core_v1, pod_name, namespace, snapshot, read_output
                )
                logger.info("trec: exiting")
                return 0
            wait_for_signal.cancel()
            event = wait_for_event.result()
            if event is None:
                logger.warning("trec: watch stream ended unexpectedly")
                return 1
            pod_status = (event.pod.get("status") or {}) if event.pod else {}
            try:
                terminal = await _apply_pod_snapshot(
                    watch_db, task_id, pod_status, snapshot, read_output
                )
            except _CONNECT_ERRORS:
                if not cancelled.is_set():
                    raise
                # Not recorded; the last read applies it again.
                continue
            if terminal:
                logger.info("trec: pod reached terminal phase; exiting")
                return 0
    finally:
        await events.aclose()


async def _record_last_state(
    db: _Database,
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
            await _apply_pod_snapshot(db, task_id, status, snapshot, read_output)
    except Exception as exc:  # noqa: BLE001 - exiting promptly matters more
        logger.warning("trec: could not record the Pod's last state: %s", exc)


async def _next(events: AsyncGenerator[PodEvent]) -> PodEvent | None:
    """Return the next watch event or None on stream end."""
    try:
        return await events.__anext__()
    except StopAsyncIteration:
        return None


async def _apply_pod_snapshot(
    db: _Database,
    task_id: str,
    pod_status: Mapping[str, Any],
    snapshot: TaskStateSnapshot,
    read_output: ReadOutput,
) -> bool:
    """Translate one Pod.status snapshot and apply each new event.

    Returns True iff the translator emitted a POD_TERMINATED event, in
    which case the caller should stop watching. The terminal *write* to
    the tasks row is tctl's job, not trec's. An event is added to
    `snapshot` only once written: if a write raises, that event and the
    ones after it are emitted again from the next status.
    """
    pod_terminated = False
    events = translate(pod_status, snapshot)
    if not snapshot.running and any(e.kind in _EXECUTOR_KINDS for e in events):
        await db.write(_mark_running, task_id)
        object.__setattr__(snapshot, "running", True)
    for event in events:
        await _apply_event(db, task_id, event, read_output)
        _advance_snapshot(snapshot, event)
        if event.kind is EventKind.POD_TERMINATED:
            pod_terminated = True
    return pod_terminated


async def _apply_event(
    db: _Database,
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
            # Read before connecting: no connection waits on the kubelet.
            stdout, stderr = await read_output(event.executor_index)
            await db.write(
                state_db.append_executor_log,
                task_id,
                ordinal=event.executor_index,
                exit_code=event.exit_code,
                start_time=parse_timestamp(event.started_at),
                end_time=parse_timestamp(event.finished_at),
                stdout=stdout,
                stderr=stderr,
            )
        return

    if event.kind in _FILER_FINISHED_KINDS and (event.exit_code or 0) != 0:
        await db.write(
            state_db.append_system_log,
            task_id,
            event.reason or _FILER_DEFAULT_REASON[event.kind],
        )


_FILER_DEFAULT_REASON = {
    EventKind.TIF_FINISHED: "input filer exited non-zero",
    EventKind.TOF_FINISHED: "output filer exited non-zero",
}
_FILER_FINISHED_KINDS = frozenset(_FILER_DEFAULT_REASON)
_EXECUTOR_KINDS = frozenset({EventKind.EXECUTOR_STARTED, EventKind.EXECUTOR_FINISHED})


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
