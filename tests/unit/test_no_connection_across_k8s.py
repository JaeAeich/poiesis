"""No pooled database connection is held across a Kubernetes call (#164).

CreateTask kept its connection while it created the Job and the PVC: a slow
API server and a burst of submissions drained the pool, and `/readyz`, which
needs a connection too, took every replica out of the Service.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from kubernetes.client import V1Job, V1ObjectMeta
from kubernetes.client.exceptions import ApiException

from poiesis.api.exceptions import (
    BadRequestError,
    InternalServerError,
    ServiceUnavailableError,
)
from poiesis.api.routes import tasks as tasks_routes
from poiesis.api.tes.models import TesCancelTaskResponse, TesState

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

TASK = "00000000-0000-4000-8000-000000000001"


class Fakes:
    """A pool that counts held connections, and a Kubernetes that checks it."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.held = 0
        self.calls: list[str] = []
        self.errors: dict[str, ApiException] = {}
        self.terminal: list[tuple[TesState, str]] = []
        self.system_logs: list[str] = []
        self.state = TesState.RUNNING
        monkeypatch.setattr(tasks_routes.tasks_db, "create_task", self.create_row)
        monkeypatch.setattr(tasks_routes.tasks_db, "get_task_meta", self.meta)
        monkeypatch.setattr(tasks_routes.state_db, "mark_canceling", self.mark)
        monkeypatch.setattr(
            tasks_routes.state_db, "write_terminal_state", self.write_terminal
        )
        monkeypatch.setattr(tasks_routes.state_db, "append_system_log", self.log)
        monkeypatch.setattr(
            tasks_routes, "build_taskpod_job", lambda *_: (SimpleNamespace(), None)
        )
        monkeypatch.setattr(tasks_routes, "attach_pvc_owner", lambda *_: None)

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[Fakes]:
        self.held += 1
        try:
            yield self
        finally:
            self.held -= 1

    def _k8s(self, call: str) -> None:
        assert self.held == 0, f"{call} called while holding a connection"
        self.calls.append(call)
        if call in self.errors:
            raise self.errors[call]

    async def create_job(self, _namespace: str, _job: Any) -> V1Job:
        await asyncio.sleep(0)
        self._k8s("create_job")
        return V1Job(metadata=V1ObjectMeta(uid="uid-1", name=f"task-{TASK}"))

    async def create_pvc(self, _namespace: str, _pvc: Any) -> None:
        await asyncio.sleep(0)
        self._k8s("create_pvc")

    async def delete_job(self, _namespace: str, _name: str) -> None:
        await asyncio.sleep(0)
        self._k8s("delete_job")

    async def create_row(self, conn: Any, *_: Any) -> str:
        assert conn is self
        assert self.held == 1
        return TASK

    async def meta(self, *_: Any) -> dict[str, Any]:
        return {"owner": "o", "state": self.state.value, "tags": {}, "groups": []}

    async def mark(self, *_: Any) -> bool:
        self.state = TesState.CANCELING
        return True

    async def write_terminal(
        self, _conn: Any, _task_id: str, state: TesState, *, reason: str
    ) -> None:
        assert self.held == 1
        self.terminal.append((state, reason))

    async def log(self, _conn: Any, _task_id: str, message: str) -> None:
        assert self.held == 1
        self.system_logs.append(message)

    async def check_create(self, *_: Any) -> list[str]:
        return []

    async def check_cancel(self, *_: Any) -> None:
        pass

    def create(self) -> Any:
        fakes: Any = self
        task: Any = tasks_routes.TesTask.model_validate(
            {"executors": [{"image": "alpine", "command": ["true"]}]}
        )
        config: Any = SimpleNamespace(taskpod_namespace="tasks")
        principal: Any = SimpleNamespace(owner="o")
        return asyncio.run(
            tasks_routes.create_task(task, fakes, config, principal, fakes, fakes)
        )


def test_create_task_releases_the_connection_before_kubernetes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes = Fakes(monkeypatch)
    assert fakes.create().id == TASK
    assert fakes.calls == ["create_job", "create_pvc"]
    assert fakes.held == 0
    assert fakes.terminal == []


@pytest.mark.parametrize(
    ("call", "exc", "error", "calls"),
    [
        (
            "create_job",
            ApiException(status=403, reason="Forbidden"),
            ServiceUnavailableError,
            ["create_job"],
        ),
        (
            "create_job",
            ApiException(status=500, reason="Internal"),
            InternalServerError,
            ["create_job"],
        ),
        (
            "create_pvc",
            ApiException(status=404, reason="Not Found"),
            BadRequestError,
            ["create_job", "create_pvc", "delete_job"],
        ),
    ],
    ids=["job-403", "job-500", "pvc-404"],
)
def test_submit_failure_marks_system_error_without_holding_a_connection(
    monkeypatch: pytest.MonkeyPatch,
    call: str,
    exc: ApiException,
    error: type[Exception],
    calls: list[str],
) -> None:
    """Same responses and SYSTEM_ERROR write as before; no connection held."""
    fakes = Fakes(monkeypatch)
    fakes.errors[call] = exc
    with pytest.raises(error) as raised:
        fakes.create()
    assert fakes.calls == calls
    ((state, reason),) = fakes.terminal
    assert state is TesState.SYSTEM_ERROR
    assert fakes.system_logs == [reason]
    assert str(raised.value.args[0]) == reason
    assert fakes.held == 0


def test_cancel_task_releases_the_connection_before_kubernetes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes = Fakes(monkeypatch)
    config: Any = SimpleNamespace(taskpod_namespace="tasks")
    principal: Any = SimpleNamespace()
    fake: Any = fakes
    response = asyncio.run(
        tasks_routes.cancel_task(TASK, fake, config, principal, fake, fake)
    )
    assert response == TesCancelTaskResponse()
    assert fakes.calls == ["delete_job"]
