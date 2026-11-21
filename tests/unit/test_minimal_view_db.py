"""The MINIMAL view holds the task's id and state only (#166), on Postgres.

TES: "Task message will include ONLY the fields: tesTask.Id, tesTask.State".
ListTasks showed the time of the request as `creation_time`, GetTask the
stored one. Skipped without ``POIESIS_TEST_DATABASE_URL`` (see `postgres.py`).
"""

from typing import Any

from postgres import needs_postgres, run

from poiesis.api.tes.models import TesExecutor, TesState, TesTask
from poiesis.db import tasks as tasks_db
from poiesis.db.tasks import ListFilters, TaskView

pytestmark = needs_postgres
OWNER = "https://kc.example.org/realms/poiesis|alice"


def test_minimal_get_and_list_show_id_and_state_only() -> None:
    """GetTask and ListTasks agree, and serialise as the routes do to id and state."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            task_id = await tasks_db.create_task(
                conn,
                TesTask(
                    state=TesState.QUEUED,
                    name="n",
                    creation_time="2000-01-01T00:00:00+00:00",
                    executors=[TesExecutor(image="alpine", command=["true"])],
                ),
                OWNER,
            )
            got = await tasks_db.get_task(conn, task_id, TaskView.MINIMAL)
            (listed,), _ = await tasks_db.list_tasks(
                conn, ListFilters(), TaskView.MINIMAL
            )
        assert got is not None
        assert got == listed
        # The executors list is required by the schema, so it stays, empty.
        assert listed.model_dump(mode="json", exclude_none=True) == {
            "id": task_id,
            "state": "QUEUED",
            "executors": [],
        }

    run(test)
