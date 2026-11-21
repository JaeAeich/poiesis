"""TaskPod manifest construction.

Pure functions that take a TES task and runtime configuration and return
the Kubernetes `Job` manifest that will run the task end-to-end, and the
PVC it shares between its containers.

The TaskPod's shape:

    init containers, in order:
        trec     — recorder native sidecar (restartPolicy: Always)
        tif      — input filer (only if the task has inputs, or
                    directories to create: `volumes.task_dirs`)
        exec-0   — first executor
        ...
        exec-N   — last executor
        tof      — output filer (only if the task has outputs)
    containers:
        pause    — placeholder; satisfies K8s' "must have a regular container"

All containers share one PVC mounted at the configured filer path; executors
also see it at the task's TES paths (`volumes.executor_path_mounts`). Only
trec, which watches the Pod, gets a ServiceAccount token
(`volumes.api_token_volume`); the Pod doesn't automount one, so executors
can't call the API. The PVC's `ownerReferences` point at the Job so
Kubernetes garbage-collects it when the Job is deleted.

Modules:

    job                — the entry point, `build_taskpod_job`; Pod spec and Job
    validation         — tasks the TaskPod can't run, rejected up front
    paths              — normalising TES paths and the rules for mounting them
    volumes            — the PVC, the Pod's volumes, every container's mounts
    executors          — the task's executor containers
    system_containers  — trec, tif, tof and ack, their env and security
    config             — `RuntimeConfig` and `PodSecurityEnforce`

The package is pure — no I/O, no kubernetes API calls. It constructs the
client-side model objects and returns them; the caller submits.
"""

from poiesis.core.taskpod.config import PodSecurityEnforce, RuntimeConfig
from poiesis.core.taskpod.job import (
    COMPONENT_LABEL,
    NAME_LABEL,
    TASK_LABEL,
    attach_pvc_owner,
    build_taskpod_job,
    job_name_for,
)
from poiesis.core.taskpod.volumes import (
    API_TOKEN_MOUNT_PATH,
    API_TOKEN_VOLUME_NAME,
    PG_CA_MOUNT_PATH,
    PG_CA_VOLUME_NAME,
    PVC_VOLUME_NAME,
)

__all__ = [
    "API_TOKEN_MOUNT_PATH",
    "API_TOKEN_VOLUME_NAME",
    "COMPONENT_LABEL",
    "NAME_LABEL",
    "PG_CA_MOUNT_PATH",
    "PG_CA_VOLUME_NAME",
    "PVC_VOLUME_NAME",
    "TASK_LABEL",
    "PodSecurityEnforce",
    "RuntimeConfig",
    "attach_pvc_owner",
    "build_taskpod_job",
    "job_name_for",
]
