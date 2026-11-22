"""Trec writes INITIALIZING when it starts, RUNNING at the first executor (#166).

It wrote RUNNING when it started, so a task showed RUNNING while its
inputs were still staging. Skipped without ``POIESIS_TEST_DATABASE_URL``
(see `postgres.py`).
"""

import asyncio
from typing import Any

from postgres import DSN, needs_postgres, run

from poiesis.tes.models import TesExecutor, TesState, TesTask
from poiesis.core import trec
from poiesis.core.pod_status import TaskStateSnapshot
from poiesis.db import state as state_db
from poiesis.db import tasks as tasks_db

pytestmark = needs_postgres
OWNER = "https://kc.example.org/realms/poiesis|alice"
STARTED = {"running": {"startedAt": "2026-11-22T10:00:00+00:00"}}
FINISHED = {
    "terminated": {
        "exitCode": 0,
        "startedAt": "2026-11-22T10:00:00+00:00",
        "finishedAt": "2026-11-22T10:00:01+00:00",
    }
}


def pod(**containers: dict[str, Any]) -> dict[str, Any]:
    """A Pod status whose init containers are in the given states."""
    return {
        "phase": "Pending",
        "initContainerStatuses": [
            {"name": name.replace("_", "-"), "state": state}
            for name, state in containers.items()
        ],
    }


class OnConn:
    """A trec database whose writes all run on one given connection."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    async def write(self, statement: Any, *args: Any, **kwargs: Any) -> None:
        await statement(self.conn, *args, **kwargs)


async def no_output(_ordinal: int) -> tuple[None, None]:
    """The executors' output, which these tests don't read."""
    return None, None


async def create(conn: Any) -> str:
    """Store a QUEUED task with one executor."""
    task = TesTask(
        state=TesState.QUEUED,
        executors=[TesExecutor(image="alpine", command=["true"])],
    )
    return await tasks_db.create_task(conn, task, OWNER)


async def state(conn: Any, task_id: str) -> str:
    """The task's stored state."""
    meta = await tasks_db.get_task_meta(conn, task_id)
    assert meta is not None
    return meta["state"]


def test_initializing_while_staging_then_running() -> None:
    """QUEUED → INITIALIZING at start, RUNNING only when exec-0 starts."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            task_id = await create(conn)
            snapshot = TaskStateSnapshot()
            await trec._mark_initializing(conn, task_id)
            assert await state(conn, task_id) == "INITIALIZING"
            await trec._apply_pod_snapshot(
                OnConn(conn), task_id, pod(tif=STARTED), snapshot, no_output
            )
            assert await state(conn, task_id) == "INITIALIZING"
            await trec._apply_pod_snapshot(
                OnConn(conn),
                task_id,
                pod(tif=FINISHED, exec_0=STARTED),
                snapshot,
                no_output,
            )
            assert await state(conn, task_id) == "RUNNING"
            assert snapshot.running
            # A restarted trec doesn't move the task back.
            await trec._mark_initializing(conn, task_id)
            assert await state(conn, task_id) == "RUNNING"

    run(test)


def test_finished_executor_seen_first_marks_running() -> None:
    """A watch that missed the executor's start still marks RUNNING."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            task_id = await create(conn)
            await trec._mark_initializing(conn, task_id)
            await trec._apply_pod_snapshot(
                OnConn(conn),
                task_id,
                pod(tif=FINISHED, exec_0=FINISHED),
                TaskStateSnapshot(),
                no_output,
            )
            assert await state(conn, task_id) == "RUNNING"
            assert await state_db.recorded_executor_ordinals(conn, task_id) == {0}

    run(test)


def test_cancel_from_initializing_wins() -> None:
    """INITIALIZING is non-terminal: it can be cancelled, trec doesn't undo that."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            task_id = await create(conn)
            await trec._mark_initializing(conn, task_id)
            assert await state_db.mark_canceling(conn, task_id)
            await trec._mark_initializing(conn, task_id)
            await trec._apply_pod_snapshot(
                OnConn(conn),
                task_id,
                pod(exec_0=STARTED),
                TaskStateSnapshot(),
                no_output,
            )
            assert await state(conn, task_id) == "CANCELING"
            assert await state_db.list_non_terminal_task_ids(
                conn, older_than_seconds=0
            ) == [task_id]
            result = await state_db.write_terminal_state(
                conn, task_id, TesState.SYSTEM_ERROR
            )
            assert result is state_db.TerminalWriteResult.CANCELED_INSTEAD

    run(test)


def test_failed_staging_ends_from_initializing() -> None:
    """tctl's terminal write applies to an INITIALIZING task."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            task_id = await create(conn)
            await trec._mark_initializing(conn, task_id)
            result = await state_db.write_terminal_state(
                conn, task_id, TesState.SYSTEM_ERROR, reason="tif failed"
            )
            assert result is state_db.TerminalWriteResult.APPLIED
            assert await state(conn, task_id) == "SYSTEM_ERROR"

    run(test)


def test_each_write_opens_and_closes_its_own_connection() -> None:
    """trec's writes reach Postgres; none of its connections stays open (#164)."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            task_id = await create(conn)
            schema = await conn.fetchval("SELECT current_schema()")
        sep = "&" if "?" in DSN else "?"
        db = trec._Database(f"{DSN}{sep}search_path={schema}&application_name={schema}")
        await db.write(trec._mark_initializing, task_id)
        await trec._apply_pod_snapshot(
            db,
            task_id,
            pod(tif=FINISHED, exec_0=FINISHED),
            TaskStateSnapshot(),
            no_output,
        )
        async with pool.acquire() as conn:
            assert await state(conn, task_id) == "RUNNING"
            assert await state_db.recorded_executor_ordinals(conn, task_id) == {0}
            for _ in range(50):
                left = await conn.fetchval(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name = $1",
                    schema,
                )
                if left == 0:
                    break
                await asyncio.sleep(0.02)
            assert left == 0

    run(test)
