"""The operator's unschedulable timeout reaches tctl's reconcile pass (#151).

Unset, a task whose Pod can't be scheduled waits until the Job's time limit;
`POIESIS_TCTL_UNSCHEDULABLE_TIMEOUT_SECONDS` makes it fail sooner. A bad
value stops tctl at startup rather than failing or keeping tasks by mistake.
"""

from __future__ import annotations

from typing import Any

import pytest
from click.testing import CliRunner

from poiesis.cli.commands.poiesis import tctl as tctl_cli

ENV = "POIESIS_TCTL_UNSCHEDULABLE_TIMEOUT_SECONDS"


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """What `poiesis tctl run` passes to `tctl.run`."""
    seen: dict[str, Any] = {}

    async def run(namespace: str, dsn: str, **kwargs: Any) -> int:
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(tctl_cli, "run", run)
    monkeypatch.setattr(tctl_cli, "load_config", lambda: None)
    monkeypatch.setenv("POIESIS_TASKPOD_NAMESPACE", "tasks")
    monkeypatch.setenv("DATABASE_URL", "dsn")
    monkeypatch.delenv(ENV, raising=False)
    return seen


def invoke() -> Any:
    return CliRunner().invoke(tctl_cli.TctlCommand().create_command(), ["run"])


@pytest.mark.parametrize("value", [None, ""])
def test_unset_waits(
    monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any], value: str | None
) -> None:
    if value is not None:
        monkeypatch.setenv(ENV, value)
    result = invoke()
    assert result.exit_code == 0, result.output
    assert seen["unschedulable_timeout"] is None


def test_set(monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any]) -> None:
    monkeypatch.setenv(ENV, "900")
    result = invoke()
    assert result.exit_code == 0, result.output
    assert seen["unschedulable_timeout"] == 900


@pytest.mark.parametrize("value", ["0", "-5", "1.5", "5m", "null"])
def test_bad_value_stops_tctl(
    monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any], value: str
) -> None:
    monkeypatch.setenv(ENV, value)
    result = invoke()
    assert result.exit_code != 0
    assert ENV in result.output
    assert seen == {}
