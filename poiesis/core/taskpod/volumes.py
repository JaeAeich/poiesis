"""The task PVC, the Pod's volumes, and what each container mounts."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from kubernetes.client import (
    V1ConfigMapProjection,
    V1ConfigMapVolumeSource,
    V1DownwardAPIProjection,
    V1DownwardAPIVolumeFile,
    V1KeyToPath,
    V1ObjectFieldSelector,
    V1ObjectMeta,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimSpec,
    V1PersistentVolumeClaimVolumeSource,
    V1ProjectedVolumeSource,
    V1ResourceRequirements,
    V1ServiceAccountTokenProjection,
    V1Volume,
    V1VolumeMount,
    V1VolumeProjection,
)

from poiesis.core.constants import FILER_PVC_PATH, IDENTITY_TOKEN_DIR
from poiesis.core.taskpod.paths import (
    depth,
    dir_candidates,
    is_within,
    mount_path,
    normalised,
    reject_parent_components,
    reject_paths_below_file_inputs,
)

if TYPE_CHECKING:
    from poiesis.core.taskpod.config import RuntimeConfig
    from poiesis.tes.models import TesTask


PVC_VOLUME_NAME = "task-data"
PG_CA_VOLUME_NAME = "postgres-ca"
PG_CA_MOUNT_PATH = "/etc/ssl/poiesis"
API_TOKEN_VOLUME_NAME = "kube-api-token"  # noqa: S105 - a volume name
#: Where in-cluster clients look for the token, CA and namespace.
API_TOKEN_MOUNT_PATH = "/var/run/secrets/kubernetes.io/serviceaccount"  # noqa: S105
#: The kubelet rotates the token before it expires; the client rereads it.
_API_TOKEN_EXPIRATION_SECONDS = 3600


def build_pvc(
    pvc_name: str,
    labels: dict[str, str],
    task: TesTask,
    config: RuntimeConfig,
) -> V1PersistentVolumeClaim:
    """Construct the shared Task PVC.

    Merges chart-supplied labels/annotations onto the per-task labels; the
    task labels win on key collision so internal selectors (poiesis.io/task)
    can't be redefined by operator config.
    """
    size_gi = resolve_pvc_size_gi(task, config)
    merged_labels = {**config.pvc_labels, **labels}
    return V1PersistentVolumeClaim(
        api_version="v1",
        kind="PersistentVolumeClaim",
        metadata=V1ObjectMeta(
            name=pvc_name,
            namespace=config.taskpod_namespace,
            labels=merged_labels,
            annotations=dict(config.pvc_annotations) or None,
        ),
        spec=V1PersistentVolumeClaimSpec(
            access_modes=list(config.pvc_access_modes),
            storage_class_name=config.pvc_storage_class,
            resources=V1ResourceRequirements(requests={"storage": f"{size_gi}Gi"}),
        ),
    )


def resolve_pvc_size_gi(task: TesTask, config: RuntimeConfig) -> int:
    """Pick the PVC size in whole GiB.

    TES `resources.disk_gb` is a float; Kubernetes only accepts integer-Gi
    quantities, so we round up to the nearest GiB to avoid silently
    under-provisioning. Falls back to ``config.pvc_default_size_gi`` when
    the request omits ``disk_gb`` or sets it to zero.
    """
    requested = task.resources.disk_gb if task.resources else None
    if requested and requested > 0:
        return max(1, math.ceil(float(requested)))
    return max(1, config.pvc_default_size_gi)


def pod_volumes(pvc_name: str, config: RuntimeConfig) -> list[Any]:
    """``spec.volumes`` of the TaskPod.

    The task PVC, the API token (`api_token_volume`), the workload-identity
    tokens (`identity_token_volume`), the Postgres CA when configured, then
    the operator's ``taskpods.extraVolumes``.

    ``Any`` because operator extras come in as raw dicts; the kubernetes
    client's serialiser walks both V1Volume instances and dicts and
    Kubernetes admission validates the actual shape.
    """
    volumes: list[Any] = [
        V1Volume(
            name=PVC_VOLUME_NAME,
            persistent_volume_claim=V1PersistentVolumeClaimVolumeSource(
                claim_name=pvc_name
            ),
        ),
        api_token_volume(),
        *(
            identity_token_volume(provider, audience)
            for provider, audience in sorted(config.filer_identity_audiences.items())
        ),
    ]
    if config.postgres_ca_configmap:
        volumes.append(
            V1Volume(
                name=PG_CA_VOLUME_NAME,
                config_map=V1ConfigMapVolumeSource(
                    name=config.postgres_ca_configmap,
                    default_mode=0o0444,
                ),
            )
        )
    volumes.extend(config.taskpod_extra_volumes)
    return volumes


def api_token_volume() -> V1Volume:
    """The ServiceAccount token, CA and namespace, as the kubelet automounts them.

    Same files as the automounted ``kube-api-access-*`` volume, so
    in-cluster config works unchanged; mounted into trec only.
    """
    return V1Volume(
        name=API_TOKEN_VOLUME_NAME,
        projected=V1ProjectedVolumeSource(
            default_mode=0o644,
            sources=[
                V1VolumeProjection(
                    service_account_token=V1ServiceAccountTokenProjection(
                        path="token",
                        expiration_seconds=_API_TOKEN_EXPIRATION_SECONDS,
                    ),
                ),
                V1VolumeProjection(
                    config_map=V1ConfigMapProjection(
                        name="kube-root-ca.crt",
                        items=[V1KeyToPath(key="ca.crt", path="ca.crt")],
                    ),
                ),
                V1VolumeProjection(
                    downward_api=V1DownwardAPIProjection(
                        items=[
                            V1DownwardAPIVolumeFile(
                                path="namespace",
                                field_ref=V1ObjectFieldSelector(
                                    api_version="v1",
                                    field_path="metadata.namespace",
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        ),
    )


def api_token_mount() -> V1VolumeMount:
    """Mount of `api_token_volume` where in-cluster clients look for it."""
    return V1VolumeMount(
        name=API_TOKEN_VOLUME_NAME,
        mount_path=API_TOKEN_MOUNT_PATH,
        read_only=True,
    )


def identity_token_volume(provider: str, audience: str) -> V1Volume:
    """A ServiceAccount token for `audience`, which TIF/TOF trade for cloud keys.

    The provider's STS (AWS, Google) or identity platform (Azure) accepts
    it from the cluster's OIDC issuer in exchange for the role, identity
    or service account the operator named.
    Only TIF and TOF mount it (`identity_token_mounts`): executors run user
    images and never get it, nor the Pod's automounted token.
    """
    return V1Volume(
        name=identity_token_volume_name(provider),
        projected=V1ProjectedVolumeSource(
            default_mode=0o644,
            sources=[
                V1VolumeProjection(
                    service_account_token=V1ServiceAccountTokenProjection(
                        path="token",
                        audience=audience,
                        expiration_seconds=_API_TOKEN_EXPIRATION_SECONDS,
                    ),
                ),
            ],
        ),
    )


def identity_token_volume_name(provider: str) -> str:
    """Volume name of `provider`'s identity token."""
    return f"{provider}-identity-token"


def identity_token_path(provider: str) -> str:
    """Where TIF/TOF read `provider`'s identity token."""
    return f"{IDENTITY_TOKEN_DIR}/{provider}/token"


def identity_token_mounts(config: RuntimeConfig) -> list[V1VolumeMount]:
    """Mounts of the identity tokens, for TIF and TOF only."""
    return [
        V1VolumeMount(
            name=identity_token_volume_name(provider),
            mount_path=f"{IDENTITY_TOKEN_DIR}/{provider}",
            read_only=True,
        )
        for provider in sorted(config.filer_identity_audiences)
    ]


def pvc_mount() -> V1VolumeMount:
    """The task PVC at the filers' staging path."""
    return V1VolumeMount(name=PVC_VOLUME_NAME, mount_path=FILER_PVC_PATH)


def poiesis_mounts(config: RuntimeConfig) -> list[Any]:
    """Volume mounts every poiesis-owned container that touches Postgres gets.

    Includes operator-supplied extras (``taskpods.extraVolumeMounts``).
    Return type is ``list[Any]`` because the kubernetes client tolerates
    dict entries inline; we keep operator dicts as-is rather than
    round-tripping through V1VolumeMount.
    """
    mounts: list[Any] = [pvc_mount()]
    if config.postgres_ca_configmap:
        mounts.append(
            V1VolumeMount(
                name=PG_CA_VOLUME_NAME,
                mount_path=PG_CA_MOUNT_PATH,
                read_only=True,
            )
        )
    mounts.extend(config.taskpod_extra_volume_mounts)
    return mounts


def executor_mounts(
    config: RuntimeConfig, path_mounts: list[V1VolumeMount]
) -> list[Any]:
    """Volume mounts for an executor (user-supplied) container.

    Executors get the PVC for staging files, the PVC again at each TES path
    of the task (``path_mounts``, see ``executor_path_mounts``), and the
    operator-supplied ``taskpods.extraVolumeMounts`` — the reference-data
    use case explicitly requires the mount to reach user code.
    """
    return [pvc_mount(), *path_mounts, *config.taskpod_extra_volume_mounts]


def executor_path_mounts(task: TesTask) -> list[V1VolumeMount]:
    """Mount the PVC at each TES path so the executor sees what the filers see.

    TIF stages ``inputs[].path`` to ``<FILER_PVC_PATH>/<path>`` and TOF
    collects ``outputs[].path`` from there. A ``subPath`` mount of
    ``<path>`` at ``<path>`` shows the executor that same PVC location at
    the path the task declares, so reads and writes meet. Mounted, as in
    v0.1:

    - task ``volumes`` and DIRECTORY inputs and outputs at their path;
    - FILE inputs at their path (TIF has created the file by then);
    - FILE outputs at their parent directory (a missing file can't be the
    target of a ``subPath`` mount: the kubelet would create a directory);
    - outputs with wildcards, FILE or DIRECTORY, at the directory before
    the first wildcard: TOF globs ``<FILER_PVC_PATH>/<path>`` whatever
    ``path_prefix`` is, so the mount must cover every match.

    A path under another mounted path already shows through that mount, so
    only the outermost ones are kept. The kubelet creates the mount points
    that don't exist yet on the PVC, with the mode of the volume root; TIF
    creates the other directories (`task_dirs`).

    Raises ``ValueError`` (HTTP 400) for a path that isn't absolute, that
    has a ``..`` component, that would mean mounting ``/``, that lies in
    the filers' staging directory, or that is below a FILE input.
    """
    reject_parent_components(task)

    candidates = {inp.path for inp in task.inputs or []} | dir_candidates(task)

    reject_paths_below_file_inputs(task)

    mount_paths: list[str] = []
    for path in sorted({mount_path(p) for p in candidates}, key=depth):
        if not any(is_within(path, outer) for outer in mount_paths):
            mount_paths.append(path)

    return [
        V1VolumeMount(name=PVC_VOLUME_NAME, mount_path=path, sub_path=path[1:])
        for path in sorted(mount_paths)
    ]


def task_dirs(task: TesTask, path_mounts: list[V1VolumeMount]) -> list[str]:
    """Directories TIF creates on the PVC before the executors run.

    TES ``volumes`` are empty directories the executors can use, and the
    other directories `executor_path_mounts` would mount (``DIRECTORY``
    outputs, the directory of a ``FILE`` output or before a wildcard)
    should exist as well. The kubelet creates those that are mount points;
    one below another mounted path (Sprocket's ``/mnt/task/usage`` volume
    under ``/mnt/task``) has no mount of its own, so TIF creates it, after
    staging the inputs, with the mode the kubelet gives mount points.
    Input paths are left to TIF's staging.
    """
    mount_points = {mount.mount_path for mount in path_mounts}
    inputs = {normalised(inp.path) for inp in task.inputs or []}
    dirs = {normalised(path) for path in dir_candidates(task)}
    return sorted(dirs - mount_points - inputs)
