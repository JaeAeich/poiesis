"""tctl's task gauges come from one grouped count (#175), on Postgres.

Skipped without ``POIESIS_TEST_DATABASE_URL`` (see `postgres.py`).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from postgres import needs_postgres, run

from poiesis.api.tes.models import TesExecutor, TesState, TesTask
from poiesis.db import state as state_db
from poiesis.db import tasks as tasks_db

pytestmark = needs_postgres
OWNER = "alice"


def test_tasks_are_counted_by_state_with_the_oldest_age() -> None:
    """Each state's count, and how long ago its oldest task was created."""

    async def test(pool: Any) -> None:
        now = datetime.now(UTC)
        async with pool.acquire() as conn:
            for state, age in (
                (TesState.QUEUED, 600),
                (TesState.QUEUED, 10),
                (TesState.RUNNING, 60),
                (TesState.COMPLETE, 9000),
            ):
                await tasks_db.create_task(
                    conn,
                    TesTask(
                        state=state,
                        creation_time=(now - timedelta(seconds=age)).isoformat(),
                        executors=[TesExecutor(image="alpine", command=["true"])],
                    ),
                    OWNER,
                )
            counts = await state_db.count_tasks_by_state(conn)
        assert set(counts) == {"QUEUED", "RUNNING", "COMPLETE"}
        assert counts["QUEUED"][0] == 2  # noqa: PLR2004
        assert counts["RUNNING"][0] == 1
        assert 590 < (counts["QUEUED"][1] or 0) < 700  # noqa: PLR2004
        assert 50 < (counts["RUNNING"][1] or 0) < 160  # noqa: PLR2004

    run(test)
