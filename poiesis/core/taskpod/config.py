"""Cluster-side configuration of a TaskPod: `RuntimeConfig` and its enums."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kubernetes.client import V1EnvVar, V1ResourceRequirements


#: Floor for the per-task scratch PVC when neither the TES request nor the
#: operator-configured default supplies a size. Kept conservative because a
#: misconfigured chart should still produce *something* mountable instead of
#: failing manifest construction.
_FALLBACK_PVC_SIZE_GI = 1


#: ``backend_parameters`` keys this server can honour; an operator turns
#: each on (``SchedulingConfig.backend_parameters``). Lower case: TES keys
#: are case insensitive.
BACKEND_PARAMETERS: frozenset[str] = frozenset(
    {"gpu_count", "node_pool", "priority_class"}
)

#: Node label a task's TES ``zones`` are matched against.
ZONE_LABEL = "topology.kubernetes.io/zone"


class PodSecurityEnforce(StrEnum):
    """How strictly to lock down poiesis-owned TaskPod containers.

    Executor containers run user-supplied images and are always exempt;
    operators that need them constrained must run TaskPods in a namespace
    with the PodSecurity admission controller configured at the cluster
    level.
    """

    RESTRICTED = "restricted"
    BASELINE = "baseline"
    OFF = "off"


@dataclass(frozen=True)
class NodePlacement:
    """A node selector and tolerations, as Kubernetes JSON (camelCase).

    Used for preemptible nodes and for the node pools a task can pick.
    """

    node_selector: Mapping[str, str] = field(default_factory=dict)
    tolerations: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class SchedulingConfig:
    """Where TaskPods run and what their executors may use.

    Sourced from ``taskpods.resources``, ``nodeSelector``, ``tolerations``,
    ``affinity``, ``priorityClassName``, ``runtimeClassName``,
    ``preemptible``, ``gpu`` and ``backendParameters`` in the chart. The
    defaults leave the Pod as it was before these settings existed: no
    executor requests or limits, no scheduling constraints.

    Attributes:
        default_cpu_cores: CPU cores of each executor when the task sets
            no ``cpu_cores``. None: no CPU request or limit.
        default_ram_gb: Memory (GiB) of each executor when the task sets
            no ``ram_gb``. None: no memory request or limit.
        max_cpu_cores: Largest ``cpu_cores`` accepted; more is a 400 at
            submit. None: no maximum.
        max_ram_gb: Largest ``ram_gb`` accepted; more is a 400. None: no
            maximum.
        cpu_limit: Whether executors get a CPU limit equal to their
            request. False sets the request only, for clusters that avoid
            CPU limits (throttling).
        node_selector: ``nodeSelector`` of every TaskPod.
        tolerations: Tolerations of every TaskPod.
        affinity: ``affinity`` of every TaskPod (Kubernetes JSON). A task's
            ``zones`` are added to its required node affinity.
        priority_class_name: ``priorityClassName`` of every TaskPod, unless
            the task picks one (``priority_class``).
        runtime_class_name: ``runtimeClassName`` of every TaskPod.
        preemptible: Node selector and tolerations added for tasks with
            ``preemptible: true``. None: ``preemptible`` is ignored.
        backend_parameters: ``backend_parameters`` keys honoured, lower
            case; a subset of `BACKEND_PARAMETERS`. Others are ignored, or
            a 400 under ``backend_parameters_strict``.
        gpu_resource_name: Extended resource a task's ``gpu_count`` sets
            as a limit on each executor.
        max_gpu_count: Largest ``gpu_count`` accepted; more is a 400.
            None: no maximum.
        priority_classes: PriorityClasses a task may pick with
            ``priority_class``.
        node_pools: Name → placement a task may pick with ``node_pool``.
    """

    default_cpu_cores: int | None = None
    default_ram_gb: float | None = None
    max_cpu_cores: int | None = None
    max_ram_gb: float | None = None
    cpu_limit: bool = True
    node_selector: Mapping[str, str] = field(default_factory=dict)
    tolerations: tuple[Mapping[str, Any], ...] = ()
    affinity: Mapping[str, Any] = field(default_factory=dict)
    priority_class_name: str | None = None
    runtime_class_name: str | None = None
    preemptible: NodePlacement | None = None
    backend_parameters: frozenset[str] = frozenset()
    gpu_resource_name: str = "nvidia.com/gpu"
    max_gpu_count: int | None = None
    priority_classes: tuple[str, ...] = ()
    node_pools: Mapping[str, NodePlacement] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeConfig:
    """Cluster-side configuration needed to materialise a TaskPod.

    Held separately from the TES task itself so the TES request stays
    portable across deployments.

    Attributes:
        taskpod_namespace: Kubernetes namespace to submit TaskPods into.
            May differ from the control-plane namespace.
        poiesis_image: Image for every poiesis-owned container
            (trec, tif, tof, ack).
        pvc_storage_class: Storage class for the Task PVC. None defers
            to the cluster default. The sentinel ``""`` (empty string)
            explicitly disables dynamic provisioning and requires a
            pre-bound PV — matches the kubectl convention.
        pvc_access_modes: PVC access modes applied to every task. Cluster
            property, not a TES knob: every task in a single deployment
            runs on one node so RWO is sufficient, but NFS / CephFS
            clusters need RWX since their CSI driver doesn't support RWO.
        pvc_default_size_gi: Size used when a TES request omits
            ``resources.disk_gb``.
        pvc_max_size_gi: Hard upper bound enforced at submit time. A TES
            request with ``disk_gb`` over this is rejected with a 400 by
            ``validation.reject_unsupported_features``. None disables the
            cap.
        pvc_labels: Labels merged onto every per-task PVC. Use for cost
            allocation, backup operator selectors, data classification.
        pvc_annotations: Annotations merged onto every per-task PVC. Use
            for backup operator opt-in (Velero/Kasten), compliance tags.
        image_pull_policy: imagePullPolicy for every container.
        taskpod_service_account: SA bound to the TaskPod; needs RBAC for
            `get`/`list`/`watch` on its own Pod and `get` on `pods/log`.
            Its token is mounted into trec only.
        job_ttl_seconds: ttlSecondsAfterFinished on the Job. None omits
            the field entirely → Job (and PVC via owner ref) is retained
            until manually deleted. Use for audit-retention deployments.
        active_deadline_seconds: activeDeadlineSeconds on the Job: the
            task's time limit, counted from the Job's start (so it also
            ends a Pod that is never scheduled). None omits the field →
            no limit. Sourced from ``taskpods.activeDeadlineSeconds``.
        grace_period_seconds: terminationGracePeriodSeconds on the Pod.
        pod_security_enforce: `restricted` | `baseline` | `off`. Applies to
            poiesis-owned containers only; executor containers run user
            images and are deliberately exempt.
        image_pull_secrets: Secret names attached to every TaskPod for
            pulling images from private registries.
        postgres_ca_configmap: ConfigMap name (key `ca.crt`) mounted at
            `/etc/ssl/poiesis` on poiesis-owned containers so asyncpg can
            validate the Postgres server cert via `sslrootcert=` in
            DATABASE_URL. None disables the mount.
        filer_resources: Resource requests/limits for TIF/TOF containers.
        recorder_resources: Resource requests/limits for the TRec sidecar.
        ack_resources: Resource requests/limits for the terminal `ack`
            container.
        extra_env: Chart-internal env vars injected into every poiesis-owned
            container (database DSN, S3 creds, etc.). Populated by the API
            from Settings; not directly operator-controllable.
        taskpod_extra_env: Operator-supplied env vars injected into every
            poiesis-owned container (trec/tif/tof/ack). Sourced from
            ``taskpods.extraEnv`` in the chart. Executors are *not*
            covered by this — operators shouldn't silently mutate the
            environment of user-supplied images.
        taskpod_extra_volumes: Operator-supplied volumes appended to every
            TaskPod's ``spec.volumes``. Sourced from
            ``taskpods.extraVolumes``. Each entry is a dict shaped like
            a Kubernetes V1Volume.
        taskpod_extra_volume_mounts: Operator-supplied volume mounts
            appended to every container (poiesis-owned AND executors,
            because the reference-data use case requires executors to see
            the mount). Each entry is a dict shaped like V1VolumeMount.
        output_glob_fallback: When True, an output glob that matches no
            file makes TOF upload everything under the output's
            ``path_prefix`` instead of nothing. Sourced from
            ``taskpods.outputGlobFallback``; off by default.
        file_url_roots: Directories `file://` URLs may point into, passed
            to TIF/TOF. Sourced from ``taskpods.fileUrlRoots``; empty turns
            the scheme off.
        ftp_enabled: Whether `ftp://` and `ftps://` URLs may be used.
            Sourced from ``taskpods.ftp.enabled``; on by default. False
            sets ``POIESIS_FTP_ENABLED=false`` on TIF/TOF.
        drs_enabled: Whether `drs://` inputs may be used. Sourced from
            ``taskpods.drs.enabled``; off by default.
        drs_allowed_hosts: Hosts `drs://` URIs may name
            (``taskpods.drs.allowedHosts``); empty allows any host.
        drs_secret: Secret in the TaskPod namespace whose
            ``DRS_BEARER_TOKEN`` key TIF, and no other container, sends to
            DRS servers. Sourced from ``taskpods.drs.existingSecret``.
        s3_configured: Whether the operator enabled S3 (``s3.enabled``,
            a Secret with keys, or a role for workload identity). False
            makes submit refuse `s3://` inputs and outputs, which would
            fail in the Pod, and leaves `s3://` out of service-info.
        gcs_configured: The same for Google Cloud Storage (`gs://`).
        azure_configured: The same for Azure Blob Storage (`az://`).
        filer_env: Env vars set on TIF and TOF only: object-store options
            and workload-identity settings. Not on trec, ack or executors.
        filer_identity_audiences: Provider → audience of a ServiceAccount
            token projected into TIF and TOF only, at
            ``IDENTITY_TOKEN_DIR/<provider>/token``, which the provider's
            SDK trades for cloud credentials (`volumes.identity_token_volume`).
        log_format: Log format passed to trec/tif/tof (``json`` or
            ``text``). Sourced from ``logging.format``; None passes
            nothing, and they choose by whether stderr is a terminal.
        scheduling: Executor resources, Pod scheduling and the
            ``backend_parameters`` honoured (`SchedulingConfig`).
    """

    taskpod_namespace: str
    poiesis_image: str
    pvc_storage_class: str | None = None
    pvc_access_modes: tuple[str, ...] = ("ReadWriteOnce",)
    pvc_default_size_gi: int = _FALLBACK_PVC_SIZE_GI
    pvc_max_size_gi: int | None = None
    pvc_labels: Mapping[str, str] = field(default_factory=dict)
    pvc_annotations: Mapping[str, str] = field(default_factory=dict)
    image_pull_policy: str = "IfNotPresent"
    taskpod_service_account: str | None = None
    job_ttl_seconds: int | None = 3600
    active_deadline_seconds: int | None = 3600
    grace_period_seconds: int = 30
    pod_security_enforce: PodSecurityEnforce = PodSecurityEnforce.RESTRICTED
    image_pull_secrets: tuple[str, ...] = ()
    # Name of a ConfigMap holding the Postgres CA bundle (key `ca.crt`).
    # When set, the ConfigMap is mounted read-only at /etc/ssl/poiesis on
    # every poiesis-owned container so asyncpg can validate the server cert
    # via `sslrootcert=` in DATABASE_URL.
    postgres_ca_configmap: str | None = None
    filer_resources: V1ResourceRequirements | None = None
    recorder_resources: V1ResourceRequirements | None = None
    ack_resources: V1ResourceRequirements | None = None
    extra_env: list[V1EnvVar] = field(default_factory=list)
    taskpod_extra_env: list[V1EnvVar] = field(default_factory=list)
    taskpod_extra_volumes: list[dict[str, Any]] = field(default_factory=list)
    taskpod_extra_volume_mounts: list[dict[str, Any]] = field(default_factory=list)
    output_glob_fallback: bool = False
    file_url_roots: tuple[str, ...] = ()
    ftp_enabled: bool = True
    drs_enabled: bool = False
    drs_allowed_hosts: tuple[str, ...] = ()
    drs_secret: str | None = None
    s3_configured: bool = True
    log_format: str | None = None
    gcs_configured: bool = False
    azure_configured: bool = False
    filer_env: list[V1EnvVar] = field(default_factory=list)
    filer_identity_audiences: Mapping[str, str] = field(default_factory=dict)
    scheduling: SchedulingConfig = field(default_factory=SchedulingConfig)

    def storage_enabled(self, scheme: str) -> bool:
        """False for an object-store scheme whose provider is not enabled."""
        return {
            "s3": self.s3_configured,
            "gs": self.gcs_configured,
            "az": self.azure_configured,
        }.get(scheme, True)
