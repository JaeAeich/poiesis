"""SQL tests for the task visibility of `poiesis.db.tasks` against Postgres.

The list scope of a decision service (``tes-authzen/2``) becomes the
clause ``owner = $me OR (<scope>)``; these tests check that clause, the
stored groups and pagination on a real database. Skipped without
``POIESIS_TEST_DATABASE_URL``; each test gets a freshly migrated schema
of its own (see `postgres.py`).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from postgres import needs_postgres, run

from poiesis.api.tes.models import TesExecutor, TesState, TesTask
from poiesis.db import tasks as tasks_db
from poiesis.db.tasks import ListFilters, TaskScope, TaskView

pytestmark = needs_postgres
ALICE = "https://kc.example.org/realms/poiesis|alice"
BOB = "https://kc.example.org/realms/poiesis|bob"
CAROL = "https://kc.example.org/realms/poiesis|carol"
#: name: (owner, groups, tags); created oldest first, listed newest first.
TASKS: dict[str, tuple[str, list[str], dict[str, str] | None]] = {
    "alice": (ALICE, [], None),
    "alice-alpha": (ALICE, ["lab-alpha"], {"project": "x"}),
    "bob": (BOB, [], None),
    "bob-alpha": (BOB, ["lab-alpha"], None),
    "bob-x": (BOB, [], {"project": "x", "stage": "dev"}),
    "bob-alpha-y": (BOB, ["lab-alpha", "lab-beta"], {"project": "y"}),
    "carol-alpha": (CAROL, ["lab-alpha"], None),
    "carol-z": (CAROL, [], {"project": "z"}),
    "carol-quote": (CAROL, ["it's"], {"o'k": 'a"b'}),
}
START = datetime(2026, 1, 1, tzinfo=UTC)


async def fill(pool: Any) -> dict[str, str]:
    """Create the tasks of `TASKS`; return their ids by name."""
    ids = {}
    async with pool.acquire() as conn:
        for index, (name, (owner, groups, tags)) in enumerate(TASKS.items()):
            task = TesTask(
                name=name,
                state=TesState.QUEUED,
                executors=[TesExecutor(image="alpine", command=["true"])],
                tags=tags,
                creation_time=(START + timedelta(minutes=index)).isoformat(),
            )
            ids[name] = await tasks_db.create_task(conn, task, owner, groups)
    return ids


async def names(pool: Any, filters: ListFilters, **kwargs: Any) -> set[str]:
    """Return the names of every listed task, paging through all pages."""
    found: list[str] = []
    async with pool.acquire() as conn:
        while True:
            tasks, token = await tasks_db.list_tasks(conn, filters, **kwargs)
            for task in tasks:
                meta = await tasks_db.get_task(conn, str(task.id), TaskView.BASIC)
                assert meta is not None
                assert meta.name is not None
                found.append(meta.name)
            if token is None:
                break
            filters.page_token = token
    assert len(found) == len(set(found)), "a task was listed twice"
    return set(found)


def listed(owner: str | None, scope: TaskScope | None, **filters: Any) -> set[str]:
    """Return the names `owner` sees with `scope`, in pages of 2."""
    result: set[str] = set()

    async def test(pool: Any) -> None:
        await fill(pool)
        result.update(
            await names(
                pool, ListFilters(owner=owner, scope=scope, page_size=2, **filters)
            )
        )

    run(test)
    return result


OWN = {"alice", "alice-alpha"}


@pytest.mark.parametrize(
    ("scope", "shared"),
    [
        (None, set()),
        (TaskScope(owners=(BOB,)), {"bob", "bob-alpha", "bob-x", "bob-alpha-y"}),
        (TaskScope(owners=(BOB, CAROL)), set(TASKS) - OWN),
        (TaskScope(groups=("lab-alpha",)), {"bob-alpha", "bob-alpha-y", "carol-alpha"}),
        (TaskScope(groups=("lab-beta", "lab-gamma")), {"bob-alpha-y"}),
        (TaskScope(tags=(("project", "x"),)), {"bob-x"}),
        (TaskScope(tags=(("project", "x"), ("project", "z"))), {"bob-x", "carol-z"}),
        (
            TaskScope(tags=(("stage", "dev"), ("project", "y"))),
            {"bob-x", "bob-alpha-y"},
        ),
        (TaskScope(tags=(("project", "q"),)), set()),
        (
            TaskScope(owners=(BOB,), groups=("lab-alpha",)),
            {"bob-alpha", "bob-alpha-y"},
        ),
        (
            TaskScope(groups=("lab-alpha",), tags=(("project", "y"),)),
            {"bob-alpha-y"},
        ),
        (
            TaskScope(
                owners=(BOB, CAROL), groups=("lab-alpha",), tags=(("project", "y"),)
            ),
            {"bob-alpha-y"},
        ),
        (TaskScope(owners=(CAROL,), tags=(("project", "x"),)), set()),
        (TaskScope(groups=("it's",), tags=(("o'k", 'a"b'),)), {"carol-quote"}),
        (TaskScope(owners=("' OR '1'='1",)), set()),
    ],
    ids=[
        "no-scope",
        "owner",
        "owners",
        "group",
        "groups-overlap",
        "tag",
        "tag-values-ored",
        "tag-keys-ored",
        "tag-no-match",
        "owners-and-groups",
        "groups-and-tags",
        "all-dimensions",
        "disjoint",
        "quotes",
        "injection-attempt",
    ],
)
def test_own_and_scope(scope: TaskScope | None, shared: set[str]) -> None:
    """The caller sees their own tasks and those the scope matches, once each."""
    assert listed(ALICE, scope) == OWN | shared


def test_scope_needs_owner() -> None:
    """Without an owner every task is listed; a scope doesn't narrow that."""
    assert listed(None, None) == set(TASKS)
    assert listed(None, TaskScope(owners=(BOB,))) == set(TASKS)


def test_scope_and_user_filters() -> None:
    """The caller's own filters still apply to shared tasks."""
    scope = TaskScope(groups=("lab-alpha",))
    assert listed(ALICE, scope, name_prefix="bob") == {"bob-alpha", "bob-alpha-y"}
    assert listed(ALICE, scope, tag_key=["project"], tag_value=["y"]) == {"bob-alpha-y"}
    assert listed(ALICE, scope, state=TesState.RUNNING) == set()


def test_pages_and_views() -> None:
    """Pages are newest first and complete; full views include shared tasks."""

    async def test(pool: Any) -> None:
        ids = await fill(pool)
        scope = TaskScope(owners=(BOB,))
        filters = ListFilters(owner=ALICE, scope=scope, page_size=2)
        pages = []
        async with pool.acquire() as conn:
            while True:
                tasks, token = await tasks_db.list_tasks(conn, filters, TaskView.BASIC)
                pages.append([task.name for task in tasks])
                if token is None:
                    break
                filters.page_token = token
        assert pages == [
            ["bob-alpha-y", "bob-x"],
            ["bob-alpha", "bob"],
            ["alice-alpha", "alice"],
        ]
        assert set(ids) >= {name for page in pages for name in page}

    run(test)


def test_groups_stored() -> None:
    """Groups are stored on create, empty by default, and in the task's meta."""

    async def test(pool: Any) -> None:
        ids = await fill(pool)
        task = TesTask(executors=[TesExecutor(image="alpine", command=["true"])])
        async with pool.acquire() as conn:
            default = await tasks_db.create_task(conn, task.model_copy(), ALICE)
            bob_alpha = await tasks_db.get_task_meta(conn, ids["bob-alpha-y"])
            plain = await tasks_db.get_task_meta(conn, default)
        assert bob_alpha is not None
        assert plain is not None
        assert bob_alpha["groups"] == ["lab-alpha", "lab-beta"]
        assert bob_alpha["owner"] == BOB
        assert bob_alpha["tags"] == {"project": "y"}
        assert plain["groups"] == []

    run(test)


def test_null_tags_absent() -> None:
    """A null tag dropped on input is absent in the stored jsonb (issue #71)."""

    async def test(pool: Any) -> None:
        task = TesTask.model_validate(
            {
                "name": "cromwell",
                "executors": [{"image": "alpine", "command": ["true"]}],
                "tags": {"workflow_id": "w1", "parent_workflow_id": None},
            }
        )
        empty = TesTask.model_validate(
            {
                "name": "all-null",
                "executors": [{"image": "alpine", "command": ["true"]}],
                "tags": {"parent_workflow_id": None},
            }
        )
        async with pool.acquire() as conn:
            task_id = await tasks_db.create_task(conn, task, ALICE)
            empty_id = await tasks_db.create_task(conn, empty, ALICE)
            row = await conn.fetchrow(
                "SELECT tags ? 'parent_workflow_id' AS has_key,"
                " tags @> $2::jsonb AS matches FROM tasks WHERE id = $1",
                uuid.UUID(task_id),
                json.dumps({"workflow_id": "w1"}),
            )
            meta = await tasks_db.get_task_meta(conn, empty_id)
        by_key = ListFilters(tag_key=["parent_workflow_id"])
        assert await names(pool, by_key) == set()
        assert row is not None
        assert not row["has_key"]
        assert row["matches"]
        assert meta is not None
        assert meta["tags"] == {}

    run(test)
