"""The task time limit is an operator setting (#150).

Every Job used to get `activeDeadlineSeconds: 3600` with nothing to change
it. It is now `taskpods.activeDeadlineSeconds`, which reaches the API as
`POIESIS_ACTIVE_DEADLINE_SECONDS`; `null` means no limit. A Job that hit
the limit is told apart by its `DeadlineExceeded` condition.
"""

from __future__ import annotations

from typing import Any

import pytest

from poiesis.api.settings import AuthSettings, Settings
from poiesis.tes.models import TesExecutor, TesState, TesTask
from poiesis.core.pod_status import job_deadline_terminal
from poiesis.core.taskpod import RuntimeConfig, build_taskpod_job

ENV = "POIESIS_ACTIVE_DEADLINE_SECONDS"


def job_deadline(config: RuntimeConfig) -> int | None:
    """`activeDeadlineSeconds` of the Job built for a one-executor task."""
    task = TesTask(
        id="t1", executors=[TesExecutor(image="busybox:1.36", command=["true"])]
    )
    _, job = build_taskpod_job(task, config)
    return job.spec.active_deadline_seconds


def test_default_is_one_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset keeps the limit every task had before the setting existed."""
    monkeypatch.delenv(ENV, raising=False)
    settings = Settings(auth=AuthSettings(enabled=False))
    assert settings.active_deadline_seconds == 3600  # noqa: PLR2004
    assert job_deadline(settings.runtime_config()) == 3600  # noqa: PLR2004


@pytest.mark.parametrize(
    ("value", "expected"),
    [("", 3600), ("1", 1), ("86400", 86400), ("null", None), ("None", None)],
)
def test_setting_reaches_the_job(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: int | None
) -> None:
    """The env value becomes the Job's deadline; null omits the field."""
    monkeypatch.setenv(ENV, value)
    settings = Settings(auth=AuthSettings(enabled=False))
    assert settings.active_deadline_seconds == expected
    assert job_deadline(settings.runtime_config()) == expected


@pytest.mark.parametrize("value", ["0", "-5", "1.5", "1h", "forever", "true"])
def test_bad_value_refused(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """A value that is not a whole number of seconds >= 1 fails startup."""
    monkeypatch.setenv(ENV, value)
    with pytest.raises(ValueError, match=ENV):
        Settings(auth=AuthSettings(enabled=False))


def job(conditions: list[dict[str, Any]], **spec: Any) -> dict[str, Any]:
    """A Job with the given status conditions and spec fields."""
    return {"spec": spec, "status": {"conditions": conditions}}


def condition(kind: str, reason: str, status: str = "True") -> dict[str, Any]:
    """A Job status condition."""
    return {"type": kind, "status": status, "reason": reason}


@pytest.mark.parametrize(
    ("deadline_job", "line"),
    [
        (
            job([condition("Failed", "DeadlineExceeded")], active_deadline_seconds=60),
            "task exceeded its time limit of 60 seconds",
        ),
        (
            job([condition("Failed", "DeadlineExceeded")], activeDeadlineSeconds=7200),
            "task exceeded its time limit of 7200 seconds",
        ),
        (
            job(
                [condition("FailureTarget", "DeadlineExceeded")],
                active_deadline_seconds=60,
            ),
            "task exceeded its time limit of 60 seconds",
        ),
        (
            job([condition("Failed", "DeadlineExceeded")]),
            "task exceeded its time limit",
        ),
    ],
    ids=["to_dict", "raw", "pod-still-terminating", "no-spec"],
)
def test_job_past_its_deadline(deadline_job: dict[str, Any], line: str) -> None:
    """A DeadlineExceeded Job is SYSTEM_ERROR, with the limit in the log."""
    assert job_deadline_terminal(deadline_job) == (
        TesState.SYSTEM_ERROR,
        "DeadlineExceeded",
        line,
    )


@pytest.mark.parametrize(
    "other_job",
    [
        {},
        {"status": None},
        job([], active_deadline_seconds=60),
        job([condition("Complete", "CompletionsReached")]),
        job([condition("Failed", "BackoffLimitExceeded")]),
        job([condition("Failed", "DeadlineExceeded", status="False")]),
        job([condition("Suspended", "DeadlineExceeded")]),
    ],
    ids=[
        "empty",
        "no-status",
        "running",
        "complete",
        "backoff",
        "condition-false",
        "other-condition",
    ],
)
def test_other_jobs_are_not_a_time_limit(other_job: dict[str, Any]) -> None:
    """Only a true Failed/FailureTarget DeadlineExceeded condition counts."""
    assert job_deadline_terminal(other_job) is None
