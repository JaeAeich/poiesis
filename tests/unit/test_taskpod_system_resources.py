"""Resources of the poiesis-owned TaskPod containers are a setting (#168).

`RuntimeConfig.recorder_resources`, `filer_resources` and `ack_resources`
existed but nothing set them, so trec, tif, tof and ack ran without
requests or limits, and a namespace ResourceQuota without a LimitRange
rejected every TaskPod. They now come from `taskpods.systemResources`,
which reaches the API as JSON in `POIESIS_TASKPOD_*_RESOURCES`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from poiesis.api.settings import (
    ACK_RESOURCES_ENV,
    FILER_RESOURCES_ENV,
    RECORDER_RESOURCES_ENV,
    AuthSettings,
    Settings,
)
from poiesis.api.tes.models import TesExecutor, TesInput, TesOutput, TesTask
from poiesis.core.taskpod import RuntimeConfig, build_taskpod_job

ENVS = (RECORDER_RESOURCES_ENV, FILER_RESOURCES_ENV, ACK_RESOURCES_ENV)

FILER = {
    "requests": {"cpu": "100m", "memory": "256Mi"},
    "limits": {"cpu": "1000m", "memory": "1Gi"},
}


def container_resources(config: RuntimeConfig) -> dict[str, Any]:
    """Container name → its resources, for a task with inputs and outputs."""
    task = TesTask(
        id="t1",
        executors=[TesExecutor(image="busybox:1.36", command=["true"])],
        inputs=[TesInput(path="/data/in", url="s3://b/in")],
        outputs=[TesOutput(path="/data/out", url="s3://b/out")],
    )
    _, job = build_taskpod_job(task, config)
    spec = job.spec.template.spec
    containers = [*spec.init_containers, *spec.containers]
    return {c.name: c.resources for c in containers}


def settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    """Settings with only the given resource env vars set."""
    for name in ENVS:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    # The task has s3:// URLs, which need S3 credentials (#166).
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "key")
    return Settings(auth=AuthSettings(enabled=False))


def test_unset_leaves_no_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the settings the containers stay as before: no resources."""
    resources = container_resources(settings(monkeypatch).runtime_config())
    for name in ("trec", "tif", "tof", "ack"):
        assert resources[name] is None


def test_settings_reach_the_containers(monkeypatch: pytest.MonkeyPatch) -> None:
    """trec, tif/tof and ack each get their own block."""
    config = settings(
        monkeypatch,
        **{
            RECORDER_RESOURCES_ENV: json.dumps({"requests": {"cpu": "10m"}}),
            FILER_RESOURCES_ENV: json.dumps(FILER),
            ACK_RESOURCES_ENV: json.dumps({"limits": {"memory": "256Mi", "cpu": 1}}),
        },
    ).runtime_config()
    resources = container_resources(config)
    assert resources["trec"].requests == {"cpu": "10m"}
    assert resources["trec"].limits is None
    for name in ("tif", "tof"):
        assert resources[name].requests == FILER["requests"]
        assert resources[name].limits == FILER["limits"]
    assert resources["ack"].limits == {"memory": "256Mi", "cpu": "1"}


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("not json", "not valid JSON"),
        ("[]", "must encode a JSON object"),
        ('{"request": {"cpu": "1"}}', "unknown keys"),
        ('{"requests": ["cpu"]}', "must be a JSON object"),
        ('{"requests": {"cpu": "lots"}}', "is not a quantity"),
        ('{"requests": {"cpu": true}}', "must be a quantity"),
        ('{"limits": {"memory": "-1Gi"}}', "must not be negative"),
        (
            '{"requests": {"memory": "2Gi"}, "limits": {"memory": "1Gi"}}',
            "requests.memory is above limits.memory",
        ),
    ],
)
@pytest.mark.parametrize("env", ENVS)
def test_bad_value_refused(
    monkeypatch: pytest.MonkeyPatch, env: str, value: str, message: str
) -> None:
    """A malformed block stops the API at startup, naming the setting."""
    with pytest.raises((ValueError, TypeError), match=message) as caught:
        settings(monkeypatch, **{env: value})
    assert env in str(caught.value)
