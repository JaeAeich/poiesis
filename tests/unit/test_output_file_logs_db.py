"""Output file logs are stored and served in `logs[].outputs` (#166), on Postgres.

Skipped without ``POIESIS_TEST_DATABASE_URL`` (see `postgres.py`).
"""

from typing import Any

from postgres import needs_postgres, run

from poiesis.tes.models import (
    TesExecutor,
    TesOutputFileLog,
    TesState,
    TesTask,
)
from poiesis.db import state as state_db
from poiesis.db import tasks as tasks_db
from poiesis.db.tasks import TaskView

pytestmark = needs_postgres
OWNER = "https://kc.example.org/realms/poiesis|alice"


def entry(name: str, size: int) -> TesOutputFileLog:
    return TesOutputFileLog(
        url=f"s3://b/{name}", path=f"/out/{name}", size_bytes=str(size)
    )


def test_output_logs_are_served_and_a_retry_replaces_them() -> None:
    """FULL and BASIC show the entries; a second write doesn't duplicate them."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            task_id = await tasks_db.create_task(
                conn,
                TesTask(
                    state=TesState.QUEUED,
                    executors=[TesExecutor(image="alpine", command=["true"])],
                ),
                OWNER,
            )
            before = await tasks_db.get_task(conn, task_id, TaskView.FULL)
            files = [entry("a", 3), entry("b", 0)]
            await state_db.set_output_logs(conn, task_id, files)
            await state_db.set_output_logs(conn, task_id, files)
            full = await tasks_db.get_task(conn, task_id, TaskView.FULL)
            basic = await tasks_db.get_task(conn, task_id, TaskView.BASIC)
        assert before is not None
        assert before.logs is not None
        assert before.logs[0].outputs == []
        for task in (full, basic):
            assert task is not None
            assert task.logs is not None
            assert task.logs[0].outputs == files

    run(test)
