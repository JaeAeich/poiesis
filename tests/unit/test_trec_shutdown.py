"""trec exits promptly on SIGTERM, and its stop isn't a task failure (#146).

trec, the native sidecar, logged "SIGTERM received; exiting" but kept
running: the blocking Pod watch ran on the event loop's default executor,
which `asyncio.run` waits for on its way out. The kubelet SIGKILLed it after
the grace period, which delayed every task's end by about 30 s and put
"container trec exited with code 137" in failed tasks' system logs.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest

from poiesis.api.tes.models import TesState
from poiesis.core import k8s_watch, reconcile, trec
from poiesis.core.k8s_watch import PodSelector, watch_pods
from poiesis.core.pod_status import (
    extract_terminal_reason,
    is_lifecycle_stop,
    pod_terminated_terminal,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


@pytest.fixture
def blocked_watch(monkeypatch: pytest.MonkeyPatch) -> Iterator[threading.Event]:
    """A watch thread that blocks, like a stream with no events, until released."""
    release = threading.Event()

    def run_watch_thread(*_: Any) -> None:
        release.wait()

    monkeypatch.setattr(k8s_watch, "_run_watch_thread", run_watch_thread)
    yield release
    release.set()


def test_watch_consumer_can_exit_while_the_stream_blocks(
    blocked_watch: threading.Event,
) -> None:
    """`asyncio.run` returns although the watch thread is still blocked."""

    async def consume() -> None:
        events = watch_pods(None, PodSelector(namespace="tasks"))  # ty: ignore
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.1):
                await anext(events)
        await events.aclose()

    runner = threading.Thread(target=asyncio.run, args=(consume(),), daemon=True)
    started = time.monotonic()
    runner.start()
    runner.join(timeout=5)

    assert not runner.is_alive()
    assert time.monotonic() - started < 5  # noqa: PLR2004
    assert not blocked_watch.is_set()


class FakeDb:
    """A trec database whose writes go to the patched statements, no connection."""

    def until(self, _stop: asyncio.Event) -> FakeDb:
        return self

    async def write(self, statement: Any, *args: Any, **kwargs: Any) -> None:
        await statement(None, *args, **kwargs)


class FakePod:
    def __init__(self, status: dict[str, Any]) -> None:
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status}


class FakeCoreV1:
    """Serves the Pod as it is when trec is stopped: exec-0 finished."""

    def __init__(self) -> None:
        self.reads: list[dict[str, Any]] = []

    def read_namespaced_pod(self, **kwargs: Any) -> FakePod:
        self.reads.append(kwargs)
        return FakePod(
            {
                "phase": "Running",
                "init_container_statuses": [
                    {
                        "name": "exec-0",
                        "state": {
                            "terminated": {
                                "exit_code": 0,
                                "started_at": "2026-11-21T10:00:00+00:00",
                                "finished_at": "2026-11-21T10:00:05+00:00",
                            }
                        },
                    }
                ],
            }
        )


def test_sigterm_records_the_last_state_and_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On SIGTERM trec reads the Pod once more, records it, and returns 0."""
    core_v1 = FakeCoreV1()
    rows: list[dict[str, Any]] = []
    sigterm = asyncio.Event()

    async def no_events(*_: Any) -> AsyncIterator[Any]:
        await asyncio.Event().wait()
        yield  # pragma: no cover

    async def append(_conn: Any, _task_id: str, **row: Any) -> None:
        rows.append(row)

    async def read_streams(*_: Any) -> tuple[str, None]:
        return "hello\n", None

    monkeypatch.setattr(trec, "watch_pods", no_events)
    monkeypatch.setattr(trec, "stop_on_signals", lambda: sigterm)
    monkeypatch.setattr(trec.client, "CoreV1Api", lambda: core_v1)
    monkeypatch.setattr(trec.state_db, "append_executor_log", append)
    monkeypatch.setattr(trec, "read_executor_streams", read_streams)

    async def mark_running(_conn: Any, _task_id: str) -> None:
        rows.append({"state": "RUNNING"})

    monkeypatch.setattr(trec, "_mark_running", mark_running)

    async def main() -> int:
        asyncio.get_running_loop().call_later(0.05, sigterm.set)
        async with asyncio.timeout(5):
            db: Any = FakeDb()
            return await trec._run_until_terminal(db, "t1", "pod-1", "tasks", {})

    assert asyncio.run(main()) == 0
    running = rows.pop(0)
    assert running == {"state": "RUNNING"}
    (read,) = core_v1.reads
    assert (read["name"], read["namespace"]) == ("pod-1", "tasks")
    (row,) = rows
    assert (row["ordinal"], row["exit_code"], row["stdout"]) == (0, 0, "hello\n")


def test_sigterm_exits_even_if_the_pod_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A failed last read is a warning; trec still exits 0."""
    sigterm = asyncio.Event()
    sigterm.set()

    class BrokenCoreV1:
        def read_namespaced_pod(self, **_: Any) -> None:
            msg = "(403) Forbidden"
            raise RuntimeError(msg)

    async def no_events(*_: Any) -> AsyncIterator[Any]:
        await asyncio.Event().wait()
        yield  # pragma: no cover

    monkeypatch.setattr(trec, "watch_pods", no_events)
    monkeypatch.setattr(trec, "stop_on_signals", lambda: sigterm)
    monkeypatch.setattr(trec.client, "CoreV1Api", BrokenCoreV1)

    db: Any = FakeDb()
    result = asyncio.run(trec._run_until_terminal(db, "t1", "p", "tasks", {}))

    assert result == 0
    assert "could not record the Pod's last state" in caplog.text


def status(name: str, exit_code: int, reason: str, finished: str) -> dict[str, Any]:
    return {
        "name": name,
        "state": {
            "terminated": {
                "exit_code": exit_code,
                "reason": reason,
                "finished_at": f"2026-11-21T17:58:{finished}Z",
            }
        },
    }


def failed_pod(*statuses: dict[str, Any]) -> dict[str, Any]:
    return {"status": {"phase": "Failed", "init_container_statuses": list(statuses)}}


def test_trec_killed_at_the_end_is_not_a_failure() -> None:
    """The issue's Pod: trec SIGKILLed after exec-0 failed."""
    pod = failed_pod(
        status("trec", 137, "Error", "55"),
        status("exec-0", 1, "Error", "23"),
    )
    reason = extract_terminal_reason(pod)
    state, _ = pod_terminated_terminal(reason)

    assert reconcile.terminal_system_logs(pod, state) == [
        "container exec-0 exited with code 1"
    ]
    assert (reason, state) == ("Error", TesState.EXECUTOR_ERROR)


def test_trec_stop_does_not_hide_an_oom_kill() -> None:
    """trec's 137 used to be the task's reason, ahead of the executor's."""
    pod = failed_pod(
        status("trec", 137, "Error", "55"),
        status("exec-0", 137, "OOMKilled", "23"),
    )
    reason = extract_terminal_reason(pod)
    assert reason == "OOMKilled"
    assert pod_terminated_terminal(reason)[0] is TesState.EXECUTOR_ERROR
    assert reconcile.terminal_system_logs(pod, TesState.EXECUTOR_ERROR) == [
        "container exec-0 OOMKilled: the executor ran out of memory and has no "
        "memory limit; set resources.ram_gb"
    ]


def test_trec_ending_before_the_work_is_a_failure() -> None:
    """trec dying while executors still ran shows."""
    pod = failed_pod(
        status("trec", 1, "Error", "10"),
        status("exec-0", 137, "Error", "23"),
    )
    assert reconcile.terminal_system_logs(pod, TesState.EXECUTOR_ERROR) == [
        "container trec exited with code 1",
        "container exec-0 exited with code 137",
    ]


@pytest.mark.parametrize(
    ("name", "finished", "others", "expected"),
    [
        ("trec", "55", [status("exec-0", 0, "Completed", "23")], True),
        ("ack", "56", [status("tof", 0, "Completed", "50")], True),
        ("trec", "10", [status("tif", 0, "Completed", "23")], False),
        ("trec", "55", [], False),
        ("exec-0", "55", [status("tif", 0, "Completed", "23")], False),
    ],
    ids=["trec-after", "ack-after", "trec-before", "no-work", "not-lifecycle"],
)
def test_is_lifecycle_stop(
    name: str, finished: str, others: list[dict[str, Any]], *, expected: bool
) -> None:
    entry = status(name, 137, "Error", finished)
    pod_status = {"init_container_statuses": [entry, *others]}
    terminated = entry["state"]["terminated"]
    assert is_lifecycle_stop(pod_status, name, terminated) is expected
