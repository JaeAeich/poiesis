"""Prometheus metrics of the API and tctl (#175).

The API serves `/metrics` on its own port, never on the TES API's; requests
are labelled by route template, never by raw path. tctl's metrics are set by
its control loop and reconcile pass, run here against the fakes of
`test_tctl_lease` and `test_tctl_reconcile`.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient
from kubernetes.client.exceptions import ApiException
from prometheus_client import REGISTRY
from test_readyz import FakeAsyncpgPool
from test_tctl_lease import Harness
from test_tctl_reconcile import T1, T2, World, job, pod

from poiesis.api import app as app_module
from poiesis.api import metrics
from poiesis.api.routes import tasks as tasks_routes
from poiesis.api.tes.models import TesState
from poiesis.core import metrics as metrics_server
from poiesis.core import tctl, tctl_metrics
from poiesis.db.pool import Pool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

TASKS = "/ga4gh/tes/v1/tasks"


def sample(name: str, **labels: str) -> float:
    """The current value of a sample of the default registry; 0 if absent."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def scrape(port: int) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics") as response:
        return response.read().decode()


class K8s:
    async def aclose(self) -> None:
        pass


class ClosablePool(FakeAsyncpgPool):
    async def close(self) -> None:
        pass


@pytest.fixture
def inner_pool() -> FakeAsyncpgPool:
    return ClosablePool(size=3, in_use=1, max_size=8)


@pytest.fixture
def port(monkeypatch: pytest.MonkeyPatch, inner_pool: FakeAsyncpgPool) -> int:
    """Fake database and cluster for the real app; returns its metrics port."""

    async def create_pool(_: str, **__: Any) -> Pool:
        return Pool(inner_pool, acquire_timeout=1)  # ty: ignore[invalid-argument-type]

    async def get_task_meta(*_: Any) -> None:
        return None

    monkeypatch.setattr(app_module, "create_pool", create_pool)
    monkeypatch.setattr(app_module, "load_config", lambda: None)
    monkeypatch.setattr(app_module, "K8sClient", K8s)
    monkeypatch.setattr(tasks_routes.tasks_db, "get_task_meta", get_task_meta)
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    chosen = free_port()
    monkeypatch.setenv("POIESIS_METRICS_PORT", str(chosen))
    return chosen


@pytest.fixture
def client(port: int) -> Iterator[TestClient]:
    with TestClient(app_module.create_app()) as test_client:
        yield test_client


class TestApi:
    def test_metrics_are_served_on_their_own_port(
        self, client: TestClient, port: int
    ) -> None:
        client.get(f"{TASKS}/not-a-uuid")
        body = scrape(port)
        for name in (
            "poiesis_http_requests_total",
            "poiesis_http_request_duration_seconds_bucket",
            "poiesis_http_requests_in_progress",
            "poiesis_task_submissions_total",
            "poiesis_db_pool_size",
            "poiesis_db_pool_in_use",
            "poiesis_db_pool_waiters",
        ):
            assert f"\n{name}" in body, name
        assert 'poiesis_task_submissions_total{outcome="submit_failed"}' in body

    def test_metrics_are_not_on_the_tes_api(self, client: TestClient) -> None:
        """Not reachable through the Ingress: the app has no `/metrics`."""
        assert client.get("/metrics").status_code == 404  # noqa: PLR2004
        assert all(
            getattr(r, "path", "") != "/metrics"
            for r in client.app.routes  # ty: ignore
        )

    def test_the_server_stops_with_the_app(self, port: int) -> None:
        with TestClient(app_module.create_app()):
            scrape(port)
        with pytest.raises(urllib.error.URLError):
            scrape(port)

    def test_requests_are_labelled_by_route_template(self, client: TestClient) -> None:
        """A task id never becomes a label value."""
        task_id = "00000000-0000-4000-8000-00000000abcd"
        labels = {"method": "GET", "route": f"{TASKS}/{{id}}", "status": "404"}
        before = sample("poiesis_http_requests_total", **labels)
        assert client.get(f"{TASKS}/{task_id}").status_code == 404  # noqa: PLR2004
        assert sample("poiesis_http_requests_total", **labels) == before + 1
        assert sample("poiesis_http_request_duration_seconds_count", **labels) >= 1
        exposed = REGISTRY.collect()
        values = {v for m in exposed for s in m.samples for v in s.labels.values()}
        assert task_id not in values
        assert f"{TASKS}/{task_id}" not in values

    def test_unmatched_paths_share_one_label(self, client: TestClient) -> None:
        labels = {"method": "GET", "route": "unmatched", "status": "404"}
        before = sample("poiesis_http_requests_total", **labels)
        client.get("/no/such/path/1")
        client.get("/no/such/path/2")
        assert sample("poiesis_http_requests_total", **labels) == before + 2

    def test_unknown_methods_share_one_label(self, client: TestClient) -> None:
        before = sum(
            s.value
            for m in REGISTRY.collect()
            if m.name == "poiesis_http_requests"
            for s in m.samples
            if s.name.endswith("_total") and s.labels["method"] == "other"
        )
        client.request("BREW", "/healthz")
        after = sum(
            s.value
            for m in REGISTRY.collect()
            if m.name == "poiesis_http_requests"
            for s in m.samples
            if s.name.endswith("_total") and s.labels["method"] == "other"
        )
        assert after == before + 1

    def test_pool_gauges_read_the_pool(
        self, client: TestClient, inner_pool: FakeAsyncpgPool
    ) -> None:
        assert sample("poiesis_db_pool_size") == 3  # noqa: PLR2004
        assert sample("poiesis_db_pool_max_size") == 8  # noqa: PLR2004
        assert sample("poiesis_db_pool_in_use") == 1
        inner_pool.in_use = 3
        assert sample("poiesis_db_pool_in_use") == 3  # noqa: PLR2004
        assert sample("poiesis_db_pool_waiters") == 0

    def test_metrics_port_is_strict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for bad in ("abc", "0", "70000"):
            monkeypatch.setenv("POIESIS_METRICS_PORT", bad)
            with pytest.raises(ValueError, match="POIESIS_METRICS_PORT"):
                metrics_server.metrics_port_from_env()
        monkeypatch.setenv("POIESIS_METRICS_PORT", "")
        assert metrics_server.metrics_port_from_env() is None


def test_pool_counts_its_waiters() -> None:
    """A request waiting for a connection is a waiter until it gets one."""
    gate = asyncio.Event()
    seen: list[int] = []

    class Slow(FakeAsyncpgPool):
        async def acquire(self, *, timeout: float | None) -> FakeAsyncpgPool:
            seen.append(pool.waiters())
            await gate.wait()
            return self

    slow: Any = Slow(size=1, in_use=1)
    pool = Pool(slow, acquire_timeout=1)

    async def main() -> None:
        async def use() -> None:
            async with pool.acquire():
                pass

        first = asyncio.create_task(use())
        second = asyncio.create_task(use())
        await asyncio.sleep(0)
        assert pool.waiters() == 2  # noqa: PLR2004
        gate.set()
        await asyncio.gather(first, second)

    asyncio.run(main())
    assert seen == [1, 2]
    assert pool.waiters() == 0


class Submit:
    """CreateTask with its database and Kubernetes faked."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.job_error: Exception | None = None

        async def create_task(*_: Any) -> str:
            return T1

        async def noop(*_: Any, **__: Any) -> None:
            pass

        monkeypatch.setattr(tasks_routes.tasks_db, "create_task", create_task)
        monkeypatch.setattr(tasks_routes.state_db, "write_terminal_state", noop)
        monkeypatch.setattr(tasks_routes.state_db, "append_system_log", noop)
        monkeypatch.setattr(tasks_routes, "attach_pvc_owner", lambda *_: None)
        monkeypatch.setattr(
            tasks_routes, "build_taskpod_job", lambda *_: (SimpleNamespace(), None)
        )

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[Submit]:
        yield self

    async def create_job(self, *_: Any) -> Any:
        if self.job_error is not None:
            raise self.job_error
        return SimpleNamespace(metadata=SimpleNamespace(uid="u", name="n"))

    async def create_pvc(self, *_: Any) -> None:
        pass

    async def check_create(self, *_: Any) -> list[str]:
        return []

    def run(self) -> None:
        fakes: Any = self
        task: Any = tasks_routes.TesTask.model_validate(
            {"executors": [{"image": "alpine", "command": ["true"]}]}
        )
        config: Any = SimpleNamespace(taskpod_namespace="tasks")
        principal: Any = SimpleNamespace(owner="o")
        asyncio.run(
            tasks_routes.create_task(task, fakes, config, principal, fakes, fakes)
        )


def test_task_submissions_are_counted_by_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def outcomes() -> dict[str, float]:
        return {
            o.value: sample("poiesis_task_submissions_total", outcome=o.value)
            for o in metrics.SubmitOutcome
        }

    submit = Submit(monkeypatch)
    before = outcomes()
    submit.run()
    submit.job_error = ApiException(status=500, reason="boom")
    with pytest.raises(tasks_routes.APIError):
        submit.run()

    def refuse(*_: Any) -> Any:
        raise ValueError("unsupported input URL")

    monkeypatch.setattr(tasks_routes, "build_taskpod_job", refuse)
    with pytest.raises(tasks_routes.BadRequestError):
        submit.run()
    after = outcomes()
    assert {k: after[k] - before[k] for k in after} == {
        "created": 1,
        "rejected": 1,
        "submit_failed": 1,
    }


class TestTctl:
    def test_terminal_transitions_are_counted_by_state_and_check(
        self, world: World
    ) -> None:
        orphan = {"state": "SYSTEM_ERROR", "reason": "orphan"}
        complete = {"state": "COMPLETE", "reason": "pod-terminal"}
        before = (
            sample("poiesis_tctl_terminal_transitions_total", **orphan),
            sample("poiesis_tctl_terminal_transitions_total", **complete),
        )
        world.states[T1] = TesState.QUEUED
        world.states[T2] = TesState.RUNNING
        world.pods = [pod(T2, "Succeeded")]
        world.tick()
        world.tick(after=31)
        assert sample("poiesis_tctl_terminal_transitions_total", **orphan) == (
            before[0] + 1
        )
        assert sample("poiesis_tctl_terminal_transitions_total", **complete) == (
            before[1] + 1
        )

    def test_a_cancel_counts_as_canceled(self, world: World) -> None:
        labels = {"state": "CANCELED", "reason": "pod-terminal"}
        before = sample("poiesis_tctl_terminal_transitions_total", **labels)
        world.states[T1] = TesState.CANCELING
        world.jobs = [job(T1)]
        world.pods = [pod(T1, "Failed")]
        world.tick()
        assert sample("poiesis_tctl_terminal_transitions_total", **labels) == (
            before + 1
        )

    def test_unknown_check_names_share_one_label(self) -> None:
        labels = {"state": "SYSTEM_ERROR", "reason": "other"}
        before = sample("poiesis_tctl_terminal_transitions_total", **labels)
        tctl_metrics.count_transition(TesState.SYSTEM_ERROR, "free text 123")
        assert sample("poiesis_tctl_terminal_transitions_total", **labels) == (
            before + 1
        )

    def test_kubernetes_errors_are_counted_by_operation(self, world: World) -> None:
        labels = {"operation": "list_pods"}
        before = sample("poiesis_tctl_kubernetes_errors_total", **labels)
        world.list_errors[("pods", None)] = ApiException(status=500)
        with pytest.raises(ApiException):
            world.tick()
        assert sample("poiesis_tctl_kubernetes_errors_total", **labels) == before + 1

    def test_failed_job_delete_is_counted(self, world: World) -> None:
        labels = {"operation": "delete_job"}
        before = sample("poiesis_tctl_kubernetes_errors_total", **labels)
        world.states[T1] = TesState.CANCELING
        world.jobs = [job(T1)]
        world.delete_error = ApiException(status=500)
        world.tick()
        assert sample("poiesis_tctl_kubernetes_errors_total", **labels) == before + 1


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    return World(monkeypatch)


class GaugePool:
    """The pool `Harness` gives tctl, answering the grouped task count."""

    def __init__(self) -> None:
        self.counts = {"QUEUED": (4, 120.5), "RUNNING": (2, 30.0), "COMPLETE": (9, 9e3)}
        self.queries = 0

    async def close(self) -> None:
        pass

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[GaugePool]:
        yield self


def test_control_loop_sets_leader_reconcile_and_task_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(monkeypatch)
    gauge_pool = GaugePool()

    async def create_pool(*_: Any, **__: Any) -> GaugePool:
        return gauge_pool

    async def count(_conn: Any) -> dict[str, tuple[int, float | None]]:
        gauge_pool.queries += 1
        return gauge_pool.counts

    leader_during_pass: list[float] = []

    async def during_pass(_still_leader: Any) -> None:
        leader_during_pass.append(sample("poiesis_tctl_is_leader"))

    harness.during_pass = during_pass
    harness.passes = 3
    monkeypatch.setattr(tctl.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(tctl.state_db, "count_tasks_by_state", count)
    monkeypatch.setattr(tctl, "_RECONCILE_INTERVAL_SECONDS", 0)
    seen: dict[str, float] = {}
    real_clear = tctl_metrics.clear_task_gauges

    def clear() -> None:
        seen.update(
            queued=sample("poiesis_tasks", state="QUEUED"),
            complete=sample("poiesis_tasks", state="COMPLETE"),
            canceled=sample("poiesis_tasks", state="CANCELED"),
            oldest_queued=sample("poiesis_tasks_oldest_age_seconds", state="QUEUED"),
            oldest_paused=sample("poiesis_tasks_oldest_age_seconds", state="PAUSED"),
        )
        real_clear()

    monkeypatch.setattr(tctl_metrics, "clear_task_gauges", clear)
    passes = sample("poiesis_tctl_reconcile_duration_seconds_count")

    assert harness.run() == 0

    assert leader_during_pass == [1, 1, 1]
    assert sample("poiesis_tctl_is_leader") == 0  # stood down on shutdown
    assert sample("poiesis_tctl_reconcile_duration_seconds_count") == passes + 3
    assert sample("poiesis_tctl_reconcile_last_success_timestamp_seconds") > 0
    # Bounded: one grouped query per interval, not per pass.
    assert gauge_pool.queries == 1
    assert seen == {
        "queued": 4,
        "complete": 9,
        "canceled": 0,
        "oldest_queued": 120.5,
        "oldest_paused": 0,
    }
    # A standby doesn't report task counts.
    assert REGISTRY.get_sample_value("poiesis_tasks", {"state": "QUEUED"}) is None


def test_failed_pass_and_lease_renewal_are_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(monkeypatch)
    errors = sample("poiesis_tctl_reconcile_errors_total")
    renew_failures = sample("poiesis_tctl_lease_renew_failures_total")
    lease_errors = sample("poiesis_tctl_kubernetes_errors_total", operation="lease")
    calls = 0

    async def failing_pass(*_: Any, **__: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            msg = "database went away"
            raise RuntimeError(msg)
        harness.failures.append(ApiException(status=500))
        await asyncio.sleep(0.05)  # the renewer fails meanwhile
        harness.cancelled.set()

    monkeypatch.setattr(tctl, "_reconcile_once", failing_pass)
    monkeypatch.setattr(tctl, "_RECONCILE_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(tctl, "_refresh_task_gauges", lambda _pool: asyncio.sleep(0))

    assert harness.run() == 0
    assert sample("poiesis_tctl_reconcile_errors_total") == errors + 1
    assert sample("poiesis_tctl_lease_renew_failures_total") == renew_failures + 1
    assert (
        sample("poiesis_tctl_kubernetes_errors_total", operation="lease")
        == lease_errors + 1
    )


def test_tctl_serves_metrics_on_its_port(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch)
    port = free_port()
    body: list[str] = []

    async def during_pass(_still_leader: Any) -> None:
        body.append(await asyncio.to_thread(scrape, port))

    harness.during_pass = during_pass
    monkeypatch.setattr(tctl, "_refresh_task_gauges", lambda _pool: asyncio.sleep(0))
    assert harness.run(metrics_port=port) == 0
    for name in (
        "poiesis_tctl_is_leader 1.0",
        "poiesis_tctl_reconcile_duration_seconds_bucket",
        "poiesis_tctl_reconcile_last_success_timestamp_seconds",
        "# TYPE poiesis_tctl_terminal_transitions_total counter",
        'poiesis_tctl_kubernetes_errors_total{operation="list_jobs"}',
        "poiesis_tctl_lease_renew_failures_total",
    ):
        assert name in body[0], name
    with pytest.raises(urllib.error.URLError):
        scrape(port)
