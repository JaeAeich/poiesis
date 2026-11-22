"""CancelTask deletes the Job whenever the task is CANCELING (#155).

A cancel marks the row `CANCELING`, then deletes the Job. If that delete
failed, the retry saw "already CANCELING" and returned 200 without deleting:
the task ran until its deadline.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from poiesis.api.exceptions import InternalServerError
from poiesis.api.routes import tasks as tasks_routes
from poiesis.api.tes.models import TesCancelTaskResponse, TesState
from poiesis.k8s import K8sClient, K8sRejectedError
from poiesis.k8s import client as k8s_client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

TASK = "00000000-0000-4000-8000-000000000001"


class Fakes:
    """One task row, and a Kubernetes that records the Job deletes."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, state: TesState) -> None:
        self.state = state
        self.deletes: list[tuple[str, str]] = []
        self.delete_errors: list[K8sRejectedError] = []
        monkeypatch.setattr(tasks_routes.tasks_db, "get_task_meta", self.meta)
        monkeypatch.setattr(tasks_routes.state_db, "mark_canceling", self.mark)

    async def meta(self, _conn: Any, _task_id: str) -> dict[str, Any]:
        return {"owner": "o", "state": self.state.value, "tags": {}, "groups": []}

    async def mark(self, _conn: Any, _task_id: str) -> bool:
        if self.state in {TesState.QUEUED, TesState.RUNNING}:
            self.state = TesState.CANCELING
            return True
        return False

    async def delete_job(self, namespace: str, name: str) -> None:
        self.deletes.append((namespace, name))
        if self.delete_errors:
            raise self.delete_errors.pop(0)

    async def check_cancel(self, *_: Any) -> None:
        pass

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        yield None

    def cancel(self) -> TesCancelTaskResponse:
        fakes: Any = self
        config: Any = SimpleNamespace(taskpod_namespace="tasks")
        principal: Any = SimpleNamespace()
        return asyncio.run(
            tasks_routes.cancel_task(TASK, fakes, config, principal, fakes, fakes)
        )


JOB = ("tasks", f"task-{TASK}")


def test_first_cancel_deletes_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    fakes = Fakes(monkeypatch, TesState.RUNNING)
    assert fakes.cancel() == TesCancelTaskResponse()
    assert fakes.state is TesState.CANCELING
    assert fakes.deletes == [JOB]


def test_retry_after_a_failed_delete_deletes_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first cancel gets a 500; the retry deletes instead of returning 200."""
    fakes = Fakes(monkeypatch, TesState.RUNNING)
    fakes.delete_errors = [K8sRejectedError(500, "boom")]
    with pytest.raises(InternalServerError):
        fakes.cancel()
    assert fakes.state is TesState.CANCELING
    assert fakes.cancel() == TesCancelTaskResponse()
    assert fakes.deletes == [JOB, JOB]


def test_cancel_of_a_canceling_task_whose_job_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The repeated delete is sent, and a missing Job is success."""
    fakes = Fakes(monkeypatch, TesState.CANCELING)
    assert fakes.cancel() == TesCancelTaskResponse()
    assert fakes.deletes == [JOB]


def _client_whose_delete_answers(status: int) -> K8sClient:
    def delete_namespaced_job(**_: Any) -> None:
        raise k8s_client.ApiException(status=status, reason="nope")

    client = K8sClient.__new__(K8sClient)
    batch: Any = SimpleNamespace(delete_namespaced_job=delete_namespaced_job)
    client._batch = batch
    return client


def test_deleting_a_job_that_is_gone_succeeds() -> None:
    """A 404 from the delete is success."""
    asyncio.run(_client_whose_delete_answers(404).delete_job("tasks", "task-1"))


def test_a_refused_delete_is_an_error() -> None:
    with pytest.raises(K8sRejectedError) as refused:
        asyncio.run(_client_whose_delete_answers(403).delete_job("tasks", "task-1"))
    assert refused.value.status == 403


@pytest.mark.parametrize(
    "state", [TesState.COMPLETE, TesState.CANCELED, TesState.SYSTEM_ERROR]
)
def test_cancel_of_a_terminal_task_deletes_nothing(
    monkeypatch: pytest.MonkeyPatch, state: TesState
) -> None:
    """The finished Job and its PVC stay until the Job's TTL."""
    fakes = Fakes(monkeypatch, state)
    assert fakes.cancel() == TesCancelTaskResponse()
    assert fakes.deletes == []
