"""Tests for task tags with null values (issue #71).

Cromwell sends ``"parent_workflow_id": null`` for a root workflow. TES
tags are strings, so Poiesis drops tags whose value is null and accepts
the task; other non-string values still get 422. The real app runs with
auth off and fake tasks, database and cluster.
"""

import contextlib
import logging
from collections.abc import AsyncIterator, Iterator
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from poiesis.api import app as app_module
from poiesis.api.routes import tasks as tasks_routes
from poiesis.api.tes.models import TesTask

TASKS = "/ga4gh/tes/v1/tasks"
TASK = {"executors": [{"image": "alpine", "command": ["true"]}]}
#: The tags Cromwell sent in issue #71.
CROMWELL_TAGS = {
    "workflow_id": "03f8b895-2bfa-4a12-ae5b-0a44dda07b68",
    "root_workflow_id": "03f8b895-2bfa-4a12-ae5b-0a44dda07b68",
    "parent_workflow_id": None,
}


class Pool:
    """Stands in for the asyncpg pool (the fakes ignore the connection)."""

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        """Hand out a dummy connection."""
        yield None

    async def close(self) -> None:
        """Nothing to close."""


class K8s:
    """Accepts every Job and PVC."""

    async def create_job(self, *_: Any) -> Any:
        """Return a created Job."""
        return SimpleNamespace(metadata=SimpleNamespace(uid="uid", name="job"))

    async def create_pvc(self, *_: Any) -> None:
        """Accept the PVC."""


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[str, TesTask]:
    """Fake task storage and cluster for the TES routes; tasks by id."""
    tasks: dict[str, TesTask] = {}

    async def create_task(_: Any, task: TesTask, *__: Any) -> str:
        assert task.id is not None
        tasks[task.id] = task
        return task.id

    async def get_task_meta(_: Any, task_id: str) -> dict[str, Any] | None:
        if task_id not in tasks:
            return None
        meta = {"state": "QUEUED", "tags": tasks[task_id].tags or {}}
        return meta | {"owner": "__anonymous__", "groups": []}

    async def get_task(_: Any, task_id: str, **__: Any) -> TesTask | None:
        return tasks.get(task_id)

    for function in (create_task, get_task_meta, get_task):
        monkeypatch.setattr(tasks_routes.tasks_db, function.__name__, function)
    monkeypatch.setattr(
        tasks_routes, "build_taskpod_job", lambda *_: (SimpleNamespace(), None)
    )
    monkeypatch.setattr(tasks_routes, "attach_pvc_owner", lambda *_: None)
    return tasks


@pytest.fixture
def client(
    stored: dict[str, TesTask], monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """The started real app with auth off and fake database and cluster."""

    async def create_pool(_: str, **__: Any) -> Pool:
        return Pool()

    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    monkeypatch.setattr(app_module, "create_pool", create_pool)
    monkeypatch.setattr(app_module, "load_config", lambda: None)
    monkeypatch.setattr(app_module, "K8sClient", K8s)
    with TestClient(app_module.create_app()) as test_client:
        yield test_client


def create(client: TestClient, tags: Any) -> Any:
    """POST a task with `tags`; return the response."""
    return client.post(TASKS, json=TASK | {"tags": tags})


def test_cromwell_null_tag_dropped(
    client: TestClient, stored: dict[str, TesTask], caplog: pytest.LogCaptureFixture
) -> None:
    """Cromwell's null tag is dropped, the others kept, the drop logged."""
    caplog.set_level(logging.DEBUG, logger="poiesis.api.tes.models")
    response = create(client, CROMWELL_TAGS)
    assert response.status_code == HTTPStatus.OK, response.text
    task_id = response.json()["id"]
    kept = {"workflow_id": CROMWELL_TAGS["workflow_id"]}
    kept["root_workflow_id"] = CROMWELL_TAGS["root_workflow_id"]
    assert stored[task_id].tags == kept

    task = client.get(f"{TASKS}/{task_id}", params={"view": "FULL"})
    assert task.status_code == HTTPStatus.OK, task.text
    assert task.json()["tags"] == kept

    dropped = [r for r in caplog.records if r.name == "poiesis.api.tes.models"]
    assert len(dropped) == 1
    assert dropped[0].levelno == logging.DEBUG
    assert "parent_workflow_id" in dropped[0].getMessage()
    assert CROMWELL_TAGS["workflow_id"] not in dropped[0].getMessage()


def test_all_null_tags_stored_empty(
    client: TestClient, stored: dict[str, TesTask]
) -> None:
    """All tags null leaves an empty map, stored as `{}` like an empty one."""
    response = create(client, {"a": None, "b": None})
    assert response.status_code == HTTPStatus.OK, response.text
    assert stored[response.json()["id"]].tags == {}


def test_no_null_tags_untouched(
    client: TestClient, stored: dict[str, TesTask], caplog: pytest.LogCaptureFixture
) -> None:
    """Tags without nulls are kept as sent and nothing is logged."""
    caplog.set_level(logging.DEBUG, logger="poiesis.api.tes.models")
    response = create(client, {"project": "x", "empty": ""})
    assert response.status_code == HTTPStatus.OK, response.text
    assert stored[response.json()["id"]].tags == {"project": "x", "empty": ""}
    assert not [r for r in caplog.records if r.name == "poiesis.api.tes.models"]


@pytest.mark.parametrize(
    "tags",
    [
        {"run": 1, "parent": None},
        {"run": {"id": "x"}},
        {"run": ["x"]},
        {"run": True},
        ["run"],
    ],
    ids=["number", "object", "list", "bool", "not-a-map"],
)
def test_other_non_string_tags_refused(
    client: TestClient, stored: dict[str, TesTask], tags: Any
) -> None:
    """Numbers, objects, lists and booleans still get 422; nothing stored."""
    response = create(client, tags)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
    assert not stored


def test_model_drops_null_tags() -> None:
    """The model itself drops null tags, so every caller sees the same."""
    task = TesTask.model_validate(TASK | {"tags": CROMWELL_TAGS})
    assert task.tags is not None
    assert "parent_workflow_id" not in task.tags
    assert TesTask.model_validate(TASK | {"tags": None}).tags is None
