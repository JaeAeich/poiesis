"""TaskPod manifest construction.

Pure function that takes a TES task and runtime configuration and returns
the Kubernetes `Job` manifest that will run the task end-to-end.

The TaskPod's shape:

    init containers, in order:
        trec     — recorder native sidecar (restartPolicy: Always)
        tif      — input filer (only if the task has inputs)
        exec-0   — first executor
        ...
        exec-N   — last executor
        tof      — output filer (only if the task has outputs)
    containers:
        pause    — placeholder; satisfies K8s' "must have a regular container"

All containers share one PVC mounted at the configured filer path. The PVC's
`ownerReferences` point at the Job so Kubernetes garbage-collects it when
the Job is deleted.

This module is pure — no I/O, no kubernetes API calls. It constructs the
client-side model objects and returns them; the caller submits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from kubernetes.client import (
    V1Container,
    V1EnvVar,
    V1Job,
    V1JobSpec,
    V1LabelSelector,
    V1ObjectMeta,
    V1OwnerReference,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimSpec,
    V1PersistentVolumeClaimVolumeSource,
    V1PodSpec,
    V1PodTemplateSpec,
    V1ResourceRequirements,
    V1Volume,
    V1VolumeMount,
)

from poiesis.core.pod_status import PAUSE_NAME, TIF_NAME, TOF_NAME, TREC_NAME

if TYPE_CHECKING:
    from poiesis.api.tes.models import TesExecutor, TesTask


TASK_LABEL = "poiesis.io/task"
COMPONENT_LABEL = "app.kubernetes.io/component"
NAME_LABEL = "app.kubernetes.io/name"

DEFAULT_PVC_SIZE_GI = "1"
PVC_VOLUME_NAME = "task-data"


@dataclass(frozen=True)
class RuntimeConfig:
    """Cluster-side configuration needed to materialise a TaskPod.

    Held separately from the TES task itself so the TES request stays
    portable across deployments.

    Attributes:
        namespace:               Kubernetes namespace to submit into.
        poiesis_image:           Image for trec / tif / tof containers (one image, different commands).
        pause_image:             Image for the placeholder main container.
        pvc_storage_class:       Storage class for the Task PVC. None defers to the cluster default.
        pvc_access_mode:         Access mode for the Task PVC. Defaults to ReadWriteOnce.
        filer_pvc_mount_path:    Path at which the PVC is mounted in every container.
        image_pull_policy:       imagePullPolicy for every container.
        taskpod_service_account: SA bound to the TaskPod; needs RBAC for `get`/`watch`/`delete` on its own Pod.
        job_ttl_seconds:         ttlSecondsAfterFinished on the Job.
        active_deadline_seconds: activeDeadlineSeconds on the Job (covers stuck-Pending).
        grace_period_seconds:    terminationGracePeriodSeconds on the Pod.
        filer_resources:         Resource requests/limits for the TIF/TOF containers.
        recorder_resources:      Resource requests/limits for the TRec sidecar.
        pause_resources:         Resource requests/limits for the pause main container.
        extra_env:               Extra env vars injected into every container (database DSN, S3 creds, etc.).
    """

    namespace: str
    poiesis_image: str
    pause_image: str = "registry.k8s.io/pause:3.9"
    pvc_storage_class: str | None = None
    pvc_access_mode: str = "ReadWriteOnce"
    filer_pvc_mount_path: str = "/transfer"
    image_pull_policy: str = "IfNotPresent"
    taskpod_service_account: str | None = None
    job_ttl_seconds: int = 3600
    active_deadline_seconds: int = 3600
    grace_period_seconds: int = 30
    filer_resources: V1ResourceRequirements | None = None
    recorder_resources: V1ResourceRequirements | None = None
    pause_resources: V1ResourceRequirements | None = None
    extra_env: list[V1EnvVar] = field(default_factory=list)


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
    _reject_unsupported_features(task)

    task_id = task.id
    job_name = f"task-{task_id}"
    pvc_name = f"task-{task_id}-data"

    labels = _labels(task_id)
    pvc = _build_pvc(pvc_name, labels, task, config)
    job = _build_job(job_name, pvc_name, labels, task, config)
    return pvc, job


def _reject_unsupported_features(task: TesTask) -> None:
    """Fail fast on TES features the single-Pod model cannot honour."""
    for idx, ex in enumerate(task.executors):
        if ex.ignore_error:
            msg = (
                f"executor[{idx}].ignore_error=True is not supported: "
                "Kubernetes init containers abort on first failure with no per-container override"
            )
            raise ValueError(msg)


def _labels(task_id: str) -> dict[str, str]:
    """Canonical labels every TaskPod resource carries."""
    return {
        TASK_LABEL: task_id,
        NAME_LABEL: "poiesis",
        COMPONENT_LABEL: "taskpod",
    }


def _build_pvc(
    pvc_name: str,
    labels: dict[str, str],
    task: TesTask,
    config: RuntimeConfig,
) -> V1PersistentVolumeClaim:
    """Construct the shared Task PVC."""
    disk_gb = (
        task.resources.disk_gb if task.resources and task.resources.disk_gb else None
    )
    if disk_gb is not None:
        # Render whole numbers without a trailing .0 for readability.
        storage = f"{int(disk_gb)}Gi" if float(disk_gb).is_integer() else f"{disk_gb}Gi"
    else:
        storage = f"{DEFAULT_PVC_SIZE_GI}Gi"

    return V1PersistentVolumeClaim(
        api_version="v1",
        kind="PersistentVolumeClaim",
        metadata=V1ObjectMeta(
            name=pvc_name,
            namespace=config.namespace,
            labels=labels,
        ),
        spec=V1PersistentVolumeClaimSpec(
            access_modes=[config.pvc_access_mode],
            storage_class_name=config.pvc_storage_class,
            resources=V1ResourceRequirements(requests={"storage": storage}),
        ),
    )


def _build_job(
    job_name: str,
    pvc_name: str,
    labels: dict[str, str],
    task: TesTask,
    config: RuntimeConfig,
) -> V1Job:
    """Construct the Job that wraps the TaskPod."""
    init_containers = _build_init_containers(task, config)
    main_containers = [_build_pause_container(config)]
    volumes = [
        V1Volume(
            name=PVC_VOLUME_NAME,
            persistent_volume_claim=V1PersistentVolumeClaimVolumeSource(
                claim_name=pvc_name
            ),
        ),
    ]

    pod_spec = V1PodSpec(
        init_containers=init_containers,
        containers=main_containers,
        restart_policy="Never",
        service_account_name=config.taskpod_service_account,
        termination_grace_period_seconds=config.grace_period_seconds,
        volumes=volumes,
    )

    return V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=V1ObjectMeta(
            name=job_name,
            namespace=config.namespace,
            labels=labels,
        ),
        spec=V1JobSpec(
            backoff_limit=0,
            ttl_seconds_after_finished=config.job_ttl_seconds,
            active_deadline_seconds=config.active_deadline_seconds,
            selector=V1LabelSelector(match_labels=labels),
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(labels=labels),
                spec=pod_spec,
            ),
        ),
    )


def _build_init_containers(task: TesTask, config: RuntimeConfig) -> list[V1Container]:
    """Init container order: trec (sidecar) → tif → exec-0..N → tof."""
    containers: list[V1Container] = [_build_trec(task, config)]

    if task.inputs:
        containers.append(_build_tif(task, config))

    for idx, executor in enumerate(task.executors):
        containers.append(_build_executor(executor, idx, config))

    if task.outputs:
        containers.append(_build_tof(task, config))

    return containers


def _build_trec(task: TesTask, config: RuntimeConfig) -> V1Container:
    """Recorder native sidecar.

    Init container with `restartPolicy: Always` — the K8s 1.29+ native-sidecar
    form. The container stays alive for the lifetime of the Pod and observes
    init-phase container transitions.
    """
    container = V1Container(
        name=TREC_NAME,
        image=config.poiesis_image,
        image_pull_policy=config.image_pull_policy,
        command=["poiesis", "trec", "--task-id", _require_id(task)],
        env=list(config.extra_env),
        volume_mounts=[_pvc_mount(config)],
        resources=config.recorder_resources,
    )
    object.__setattr__(container, "restart_policy", "Always")
    return container


def _build_tif(task: TesTask, config: RuntimeConfig) -> V1Container:
    """Input filer container."""
    return V1Container(
        name=TIF_NAME,
        image=config.poiesis_image,
        image_pull_policy=config.image_pull_policy,
        command=["poiesis", "tif", "--task-id", _require_id(task)],
        env=list(config.extra_env),
        volume_mounts=[_pvc_mount(config)],
        resources=config.filer_resources,
    )


def _build_tof(task: TesTask, config: RuntimeConfig) -> V1Container:
    """Output filer container."""
    return V1Container(
        name=TOF_NAME,
        image=config.poiesis_image,
        image_pull_policy=config.image_pull_policy,
        command=["poiesis", "tof", "--task-id", _require_id(task)],
        env=list(config.extra_env),
        volume_mounts=[_pvc_mount(config)],
        resources=config.filer_resources,
    )


def _build_executor(
    executor: TesExecutor,
    index: int,
    config: RuntimeConfig,
) -> V1Container:
    """One executor init container.

    Image, command, workdir, env, stdin/stdout/stderr paths come from the
    TesExecutor; Poiesis does not wrap the user's command.
    """
    env = [V1EnvVar(name=k, value=v) for k, v in (executor.env or {}).items()]
    return V1Container(
        name=f"exec-{index}",
        image=executor.image,
        image_pull_policy=config.image_pull_policy,
        command=list(executor.command),
        working_dir=executor.workdir,
        env=env or None,
        volume_mounts=[_pvc_mount(config)],
        stdin=bool(executor.stdin),
    )


def _build_pause_container(config: RuntimeConfig) -> V1Container:
    """Placeholder main container.

    K8s requires `containers:` to be non-empty. `pause` blocks until SIGTERM
    and is essentially free at runtime.
    """
    return V1Container(
        name=PAUSE_NAME,
        image=config.pause_image,
        image_pull_policy=config.image_pull_policy,
        resources=config.pause_resources,
    )


def _pvc_mount(config: RuntimeConfig) -> V1VolumeMount:
    return V1VolumeMount(name=PVC_VOLUME_NAME, mount_path=config.filer_pvc_mount_path)


def _require_id(task: TesTask) -> str:
    """Return task.id, asserting it is set."""
    if task.id is None:
        msg = "TesTask.id must be set before manifest construction"
        raise ValueError(msg)
    return task.id


def attach_pvc_owner(
    pvc: V1PersistentVolumeClaim,
    job_uid: str,
    job_name: str,
) -> V1PersistentVolumeClaim:
    """Add an ownerReference from the PVC to the Job.

    Call after the Job is submitted to populate `pvc.metadata.ownerReferences`
    so kube-controller-manager garbage-collects the PVC when the Job is
    deleted. Returns the same object for chainability.
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
            block_owner_deletion=True,
        ),
    ]
    return pvc
