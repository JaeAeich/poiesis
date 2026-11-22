"""Executor output is stored and served in the FULL view (#111), on Postgres.

Skipped without ``POIESIS_TEST_DATABASE_URL`` (see `postgres.py`).
"""

from typing import Any

from postgres import needs_postgres, run

from poiesis.tes.models import TesExecutor, TesState, TesTask
from poiesis.db import state as state_db
from poiesis.db import tasks as tasks_db
from poiesis.db.tasks import TaskView

pytestmark = needs_postgres
OWNER = "https://kc.example.org/realms/poiesis|alice"


async def create(conn: Any) -> str:
    task = TesTask(
        state=TesState.QUEUED,
        executors=[TesExecutor(image="alpine", command=["true"]) for _ in range(2)],
    )
    return await tasks_db.create_task(conn, task, OWNER)


def test_output_is_served_in_the_full_view() -> None:
    """Stored stdout shows in FULL, not in BASIC; a missing read stays empty."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            task_id = await create(conn)
            await state_db.append_executor_log(
                conn, task_id, ordinal=0, exit_code=0, stdout="hello\n"
            )
            await state_db.append_executor_log(conn, task_id, ordinal=1, exit_code=1)
            full = await tasks_db.get_task(conn, task_id, TaskView.FULL)
            basic = await tasks_db.get_task(conn, task_id, TaskView.BASIC)
        assert full is not None
        assert basic is not None
        assert full.logs is not None
        assert basic.logs is not None
        (log,) = full.logs
        assert log.logs is not None
        assert [(e.stdout, e.stderr, e.exit_code) for e in log.logs] == [
            ("hello\n", None, 0),
            (None, None, 1),
        ]
        assert basic.logs[0].logs is not None
        assert [e.stdout for e in basic.logs[0].logs] == [None, None]

    run(test)


def test_recorded_ordinals_and_first_write_wins() -> None:
    """Recorded ordinals are listed; a second write of one changes nothing."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            task_id = await create(conn)
            assert await state_db.recorded_executor_ordinals(conn, task_id) == set()
            await state_db.append_executor_log(
                conn, task_id, ordinal=1, exit_code=0, stdout="first"
            )
            await state_db.append_executor_log(
                conn, task_id, ordinal=1, exit_code=0, stdout="second"
            )
            assert await state_db.recorded_executor_ordinals(conn, task_id) == {1}
            full = await tasks_db.get_task(conn, task_id, TaskView.FULL)
        assert full is not None
        assert full.logs is not None
        assert full.logs[0].logs is not None
        assert [e.stdout for e in full.logs[0].logs] == ["first"]

    run(test)
