"""Task state-machine transitions.

The single code path for terminal writes. Callers (the in-Pod recorder and
the global controller) compose these onto a shared connection so they
race-correctly through Postgres row-level locking, not application-level locks.

Two operations matter:

    `mark_canceling` — moves a non-terminal task to CANCELING.
    `write_terminal_state` — moves any non-terminal task (including
        CANCELING) to a terminal state. If the row is currently
        CANCELING, the write lands as CANCELED regardless of the
        proposed state.

The CANCELING precedence rule is what guarantees a SIGTERMed executor
exiting code 143 is recorded as a cancellation, not an executor error,
when the underlying cause was a user cancel.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import TYPE_CHECKING

from poiesis.api.tes.models import TesState

if TYPE_CHECKING:
    from datetime import datetime

    import asyncpg


NON_TERMINAL_STATES: tuple[str, ...] = (
    TesState.QUEUED.value,
    TesState.INITIALIZING.value,
    TesState.RUNNING.value,
    TesState.PAUSED.value,
    TesState.CANCELING.value,
)

TERMINAL_STATES: frozenset[TesState] = frozenset(
    {
        TesState.COMPLETE,
        TesState.EXECUTOR_ERROR,
        TesState.SYSTEM_ERROR,
        TesState.CANCELED,
        TesState.PREEMPTED,
    },
)


class TerminalWriteResult(Enum):
    """Outcome of `write_terminal_state`.

    Members:
        APPLIED:          The proposed terminal state landed.
        CANCELED_INSTEAD: The row was CANCELING; landed as CANCELED instead.
        NO_OP:            The row was already terminal, or does not exist.
    """

    APPLIED = "applied"
    CANCELED_INSTEAD = "canceled_instead"
    NO_OP = "no_op"


async def mark_canceling(conn: asyncpg.Connection, task_id: str) -> bool:
    """Move a non-terminal task to CANCELING.

    Returns True if the row transitioned, False if no-op (already terminal,
    already CANCELING, or not found).
    """
    row = await conn.fetchval(
        """
        UPDATE tasks
            SET state = 'CANCELING'
        WHERE id = $1
            AND state = ANY($2::tes_state[])
            AND state <> 'CANCELING'
        RETURNING id
        """,
        uuid.UUID(task_id),
        list(NON_TERMINAL_STATES),
    )
    return row is not None


async def write_terminal_state(
    conn: asyncpg.Connection,
    task_id: str,
    proposed: TesState,
    reason: str | None = None,
) -> TerminalWriteResult:
    """Write a terminal state, honouring CANCELING precedence.

    The transition is conditional on the row currently being non-terminal.
    If the row is CANCELING, the write lands as CANCELED regardless of the
    proposed state — preserving cancel intent against racing executor-exit
    observations.
    """
    if proposed not in TERMINAL_STATES:
        msg = f"proposed state must be terminal, got {proposed.value}"
        raise ValueError(msg)

    task_uuid = uuid.UUID(task_id)

    async with conn.transaction():
        # First: if the row is in CANCELING, finalise it as CANCELED.
        canceled = await conn.fetchval(
            """
            UPDATE tasks
                SET state              = 'CANCELED',
                    termination_reason = COALESCE($2, 'Cancelled'),
                    ended_at           = now()
            WHERE id = $1
                AND state = 'CANCELING'
            RETURNING id
            """,
            task_uuid,
            reason,
        )
        if canceled is not None:
            await _update_latest_task_log(
                conn, task_uuid, message=reason or "Cancelled", stamp_end=True
            )
            return TerminalWriteResult.CANCELED_INSTEAD

        # Otherwise: the normal non-terminal → terminal transition.
        applied = await conn.fetchval(
            """
            UPDATE tasks
                SET state              = $2,
                    termination_reason = $3,
                    ended_at           = now()
            WHERE id = $1
                AND state = ANY($4::tes_state[])
            RETURNING id
            """,
            task_uuid,
            proposed.value,
            reason,
            list(NON_TERMINAL_STATES),
        )
        if applied is not None:
            await _update_latest_task_log(
                conn, task_uuid, message=reason, stamp_end=True
            )

    return (
        TerminalWriteResult.APPLIED
        if applied is not None
        else TerminalWriteResult.NO_OP
    )


async def append_system_log(
    conn: asyncpg.Connection,
    task_id: str,
    message: str,
) -> None:
    """Append a free-form system-log line to the task's active log row.

    Used by recorders to surface observations (image-pull failures, init
    container errors, TIF/TOF stderr) that don't themselves change state.
    """
    await _update_latest_task_log(conn, uuid.UUID(task_id), message=message)


async def append_executor_log(
    conn: asyncpg.Connection,
    task_id: str,
    *,
    ordinal: int,
    exit_code: int,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> None:
    """Append one `executor_logs` row under the task's active log row."""
    await conn.execute(
        """
        INSERT INTO executor_logs (
            task_log_id, ordinal, start_time, end_time, exit_code
        )
        SELECT id, $2, $3, $4, $5
        FROM task_logs
        WHERE task_id = $1
        ORDER BY ordinal DESC
        LIMIT 1
        """,
        uuid.UUID(task_id),
        ordinal,
        start_time,
        end_time,
        exit_code,
    )


_UPDATE_APPEND_MESSAGE = """
    UPDATE task_logs
        SET system_logs = array_append(COALESCE(system_logs, '{}'), $2)
    WHERE id = (
        SELECT id FROM task_logs
        WHERE task_id = $1
        ORDER BY ordinal DESC
        LIMIT 1
    )
"""

_UPDATE_APPEND_MESSAGE_AND_STAMP_END = """
    UPDATE task_logs
        SET system_logs = array_append(COALESCE(system_logs, '{}'), $2),
            end_time    = now()
    WHERE id = (
        SELECT id FROM task_logs
        WHERE task_id = $1
        ORDER BY ordinal DESC
        LIMIT 1
    )
"""

_UPDATE_STAMP_END = """
    UPDATE task_logs
        SET end_time = now()
    WHERE id = (
        SELECT id FROM task_logs
        WHERE task_id = $1
        ORDER BY ordinal DESC
        LIMIT 1
    )
"""


async def _update_latest_task_log(
    conn: asyncpg.Connection,
    task_uuid: uuid.UUID,
    *,
    message: str | None = None,
    stamp_end: bool = False,
) -> None:
    """Update the highest-ordinal `task_logs` row for `task_uuid`.

    Appends `message` to `system_logs` when given, stamps `end_time = now()`
    when `stamp_end`. A no-op when both are absent.
    """
    if message is not None and stamp_end:
        await conn.execute(_UPDATE_APPEND_MESSAGE_AND_STAMP_END, task_uuid, message)
    elif message is not None:
        await conn.execute(_UPDATE_APPEND_MESSAGE, task_uuid, message)
    elif stamp_end:
        await conn.execute(_UPDATE_STAMP_END, task_uuid)
