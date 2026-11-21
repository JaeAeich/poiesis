"""Executor output reaches the task logs (#111).

When an executor finishes, trec (and tctl when it backfills) reads the
end of the ``exec-N`` container log and stores it as the executor log's
``stdout``. A failed read logs a warning and stores nothing; it never
fails the task or stops the recorder.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from poiesis.core import executor_logs, tctl, trec
from poiesis.core.executor_logs import MAX_OUTPUT_BYTES, read_executor_output
from poiesis.core.pod_status import EventKind, TaskEvent
from poiesis.db import state as state_db


class FakeLogResponse:
    """The streamed response of `read_namespaced_pod_log(_preload_content=False)`."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.released = False

    def stream(self, amt: int) -> Any:
        for start in range(0, len(self.data), amt):
            yield self.data[start : start + amt]

    def release_conn(self) -> None:
        self.released = True


class FakeCoreV1:
    """Serves container logs by name; `fail` makes every read raise."""

    def __init__(self, logs: dict[str, bytes], *, fail: bool = False) -> None:
        self.logs = logs
        self.fail = fail
        self.calls: list[dict[str, Any]] = []
        self.responses: list[FakeLogResponse] = []

    def read_namespaced_pod_log(self, **kwargs: Any) -> FakeLogResponse:
        self.calls.append(kwargs)
        if self.fail:
            msg = "(403) Forbidden: pods/log"
            raise RuntimeError(msg)
        response = FakeLogResponse(self.logs[kwargs["container"]])
        self.responses.append(response)
        return response


def read(core_v1: FakeCoreV1, ordinal: int = 0) -> str | None:
    return asyncio.run(read_executor_output(core_v1, "pod-1", "tasks", ordinal))


def test_reads_the_executor_container_log() -> None:
    """The log of `exec-N` in the task's Pod is read, streamed, and released."""
    core_v1 = FakeCoreV1({"exec-2": b"hello\nworld\n"})
    assert read(core_v1, 2) == "hello\nworld\n"
    (call,) = core_v1.calls
    assert call["name"] == "pod-1"
    assert call["namespace"] == "tasks"
    assert call["container"] == "exec-2"
    assert call["_preload_content"] is False
    # The kubelet sends only the end of a long log.
    assert call["tail_lines"] == executor_logs._TAIL_LINES
    assert core_v1.responses[0].released


def test_keeps_only_the_end_of_a_long_log() -> None:
    """Only the last `MAX_OUTPUT_BYTES` are kept, so the failure shows."""
    head = b"x" * (3 * MAX_OUTPUT_BYTES)
    tail = b"error: the real reason\n"
    output = read(FakeCoreV1({"exec-0": head + tail}))
    assert output is not None
    assert len(output) == MAX_OUTPUT_BYTES
    assert output.endswith(tail.decode())


def test_output_fits_a_text_column() -> None:
    """Bad UTF-8 is replaced and NUL bytes, which TEXT can't hold, dropped."""
    assert read(FakeCoreV1({"exec-0": b"a\x00b\xffc"})) == "ab�c"


def test_failed_read_warns_and_returns_none(caplog: pytest.LogCaptureFixture) -> None:
    """A read error (here missing RBAC) becomes a warning and None."""
    with caplog.at_level(logging.WARNING, logger=executor_logs.__name__):
        assert read(FakeCoreV1({}, fail=True)) is None
    assert "exec-0" in caplog.text
    assert "Forbidden" in caplog.text


@pytest.fixture
def appended(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture `append_executor_log` calls instead of writing to Postgres."""
    calls: list[dict[str, Any]] = []

    async def append(conn: Any, task_id: str, **kwargs: Any) -> None:
        calls.append({"task_id": task_id, **kwargs})

    monkeypatch.setattr(state_db, "append_executor_log", append)
    return calls


def finished(index: int, exit_code: int) -> TaskEvent:
    return TaskEvent(
        kind=EventKind.EXECUTOR_FINISHED,
        executor_index=index,
        exit_code=exit_code,
        started_at="2026-11-21T10:00:00+00:00",
        finished_at="2026-11-21T10:00:05+00:00",
    )


def test_trec_stores_executor_output(appended: list[dict[str, Any]]) -> None:
    """trec reads the finished executor's output and stores it as stdout."""
    read_for: list[int] = []

    async def read_output(index: int) -> str | None:
        read_for.append(index)
        return "boom\n"

    asyncio.run(trec._apply_event(None, "t1", finished(1, 3), read_output))
    assert read_for == [1]
    (row,) = appended
    assert row["ordinal"] == 1
    assert row["exit_code"] == 3  # noqa: PLR2004
    assert row["stdout"] == "boom\n"
    assert "stderr" not in row


def test_trec_records_the_row_when_the_log_cannot_be_read(
    appended: list[dict[str, Any]],
) -> None:
    """With the real reader failing, the row is still stored, without output."""
    core_v1 = FakeCoreV1({}, fail=True)

    async def read_output(index: int) -> str | None:
        return await read_executor_output(core_v1, "pod-1", "tasks", index)

    asyncio.run(trec._apply_event(None, "t1", finished(0, 1), read_output))
    (row,) = appended
    assert row["exit_code"] == 1
    assert row["stdout"] is None


def terminated(name: str, exit_code: int) -> dict[str, Any]:
    return {
        "name": name,
        "state": {
            "terminated": {
                "exit_code": exit_code,
                "started_at": "2026-11-21T10:00:00+00:00",
                "finished_at": "2026-11-21T10:00:05+00:00",
            }
        },
    }


POD = {
    "metadata": {"name": "pod-1", "namespace": "tasks"},
    "status": {
        "init_container_statuses": [
            terminated("trec", 0),
            terminated("tif", 0),
            terminated("exec-0", 0),
            terminated("exec-1", 7),
        ]
    },
}


def backfill(
    core_v1: FakeCoreV1,
    monkeypatch: pytest.MonkeyPatch,
    recorded: set[int],
) -> None:
    async def ordinals(conn: Any, task_id: str) -> set[int]:
        return recorded

    monkeypatch.setattr(state_db, "recorded_executor_ordinals", ordinals)
    asyncio.run(tctl._backfill_executor_logs(None, core_v1, "t1", POD))


def test_tctl_backfills_output_of_unrecorded_executors(
    appended: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """tctl reads logs only for executors trec didn't record."""
    core_v1 = FakeCoreV1({"exec-0": b"zero\n", "exec-1": b"one\n"})
    backfill(core_v1, monkeypatch, recorded={0})
    assert [c["container"] for c in core_v1.calls] == ["exec-1"]
    assert core_v1.calls[0]["name"] == "pod-1"
    assert core_v1.calls[0]["namespace"] == "tasks"
    (row,) = appended
    assert row["ordinal"] == 1
    assert row["exit_code"] == 7  # noqa: PLR2004
    assert row["stdout"] == "one\n"


def test_tctl_backfills_rows_when_logs_cannot_be_read(
    appended: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed log read still backfills the rows, without output."""
    backfill(FakeCoreV1({}, fail=True), monkeypatch, recorded=set())
    assert [(r["ordinal"], r["stdout"]) for r in appended] == [(0, None), (1, None)]
