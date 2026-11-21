"""TES resources reach the TaskPod; scheduling settings; OOMKilled executors (#170).

`cpu_cores`, `ram_gb`, `zones` and `preemptible` were stored and never
used: executors ran without requests or limits wherever the scheduler put
them. The manifests are covered by the golden cases (`resources-*`,
`zones`, `scheduling-*`); this module covers the settings that feed them
(`POIESIS_TASKPOD_SCHEDULING`), the keys service-info reports, and how an
executor killed for its memory ends.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from poiesis.api.app import create_app
from poiesis.api.settings import (
    SCHEDULING_ENV,
    AuthSettings,
    SchedulingSettings,
    Settings,
)
from poiesis.api.tes.models import TesExecutor, TesResources, TesState, TesTask
from poiesis.core import tctl
from poiesis.core.pod_status import extract_terminal_reason, pod_terminated_terminal
from poiesis.core.taskpod import RuntimeConfig, build_taskpod_job
from poiesis.core.taskpod.config import NodePlacement
from poiesis.core.taskpod.pod import memory_quantity

SCHEDULING = {
    "resources": {
        "defaultCpuCores": 1,
        "defaultRamGb": 2,
        "maxCpuCores": 16,
        "maxRamGb": 64,
        "cpuLimit": False,
    },
    "nodeSelector": {"pool": "tasks"},
    "tolerations": [{"key": "tasks", "operator": "Exists"}],
    "affinity": {},
    "priorityClassName": "",
    "runtimeClassName": "gvisor",
    "preemptible": {"nodeSelector": {}, "tolerations": []},
    "gpu": {"resourceName": "nvidia.com/gpu", "maxCount": 2},
    "backendParameters": {
        "allowed": ["GPU_COUNT", "node_pool"],
        "priorityClasses": [],
        "nodePools": {"big": {"nodeSelector": {"pool": "big"}}},
    },
}


def settings(monkeypatch: pytest.MonkeyPatch, value: object) -> Settings:
    """Settings with `POIESIS_TASKPOD_SCHEDULING` set to `value` as JSON."""
    monkeypatch.setenv(SCHEDULING_ENV, json.dumps(value))
    return Settings(auth=AuthSettings(enabled=False))


def test_unset_is_the_old_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    """No setting: executors get no requests or limits, the Pod no constraints."""
    monkeypatch.delenv(SCHEDULING_ENV, raising=False)
    config = Settings(auth=AuthSettings(enabled=False)).runtime_config()
    assert config.scheduling == RuntimeConfig("ns", "img").scheduling
    _, job = build_taskpod_job(
        TesTask(id="t", executors=[TesExecutor(image="busybox", command=["true"])]),
        config,
    )
    spec = job.spec.template.spec
    assert spec.init_containers[-1].resources is None
    assert spec.node_selector is None
    assert spec.affinity is None


def test_settings_reach_the_runtime_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each value of the chart's JSON lands in `SchedulingConfig`."""
    scheduling = settings(monkeypatch, SCHEDULING).runtime_config().scheduling
    assert scheduling.default_cpu_cores == 1
    assert scheduling.default_ram_gb == 2  # noqa: PLR2004
    assert scheduling.max_cpu_cores == 16  # noqa: PLR2004
    assert scheduling.max_ram_gb == 64  # noqa: PLR2004
    assert scheduling.cpu_limit is False
    assert scheduling.node_selector == {"pool": "tasks"}
    assert scheduling.tolerations == ({"key": "tasks", "operator": "Exists"},)
    assert scheduling.priority_class_name is None  # "" is unset
    assert scheduling.runtime_class_name == "gvisor"
    assert scheduling.preemptible is None  # nothing configured: ignored
    assert scheduling.backend_parameters == {"gpu_count", "node_pool"}
    assert scheduling.max_gpu_count == 2  # noqa: PLR2004
    assert scheduling.node_pools == {
        "big": NodePlacement(node_selector={"pool": "big"})
    }


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ({"resources": {"defaultCpuCores": 8, "maxCpuCores": 4}}, "defaultCpuCores"),
        ({"resources": {"defaultRamGb": 8, "maxRamGb": 4}}, "defaultRamGb"),
        ({"resources": {"maxRamGb": 0}}, "maxRamGb"),
        ({"resources": {"defaultCpuCores": 0}}, "defaultCpuCores"),
        ({"backendParameters": {"allowed": ["VmSize"]}}, "unknown keys"),
        ({"backendParameters": {"allowed": ["priority_class"]}}, "priorityClasses"),
        ({"backendParameters": {"allowed": ["node_pool"]}}, "nodePools"),
        ({"nodeSelectors": {}}, "nodeSelectors"),
        ({"gpu": {"maxCount": -1}}, "maxCount"),
    ],
)
def test_bad_settings_stop_the_api(
    monkeypatch: pytest.MonkeyPatch, value: dict[str, Any], error: str
) -> None:
    """A misconfiguration fails at startup, not on every task."""
    with pytest.raises(ValueError, match=SCHEDULING_ENV) as caught:
        settings(monkeypatch, value)
    assert error in str(caught.value)


def test_preemptible_placement_when_configured() -> None:
    """A preemptible node selector or tolerations turn `preemptible` on."""
    placement = SchedulingSettings.model_validate(
        {"preemptible": {"tolerations": [{"key": "spot", "operator": "Exists"}]}}
    ).config()
    assert placement.preemptible == NodePlacement(
        tolerations=({"key": "spot", "operator": "Exists"},)
    )


def test_service_info_lists_the_allowed_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """`tesResources_backend_parameters` is the operator's allowlist, lower case."""
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    monkeypatch.setenv(SCHEDULING_ENV, json.dumps(SCHEDULING))
    info = TestClient(create_app()).get("/ga4gh/tes/v1/service-info").json()
    assert info["tesResources_backend_parameters"] == ["gpu_count", "node_pool"]


def test_service_info_lists_none_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """With nothing allowed, no key is reported."""
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    monkeypatch.delenv(SCHEDULING_ENV, raising=False)
    info = TestClient(create_app()).get("/ga4gh/tes/v1/service-info").json()
    assert info["tesResources_backend_parameters"] == []


@pytest.mark.parametrize(
    ("ram_gb", "quantity"),
    [(8, "8Gi"), (0.5, "512Mi"), (1.5, "1536Mi"), (0.3, "308Mi"), (0.0001, "1Mi")],
)
def test_memory_quantity(ram_gb: float, quantity: str) -> None:
    """GiB, rounded up to whole MiB; whole GiB written as such."""
    assert memory_quantity(ram_gb) == quantity


def test_task_below_the_maximum_is_accepted() -> None:
    """Exactly the maximum is fine; the defaults don't count against it."""
    config = RuntimeConfig(
        "ns",
        "img",
        scheduling=SchedulingSettings.model_validate(SCHEDULING).config(),
    )
    task = TesTask(
        id="t",
        executors=[TesExecutor(image="busybox", command=["true"])],
        resources=TesResources(cpu_cores=16, ram_gb=64),
    )
    _, job = build_taskpod_job(task, config)
    resources = job.spec.template.spec.init_containers[-1].resources
    assert resources.requests == {"cpu": "16", "memory": "64Gi"}
    assert resources.limits == {"memory": "64Gi"}  # cpuLimit: false


def oom_pod(name: str, *, camel_case: bool, limit: str | None) -> dict[str, Any]:
    """A Failed Pod whose container `name` was OOMKilled, with its spec."""
    resources = {"limits": {"memory": limit}} if limit else None
    statuses = [
        {"name": "trec", "state": {"terminated": {"exitCode": 0}}},
        {
            "name": name,
            "state": {"terminated": {"exitCode": 137, "reason": "OOMKilled"}},
        },
    ]
    containers = [{"name": "trec"}, {"name": name, "resources": resources}]
    if camel_case:
        return {
            "spec": {"initContainers": containers},
            "status": {"phase": "Failed", "initContainerStatuses": statuses},
        }
    return {
        "spec": {"init_containers": containers},
        "status": {"phase": "Failed", "init_container_statuses": statuses},
    }


@pytest.mark.parametrize("camel_case", [True, False], ids=["raw", "to_dict"])
def test_oom_killed_executor_is_an_executor_error(
    camel_case: bool,  # noqa: FBT001
) -> None:
    """The task used more memory than it asked for; the log shows the limit."""
    pod = oom_pod("exec-0", camel_case=camel_case, limit="8Gi")

    state, reason = pod_terminated_terminal(extract_terminal_reason(pod))

    assert (state, reason) == (TesState.EXECUTOR_ERROR, "OOMKilled")
    assert tctl._terminal_system_logs(pod, state) == [
        "container exec-0 OOMKilled: the executor exceeded its memory limit of "
        "8Gi (resources.ram_gb)"
    ]


@pytest.mark.parametrize("name", ["tif", "tof", "trec", "ack"])
def test_oom_killed_system_container_is_a_system_error(name: str) -> None:
    """A poiesis-owned container over its own limit is not the task's fault."""
    pod = oom_pod(name, camel_case=True, limit="1Gi")

    state, reason = pod_terminated_terminal(extract_terminal_reason(pod))

    assert (state, reason) == (TesState.SYSTEM_ERROR, "SystemOOMKilled")
    assert tctl._terminal_system_logs(pod, state) == [f"container {name} OOMKilled"]
