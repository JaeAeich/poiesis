"""The entry point: a TES task and runtime config to the PVC and Job."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kubernetes.client import (
    V1Container,
    V1Job,
    V1JobSpec,
    V1LocalObjectReference,
    V1ObjectMeta,
    V1OwnerReference,
    V1PersistentVolumeClaim,
    V1PodSpec,
    V1PodTemplateSpec,
)

from poiesis.core.taskpod.executors import build_executor
from poiesis.core.taskpod.system_containers import (
    build_ack_container,
    build_tif,
    build_tof,
    build_trec,
)
from poiesis.core.taskpod.validation import reject_unsupported_features
from poiesis.core.taskpod.volumes import (
    build_pvc,
    executor_path_mounts,
    pod_volumes,
    task_dirs,
)

if TYPE_CHECKING:
    from poiesis.api.tes.models import TesTask
    from poiesis.core.taskpod.config import RuntimeConfig


TASK_LABEL = "poiesis.io/task"
COMPONENT_LABEL = "app.kubernetes.io/component"
NAME_LABEL = "app.kubernetes.io/name"


def build_taskpod_job(
    task: TesTask, config: RuntimeConfig
) -> tuple[V1PersistentVolumeClaim, V1Job]:
    """Build the PVC + Job pair for a TES task.

    Returns the two manifests the caller should submit. The Pod can be
    submitted before the PVC exists (it will sit Pending until the PVC is
    ready), so the recommended order is:

        pvc, job = build_taskpod_job(task, config)
        created_job = await k8s.create_job(job)
        attach_pvc_owner(pvc, created_job.metadata.uid, created_job.metadata.name)
        await k8s.create_pvc(pvc)

    With the ownerReference set on creation, `kube-controller-manager` will
    garbage-collect the PVC when the Job is deleted. Poiesis itself never
    deletes a PVC.
    """
    if task.id is None:
        msg = "TesTask.id must be set before manifest construction"
        raise ValueError(msg)
    reject_unsupported_features(task, config)

    task_id = task.id
    job_name = job_name_for(task_id)
    pvc_name = f"task-{task_id}-data"

    labels = task_labels(task_id)
    pvc = build_pvc(pvc_name, labels, task, config)
    job = build_job(job_name, pvc_name, labels, task, config)
    return pvc, job


def job_name_for(task_id: str) -> str:
    """Return the Kubernetes Job name that wraps `task_id`'s TaskPod."""
    return f"task-{task_id}"


def task_labels(task_id: str) -> dict[str, str]:
    """Canonical labels every TaskPod resource carries."""
    return {
        TASK_LABEL: task_id,
        NAME_LABEL: "poiesis",
        COMPONENT_LABEL: "taskpod",
    }


def build_job(
    job_name: str,
    pvc_name: str,
    labels: dict[str, str],
    task: TesTask,
    config: RuntimeConfig,
) -> V1Job:
    """Construct the Job that wraps the TaskPod."""
    init_containers = build_init_containers(task, config)
    main_containers = [build_ack_container(task, config)]

    pod_spec = V1PodSpec(
        init_containers=init_containers,
        containers=main_containers,
        restart_policy="Never",
        service_account_name=config.taskpod_service_account,
        # executors run user images: no token for them (see `build_trec`)
        automount_service_account_token=False,
        termination_grace_period_seconds=config.grace_period_seconds,
        volumes=pod_volumes(pvc_name, config),
        image_pull_secrets=(
            [V1LocalObjectReference(name=n) for n in config.image_pull_secrets] or None
        ),
    )

    return V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=V1ObjectMeta(
            name=job_name,
            namespace=config.taskpod_namespace,
            labels=labels,
        ),
        spec=V1JobSpec(
            backoff_limit=0,
            ttl_seconds_after_finished=config.job_ttl_seconds,
            active_deadline_seconds=config.active_deadline_seconds,
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(labels=labels),
                spec=pod_spec,
            ),
        ),
    )


def build_init_containers(task: TesTask, config: RuntimeConfig) -> list[V1Container]:
    """Init container order: trec (sidecar) → tif → exec-0..N → tof."""
    path_mounts = executor_path_mounts(task)
    containers: list[V1Container] = [build_trec(task, config, path_mounts)]

    dirs = task_dirs(task, path_mounts)
    if task.inputs or dirs:
        containers.append(build_tif(task, config, dirs))

    for idx, executor in enumerate(task.executors):
        containers.append(build_executor(executor, idx, config, path_mounts))

    if task.outputs:
        containers.append(build_tof(task, config))

    return containers


def attach_pvc_owner(
    pvc: V1PersistentVolumeClaim,
    job_uid: str,
    job_name: str,
) -> V1PersistentVolumeClaim:
    """Add an ownerReference from the PVC to the Job.

    Call after the Job is submitted to populate `pvc.metadata.ownerReferences`
    so kube-controller-manager garbage-collects the PVC when the Job is
    deleted. Returns the same object for chainability.

    `block_owner_deletion` stays off: with it on, clusters that enforce
    owner-reference permissions (e.g. OpenShift) require `update` on
    `jobs/finalizers`, which namespace admins often can't grant. Garbage
    collection still removes the PVC once the Job is gone; a foreground
    deletion of the Job just doesn't wait for it.
    """
    if pvc.metadata is None:
        pvc.metadata = V1ObjectMeta()
    pvc.metadata.owner_references = [
        V1OwnerReference(
            api_version="batch/v1",
            kind="Job",
            name=job_name,
            uid=job_uid,
            controller=True,
            block_owner_deletion=False,
        ),
    ]
    return pvc
