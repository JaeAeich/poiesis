"""Only trec gets the TaskPod's ServiceAccount token (#110).

The Pod used to automount the token into every container, so executors,
which run user images, could call the Kubernetes API with the TaskPod's
RBAC. Now the Pod automounts nothing and trec alone mounts a projected
token at the path in-cluster config reads.
"""

from __future__ import annotations

from typing import Any

from kubernetes.client import V1Job

from poiesis.api.tes.models import TesExecutor, TesInput, TesOutput, TesTask
from poiesis.core.taskpod import (
    API_TOKEN_MOUNT_PATH,
    API_TOKEN_VOLUME_NAME,
    RuntimeConfig,
    build_taskpod_job,
)

CONFIG = RuntimeConfig(
    taskpod_namespace="tasks",
    poiesis_image="poiesis:test",
    taskpod_service_account="poiesis-taskpod",
    postgres_ca_configmap="pg-ca",
    taskpod_extra_volume_mounts=[{"name": "ref", "mountPath": "/ref"}],
)


def build() -> V1Job:
    task = TesTask(
        id="t1",
        inputs=[TesInput(path="/data/in.txt", content="x")],
        outputs=[TesOutput(path="/data/out.txt", url="s3://bucket/out")],
        executors=[
            TesExecutor(image="busybox:1.36", command=["true"]) for _ in range(2)
        ],
    )
    _, job = build_taskpod_job(task, CONFIG)
    return job


def containers(job: V1Job) -> dict[str, Any]:
    spec = job.spec.template.spec
    return {c.name: c for c in [*spec.init_containers, *spec.containers]}


def mount_names(container: Any) -> list[str]:
    """Names of a container's mounts; operator extras are plain dicts."""
    return [
        m["name"] if isinstance(m, dict) else m.name
        for m in container.volume_mounts or []
    ]


def token_mounts(container: Any) -> list[Any]:
    return [
        m
        for m in container.volume_mounts or []
        if not isinstance(m, dict)
        and (m.name == API_TOKEN_VOLUME_NAME or m.mount_path == API_TOKEN_MOUNT_PATH)
    ]


def test_pod_does_not_automount_token() -> None:
    """The Pod keeps its ServiceAccount but automounts no token."""
    spec = build().spec.template.spec
    assert spec.service_account_name == "poiesis-taskpod"
    assert spec.automount_service_account_token is False


def test_only_trec_mounts_token() -> None:
    """trec mounts the token read-only; executors, filers and ack don't."""
    by_name = containers(build())
    assert set(by_name) == {"trec", "tif", "exec-0", "exec-1", "tof", "ack"}
    (mount,) = token_mounts(by_name["trec"])
    assert mount.mount_path == API_TOKEN_MOUNT_PATH
    assert mount.read_only is True
    for name in ("tif", "exec-0", "exec-1", "tof", "ack"):
        assert token_mounts(by_name[name]) == [], name
        assert API_TOKEN_VOLUME_NAME not in mount_names(by_name[name]), name


def test_trec_keeps_its_other_mounts() -> None:
    """trec still gets the PVC, the Postgres CA and the operator's mounts."""
    trec = containers(build())["trec"]
    assert mount_names(trec) == [
        "task-data",
        "postgres-ca",
        "ref",
        API_TOKEN_VOLUME_NAME,
    ]


def test_token_volume_matches_in_cluster_layout() -> None:
    """The volume holds `token`, `ca.crt` and `namespace`, as automount does."""
    volumes = {v.name: v for v in build().spec.template.spec.volumes}
    projected = volumes[API_TOKEN_VOLUME_NAME].projected
    token, ca, namespace = projected.sources
    assert token.service_account_token.path == "token"
    assert token.service_account_token.audience is None
    assert token.service_account_token.expiration_seconds == 3600  # noqa: PLR2004
    assert ca.config_map.name == "kube-root-ca.crt"
    assert [(i.key, i.path) for i in ca.config_map.items] == [("ca.crt", "ca.crt")]
    (item,) = namespace.downward_api.items
    assert item.path == "namespace"
    assert item.field_ref.field_path == "metadata.namespace"
    assert projected.default_mode == 0o644  # noqa: PLR2004
