"""Security contexts of executors and of the TaskPod are a setting.

Executors run user images and got no `securityContext`, and the TaskPod
none at Pod level. In a namespace that enforces Pod Security `restricted`
the API server then refused every TaskPod. `taskpods.executorSecurityEnforce`
(`POIESIS_EXECUTOR_SECURITY_ENFORCE`) now picks a profile for them, `off`
by default, and `taskpods.podSecurityContext` and
`taskpods.executorSecurityContext` add to it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from kubernetes.client import ApiClient, V1ObjectMeta, V1PodSecurityContext

from poiesis.api.settings import (
    EXECUTOR_SECURITY_CONTEXT_ENV,
    EXECUTOR_SECURITY_ENFORCE_ENV,
    TASKPOD_POD_SECURITY_CONTEXT_ENV,
    AuthSettings,
    Settings,
)
from poiesis.api.tes.models import TesExecutor, TesInput, TesTask
from poiesis.core.k8s_json import from_json
from poiesis.core.taskpod import PodSecurityEnforce, RuntimeConfig, build_taskpod_job

ENVS = (
    EXECUTOR_SECURITY_ENFORCE_ENV,
    TASKPOD_POD_SECURITY_CONTEXT_ENV,
    EXECUTOR_SECURITY_CONTEXT_ENV,
)

RESTRICTED_POD = {
    "runAsNonRoot": True,
    "runAsUser": 65532,
    "runAsGroup": 65532,
    "fsGroup": 65532,
    "fsGroupChangePolicy": "OnRootMismatch",
    "seccompProfile": {"type": "RuntimeDefault"},
}
RESTRICTED_EXECUTOR = {
    "runAsNonRoot": True,
    "allowPrivilegeEscalation": False,
    "capabilities": {"drop": ["ALL"]},
    "seccompProfile": {"type": "RuntimeDefault"},
}
BASELINE_EXECUTOR = {"allowPrivilegeEscalation": False}


def pod_spec(config: RuntimeConfig) -> dict[str, Any]:
    """The TaskPod spec of a two-executor task, as Kubernetes JSON."""
    task = TesTask(
        id="t1",
        inputs=[TesInput(path="/data/in", content="hello")],
        executors=[
            TesExecutor(image="busybox:1.36", command=["true"]),
            TesExecutor(image="busybox:1.36", command=["true"]),
        ],
    )
    _, job = build_taskpod_job(task, config)
    spec: dict[str, Any] = ApiClient().sanitize_for_serialization(
        job.spec.template.spec
    )
    return spec


def containers(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Container name → container, init containers included."""
    return {c["name"]: c for c in [*spec["initContainers"], *spec["containers"]]}


def executors(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The executor containers."""
    return [c for n, c in containers(spec).items() if n.startswith("exec-")]


def settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    """Settings with only the given security env vars set."""
    for name in ENVS:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings(auth=AuthSettings(enabled=False))


def test_unset_keeps_executors_as_their_images_say(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """By default executors and the Pod get no security context, as before."""
    config = settings(monkeypatch).runtime_config()
    assert config.executor_security_enforce is PodSecurityEnforce.OFF
    spec = pod_spec(config)
    assert "securityContext" not in spec
    for executor in executors(spec):
        assert "securityContext" not in executor


def test_restricted_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """`restricted` sets a fixed non-root user on the Pod and locks executors down."""
    config = settings(
        monkeypatch, **{EXECUTOR_SECURITY_ENFORCE_ENV: "restricted"}
    ).runtime_config()
    spec = pod_spec(config)
    assert spec["securityContext"] == RESTRICTED_POD
    for executor in executors(spec):
        assert executor["securityContext"] == RESTRICTED_EXECUTOR


def test_baseline_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """`baseline` only stops privilege escalation; root images keep capabilities."""
    config = settings(
        monkeypatch, **{EXECUTOR_SECURITY_ENFORCE_ENV: "baseline"}
    ).runtime_config()
    spec = pod_spec(config)
    assert "securityContext" not in spec
    for executor in executors(spec):
        assert executor["securityContext"] == BASELINE_EXECUTOR


def test_overrides_merge_over_the_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operator keys replace the profile's keys of the same name, and add others."""
    config = settings(
        monkeypatch,
        **{
            EXECUTOR_SECURITY_ENFORCE_ENV: "restricted",
            TASKPOD_POD_SECURITY_CONTEXT_ENV: json.dumps(
                {"runAsUser": 1000, "supplementalGroups": [2000]}
            ),
            EXECUTOR_SECURITY_CONTEXT_ENV: json.dumps({"readOnlyRootFilesystem": True}),
        },
    ).runtime_config()
    spec = pod_spec(config)
    assert spec["securityContext"] == {
        **RESTRICTED_POD,
        "runAsUser": 1000,
        "supplementalGroups": [2000],
    }
    for executor in executors(spec):
        assert executor["securityContext"] == {
            **RESTRICTED_EXECUTOR,
            "readOnlyRootFilesystem": True,
        }


def test_nested_overrides_keep_the_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """An object in an override merges with the profile's object of that name."""
    config = settings(
        monkeypatch,
        **{
            EXECUTOR_SECURITY_ENFORCE_ENV: "restricted",
            EXECUTOR_SECURITY_CONTEXT_ENV: json.dumps(
                {"capabilities": {"add": ["NET_BIND_SERVICE"]}}
            ),
        },
    ).runtime_config()
    for executor in executors(pod_spec(config)):
        assert executor["securityContext"]["capabilities"] == {
            "add": ["NET_BIND_SERVICE"],
            "drop": ["ALL"],
        }


def test_restricted_executors_need_restricted_poiesis_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With podSecurityEnforce off, trec/tif/tof/ack would fail restricted: refused."""
    monkeypatch.setenv("POIESIS_POD_SECURITY_ENFORCE", "off")
    with pytest.raises(ValueError, match="not off"):
        settings(monkeypatch, **{EXECUTOR_SECURITY_ENFORCE_ENV: "restricted"})


def test_runtime_config_refuses_restricted_executors_with_off() -> None:
    """The builder's own config refuses the combination too, without Settings."""
    with pytest.raises(ValueError, match="not off"):
        RuntimeConfig(
            taskpod_namespace="ns",
            poiesis_image="poiesis:test",
            executor_security_enforce=PodSecurityEnforce.RESTRICTED,
            pod_security_enforce=PodSecurityEnforce.OFF,
        )


def test_overrides_apply_without_a_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """With `off`, the operator's contexts are used as they are."""
    config = settings(
        monkeypatch,
        **{
            TASKPOD_POD_SECURITY_CONTEXT_ENV: json.dumps({"fsGroup": 1000}),
            EXECUTOR_SECURITY_CONTEXT_ENV: json.dumps({"runAsNonRoot": True}),
        },
    ).runtime_config()
    spec = pod_spec(config)
    assert spec["securityContext"] == {"fsGroup": 1000}
    for executor in executors(spec):
        assert executor["securityContext"] == {"runAsNonRoot": True}


#: securityContext of trec/tif/tof/ack per podSecurityEnforce.
POIESIS_CONTEXTS: dict[str, dict[str, Any] | None] = {
    "restricted": {
        "runAsNonRoot": True,
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
        "seccompProfile": {"type": "RuntimeDefault"},
    },
    "baseline": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
    "off": None,
}


@pytest.mark.parametrize("executor_profile", ["off", "baseline", "restricted"])
@pytest.mark.parametrize("poiesis_profile", ["restricted", "baseline", "off"])
def test_poiesis_containers_keep_their_own_profile(
    monkeypatch: pytest.MonkeyPatch, poiesis_profile: str, executor_profile: str
) -> None:
    """trec, tif and ack follow podSecurityEnforce, not the executor setting."""
    if executor_profile == "restricted" and poiesis_profile == "off":
        pytest.skip("refused, see test_restricted_executors_need_restricted_poiesis")
    monkeypatch.setenv("POIESIS_POD_SECURITY_ENFORCE", poiesis_profile)
    spec = pod_spec(
        settings(
            monkeypatch, **{EXECUTOR_SECURITY_ENFORCE_ENV: executor_profile}
        ).runtime_config()
    )
    for name in ("trec", "tif", "ack"):
        assert (
            containers(spec)[name].get("securityContext")
            == POIESIS_CONTEXTS[poiesis_profile]
        ), name


@pytest.mark.parametrize("poiesis_profile", ["restricted", "baseline"])
def test_restricted_taskpod_meets_pod_security_restricted(
    monkeypatch: pytest.MonkeyPatch, poiesis_profile: str
) -> None:
    """Every container of a `restricted` TaskPod passes the restricted checks.

    The checks of the Pod Security Standard `restricted` that a TaskPod can
    fail: privilege escalation, capabilities, non-root and seccomp, each
    from the container or, where Kubernetes allows it, the Pod.
    """
    monkeypatch.setenv("POIESIS_POD_SECURITY_ENFORCE", poiesis_profile)
    config = settings(
        monkeypatch, **{EXECUTOR_SECURITY_ENFORCE_ENV: "restricted"}
    ).runtime_config()
    spec = pod_spec(config)
    pod = spec.get("securityContext", {})
    for name, container in containers(spec).items():
        context = container.get("securityContext", {})
        assert context.get("allowPrivilegeEscalation") is False, name
        assert context.get("capabilities", {}).get("drop") == ["ALL"], name
        assert context.get("runAsNonRoot", pod.get("runAsNonRoot")) is True, name
        seccomp = context.get("seccompProfile", pod.get("seccompProfile", {}))
        assert seccomp.get("type") in {"RuntimeDefault", "Localhost"}, name


def test_nested_fields_become_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Objects and lists of objects in an override reach the Pod intact."""
    sysctls = [{"name": "net.ipv4.ping_group_range", "value": "0 2147483647"}]
    config = settings(
        monkeypatch,
        **{
            TASKPOD_POD_SECURITY_CONTEXT_ENV: json.dumps(
                {"sysctls": sysctls, "supplementalGroups": [1, 2]}
            ),
            EXECUTOR_SECURITY_CONTEXT_ENV: json.dumps(
                {"seLinuxOptions": {"level": "s0:c1"}}
            ),
        },
    ).runtime_config()
    spec = pod_spec(config)
    assert spec["securityContext"] == {"sysctls": sysctls, "supplementalGroups": [1, 2]}
    for executor in executors(spec):
        assert executor["securityContext"] == {"seLinuxOptions": {"level": "s0:c1"}}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pod_security_context", {"bogus": 1}),
        ("executor_security_context", {"capabilities": {"bogus": []}}),
    ],
)
def test_runtime_config_with_unknown_key_refused(field: str, value: Any) -> None:
    """A RuntimeConfig built without Settings still can't build such a TaskPod."""
    config = RuntimeConfig(
        taskpod_namespace="ns", poiesis_image="poiesis:test", **{field: value}
    )
    with pytest.raises(ValueError, match="no field 'bogus'"):
        pod_spec(config)


def test_dict_fields_pass_unconverted() -> None:
    """`dict(…)` and scalar fields keep their JSON value; models are built."""
    meta = from_json(V1ObjectMeta, {"name": "x", "labels": {"a": "b"}})
    assert meta.labels == {"a": "b"}
    context = from_json(V1PodSecurityContext, {"seccompProfile": {"type": "X"}})
    assert context.seccomp_profile is not None
    assert context.seccomp_profile.type == "X"


@pytest.mark.parametrize(
    ("env", "value", "message"),
    [
        (EXECUTOR_SECURITY_ENFORCE_ENV, "strict", "restricted, baseline or off"),
        (TASKPOD_POD_SECURITY_CONTEXT_ENV, "not json", "not valid JSON"),
        (TASKPOD_POD_SECURITY_CONTEXT_ENV, "[]", "must encode a JSON object"),
        (TASKPOD_POD_SECURITY_CONTEXT_ENV, '{"runAsUsr": 1}', "no field 'runAsUsr'"),
        (
            TASKPOD_POD_SECURITY_CONTEXT_ENV,
            '{"allowPrivilegeEscalation": false}',
            "no field 'allowPrivilegeEscalation'",
        ),
        (EXECUTOR_SECURITY_CONTEXT_ENV, "not json", "not valid JSON"),
        (EXECUTOR_SECURITY_CONTEXT_ENV, '"x"', "must encode a JSON object"),
        (
            EXECUTOR_SECURITY_CONTEXT_ENV,
            '{"capabilities": {"drops": ["ALL"]}}',
            "no field 'drops'",
        ),
        (EXECUTOR_SECURITY_CONTEXT_ENV, '{"capabilities": "ALL"}', "must be an object"),
        (
            EXECUTOR_SECURITY_CONTEXT_ENV,
            '{"capabilities": {"drop": [null]}}',
            "V1Capabilities.drop must not hold null",
        ),
        (
            EXECUTOR_SECURITY_CONTEXT_ENV,
            '{"capabilities": {"drop": "ALL"}}',
            "V1Capabilities.drop must be a list",
        ),
        (
            TASKPOD_POD_SECURITY_CONTEXT_ENV,
            '{"runAsUser": "1000"}',
            "V1PodSecurityContext.runAsUser must be int",
        ),
        (
            TASKPOD_POD_SECURITY_CONTEXT_ENV,
            '{"runAsUser": true}',
            "V1PodSecurityContext.runAsUser must be int",
        ),
        (
            TASKPOD_POD_SECURITY_CONTEXT_ENV,
            '{"sysctls": {"name": "x"}}',
            "V1PodSecurityContext.sysctls must be a list",
        ),
        (
            EXECUTOR_SECURITY_CONTEXT_ENV,
            '{"privileged": "no"}',
            "V1SecurityContext.privileged must be bool",
        ),
    ],
)
def test_bad_value_refused(
    monkeypatch: pytest.MonkeyPatch, env: str, value: str, message: str
) -> None:
    """A malformed setting stops the API at startup, naming the setting."""
    with pytest.raises((ValueError, TypeError), match=message) as caught:
        settings(monkeypatch, **{env: value})
    assert env in str(caught.value)
