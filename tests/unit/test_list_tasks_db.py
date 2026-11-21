"""ListTasks batching, indexes and `name_prefix` escaping (#167, #166), on Postgres.

Skipped without ``POIESIS_TEST_DATABASE_URL`` (see `postgres.py`).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from postgres import needs_postgres, run

from poiesis.api.tes.models import (
    TesExecutor,
    TesExecutorLog,
    TesInput,
    TesOutput,
    TesOutputFileLog,
    TesState,
    TesTask,
    TesTaskLog,
)
from poiesis.db import tasks as tasks_db
from poiesis.db.tasks import ListFilters, TaskView

pytestmark = needs_postgres
OWNER = "https://kc.example.org/realms/poiesis|alice"
START = datetime(2026, 1, 1, tzinfo=UTC)


def rich_task(index: int) -> TesTask:
    """A task with several of each child row, so ordering matters."""
    return TesTask(
        name=f"task-{index}",
        description="d",
        state=TesState.COMPLETE,
        inputs=[TesInput(path=f"/in/{i}", content=f"c{i}", url=None) for i in range(3)]
        + [TesInput(path="/in/url", url="s3://b/k")],
        outputs=[TesOutput(path=f"/out/{i}", url=f"s3://b/{i}") for i in range(3)],
        executors=[
            TesExecutor(image=f"alpine:{i}", command=["echo", str(i)], env={"I": "1"})
            for i in range(3)
        ],
        logs=[
            TesTaskLog(
                logs=[
                    TesExecutorLog(exit_code=e, stdout=f"o{e}", stderr=f"e{e}")
                    for e in range(3)
                ],
                outputs=[
                    TesOutputFileLog(url="s3://b/0", path="/out/0", size_bytes="1")
                ],
                system_logs=[f"attempt {attempt}"],
                metadata={"attempt": str(attempt)},
            )
            for attempt in range(2)
        ],
        tags={"index": str(index)},
        volumes=["/vol"],
        creation_time=(START + timedelta(minutes=index)).isoformat(),
    )


async def fill(conn: Any, count: int, offset: int = 0) -> None:
    for index in range(offset, offset + count):
        await tasks_db.create_task(conn, rich_task(index), OWNER)


class CountingConnection:
    """Forward to a connection, counting the queries sent through it."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self.queries = 0

    def __getattr__(self, name: str) -> Any:
        method = getattr(self.conn, name)
        if name not in {"execute", "fetch", "fetchrow", "fetchval"}:
            return method

        async def counted(*args: Any, **kwargs: Any) -> Any:
            self.queries += 1
            return await method(*args, **kwargs)

        return counted


async def count_queries(conn: Any, view: TaskView, page_size: int) -> int:
    counting = CountingConnection(conn)
    tasks, _ = await tasks_db.list_tasks(
        counting, ListFilters(owner=OWNER, page_size=page_size), view
    )
    assert len(tasks) == page_size
    return counting.queries


@pytest.mark.parametrize("view", list(TaskView))
def test_query_count_is_constant(view: TaskView) -> None:
    """A page costs the same number of queries for 1, 5 and 20 tasks."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            await fill(conn, 20)
            counts = {n: await count_queries(conn, view, n) for n in (1, 5, 20)}
        expected = 1 if view is TaskView.MINIMAL else 6
        assert counts == dict.fromkeys(counts, expected)

    run(test)


@pytest.mark.parametrize("view", [TaskView.BASIC, TaskView.FULL])
def test_list_matches_get(view: TaskView) -> None:
    """Every listed task equals `get_task` of it, child order included."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            await fill(conn, 4)
            # A bare task: no inputs, outputs or logs beyond the default.
            await tasks_db.create_task(
                conn,
                TesTask(
                    executors=[TesExecutor(image="alpine", command=["true"])],
                    creation_time=(START + timedelta(hours=1)).isoformat(),
                ),
                OWNER,
            )
            listed, _ = await tasks_db.list_tasks(
                conn, ListFilters(owner=OWNER, page_size=10), view
            )
            single = [
                await tasks_db.get_task(conn, str(task.id), view) for task in listed
            ]
        assert len(listed) == 5
        assert listed == single
        rich = listed[1]
        assert rich.executors[2].image == "alpine:2"
        assert [i.path for i in rich.inputs or []][:3] == ["/in/0", "/in/1", "/in/2"]
        assert rich.logs is not None
        assert [log.metadata for log in rich.logs] == [
            {"attempt": "0"},
            {"attempt": "1"},
        ]
        assert [e.exit_code for e in rich.logs[1].logs] == [0, 1, 2]

    run(test)


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("100%", {"100%"}),
        ("a_b", {"a_b"}),
        ("a\\", {"a\\b"}),
        ("%", {"%x"}),
        ("_", {"_x"}),
        ("a", {"a_b", "axb", "a\\b"}),
    ],
    ids=[
        "percent",
        "underscore",
        "backslash",
        "only-percent",
        "only-underscore",
        "plain",
    ],
)
def test_name_prefix_is_literal(prefix: str, expected: set[str]) -> None:
    """`%`, `_` and `\\` in `name_prefix` match themselves only (#166)."""
    found: set[str] = set()

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            for index, name in enumerate(
                ["100%", "1000", "a_b", "axb", "a\\b", "%x", "_x"]
            ):
                await tasks_db.create_task(
                    conn,
                    TesTask(
                        name=name,
                        executors=[TesExecutor(image="alpine", command=["true"])],
                        creation_time=(START + timedelta(minutes=index)).isoformat(),
                    ),
                    OWNER,
                )
            listed, _ = await tasks_db.list_tasks(
                conn, ListFilters(owner=OWNER, name_prefix=prefix), TaskView.BASIC
            )
        found.update(task.name or "" for task in listed)

    run(test)
    assert found == expected


def test_tag_value_filter() -> None:
    """`tag_key`+`tag_value` matches the exact value; key alone matches any."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            await fill(conn, 3)
            by_value, _ = await tasks_db.list_tasks(
                conn,
                ListFilters(owner=OWNER, tag_key=["index"], tag_value=["1"]),
                TaskView.BASIC,
            )
            by_key, _ = await tasks_db.list_tasks(
                conn, ListFilters(owner=OWNER, tag_key=["index"]), TaskView.BASIC
            )
            missing, _ = await tasks_db.list_tasks(
                conn,
                ListFilters(owner=OWNER, tag_key=["index"], tag_value=["9"]),
                TaskView.BASIC,
            )
        assert [t.name for t in by_value] == ["task-1"]
        assert len(by_key) == 3
        assert missing == []

    run(test)


def test_indexes_exist() -> None:
    """The list indexes are created; the plain creation-time index is gone."""

    async def test(pool: Any) -> None:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT indexname FROM pg_indexes"
                " WHERE tablename = 'tasks' AND schemaname = current_schema()"
            )
        names = {r["indexname"] for r in rows}
        assert {
            "tasks_owner_creation_idx",
            "tasks_creation_id_idx",
            "tasks_tags_idx",
        } <= names
        assert "tasks_creation_idx" not in names

    run(test)
