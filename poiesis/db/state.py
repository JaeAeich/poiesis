"""Task state-machine transitions.

The single code path for terminal writes. Callers (the in-Pod recorder and
the global controller) compose these onto a shared connection so they
race-correctly through Postgres row-level locking, not application-level locks.

Two operations matter:

  `mark_canceling`        moves a non-terminal task to CANCELING.
  `write_terminal_state`  moves any non-terminal task (including CANCELING)
                        to a terminal state, with one ordering rule:
                        if the row is currently CANCELING, the write lands
                        as CANCELED regardless of the proposed state.

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

    return (
        TerminalWriteResult.APPLIED
        if applied is not None
        else TerminalWriteResult.NO_OP
    )
