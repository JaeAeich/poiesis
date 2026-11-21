"""trec connects per write and retries while Postgres is down (#164).

trec held one connection for the task's whole life, so N running tasks held
N Postgres connections, and a dropped connection ended trec.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import asyncpg
import pytest

from poiesis.core import trec
from poiesis.core.k8s_watch import PodEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

FINISHED = {
    "terminated": {
        "exit_code": 0,
        "started_at": "2026-11-22T10:00:00+00:00",
        "finished_at": "2026-11-22T10:00:05+00:00",
    }
}
RUNNING = {"running": {"started_at": "2026-11-22T10:00:00+00:00"}}


def status(phase: str, exec_0: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": phase,
        "init_container_statuses": [{"name": "exec-0", "state": exec_0}],
    }


class FakeConn:
    def __init__(self, postgres: Postgres) -> None:
        self.postgres = postgres

    async def close(self, *, timeout: float) -> None:
        assert timeout > 0
        self.postgres.open -= 1

    def terminate(self) -> None:  # pragma: no cover - close never fails here
        self.postgres.open -= 1


class Postgres:
    """`asyncpg.connect` that fails while `down` > 0, and counts open connections."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, down: int = 0) -> None:
        self.down = down
        self.error: Exception = OSError("connection refused")
        self.attempts = 0
        self.open = 0
        self.rows: list[dict[str, Any]] = []
        monkeypatch.setattr(trec.asyncpg, "connect", self.connect)
        monkeypatch.setattr(trec, "_CONNECT_BACKOFF_SECONDS", (0, 0, 0))
        monkeypatch.setattr(trec.state_db, "append_executor_log", self.append)
        monkeypatch.setattr(trec, "_mark_running", self.mark_running)

        async def read_streams(*_: Any) -> tuple[None, None]:
            return None, None

        monkeypatch.setattr(trec, "read_executor_streams", read_streams)

    async def connect(self, _dsn: str, **kwargs: Any) -> FakeConn:
        assert kwargs["timeout"] > 0
        assert kwargs["command_timeout"] > 0
        self.attempts += 1
        if self.down > 0:
            self.down -= 1
            raise self.error
        self.open += 1
        return FakeConn(self)

    async def append(self, conn: FakeConn, _task_id: str, **row: Any) -> None:
        assert self.open == 1
        assert conn.postgres is self
        self.rows.append(row)

    async def mark_running(self, _conn: FakeConn, _task_id: str) -> None:
        assert self.open == 1
        self.rows.append({"state": "RUNNING"})


async def statement(conn: FakeConn, task_id: str) -> None:
    conn.postgres.rows.append({"task": task_id})


def test_write_retries_until_postgres_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    postgres = Postgres(monkeypatch, down=2)
    asyncio.run(trec._Database("dsn").write(statement, "t1"))
    assert postgres.rows == [{"task": "t1"}]
    assert postgres.attempts == 3  # noqa: PLR2004
    assert postgres.open == 0


def test_write_gives_up_after_the_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Then trec exits and the kubelet restarts it; it records the Pod anew."""
    postgres = Postgres(monkeypatch, down=99)
    with pytest.raises(OSError, match="refused"):
        asyncio.run(trec._Database("dsn").write(statement, "t1"))
    assert postgres.attempts == 4  # noqa: PLR2004
    assert postgres.rows == []


def test_bad_credentials_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    postgres = Postgres(monkeypatch, down=1)
    postgres.error = asyncpg.InvalidPasswordError("password authentication failed")
    with pytest.raises(asyncpg.InvalidPasswordError):
        asyncio.run(trec._Database("dsn").write(statement, "t1"))
    assert postgres.attempts == 1


def watch(postgres: Postgres, *statuses: dict[str, Any]) -> Any:
    """A Pod watch that checks no connection is open while it waits."""

    async def events(*_: Any) -> AsyncIterator[PodEvent]:
        for pod_status in statuses:
            assert postgres.open == 0, "connection held between events"
            yield PodEvent(type="MODIFIED", pod={"status": pod_status})
        await asyncio.Event().wait()

    return events


def run_trec(monkeypatch: pytest.MonkeyPatch, sigterm: asyncio.Event) -> int:
    monkeypatch.setattr(trec, "_install_signal_handlers", lambda: sigterm)

    async def main() -> int:
        async with asyncio.timeout(5):
            db = trec._Database("dsn")
            return await trec._run_until_terminal(db, "t1", "pod-1", "tasks", {})

    return asyncio.run(main())


def test_no_connection_is_held_and_no_event_is_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Postgres down at the executor's finish: the row is written once it's back."""
    postgres = Postgres(monkeypatch)

    async def mark_running(_conn: FakeConn, _task_id: str) -> None:
        postgres.rows.append({"state": "RUNNING"})
        postgres.down = 2  # down when exec-0's row is written next

    monkeypatch.setattr(trec, "_mark_running", mark_running)
    monkeypatch.setattr(
        trec,
        "watch_pods",
        watch(postgres, status("Running", RUNNING), status("Succeeded", FINISHED)),
    )

    assert run_trec(monkeypatch, asyncio.Event()) == 0
    running, row = postgres.rows
    assert running == {"state": "RUNNING"}
    assert (row["ordinal"], row["exit_code"]) == (0, 0)
    assert postgres.open == 0


class FakeCoreV1:
    def read_namespaced_pod(self, **_: Any) -> Any:
        pod = status("Running", FINISHED)
        return type("Pod", (), {"to_dict": lambda _self: {"status": pod}})()


def test_sigterm_during_an_outage_stops_waiting_and_records_on_the_last_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """trec stops retrying at SIGTERM; the last read writes what was pending."""
    postgres = Postgres(monkeypatch, down=2)
    monkeypatch.setattr(trec, "_CONNECT_BACKOFF_SECONDS", (60, 60, 60))
    monkeypatch.setattr(
        trec, "watch_pods", watch(postgres, status("Running", FINISHED))
    )
    monkeypatch.setattr(trec.client, "CoreV1Api", FakeCoreV1)
    sigterm = asyncio.Event()

    async def stop_soon() -> None:
        await asyncio.sleep(0.05)
        sigterm.set()

    original = trec._run_until_terminal

    async def with_sigterm(*args: Any) -> int:
        stopper = asyncio.create_task(stop_soon())
        try:
            return await original(*args)
        finally:
            await stopper

    monkeypatch.setattr(trec, "_run_until_terminal", with_sigterm)
    started = time.monotonic()
    assert run_trec(monkeypatch, sigterm) == 0
    assert time.monotonic() - started < 2  # noqa: PLR2004
    running, row = postgres.rows
    assert running == {"state": "RUNNING"}
    assert (row["ordinal"], row["exit_code"]) == (0, 0)
    assert postgres.attempts == 4  # noqa: PLR2004
    assert postgres.open == 0
