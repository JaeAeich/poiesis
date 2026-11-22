"""Pod-level settings and per-executor resources: where they are decided.

This is the seam for scheduling and resource features of the TaskPod. The
task's TES ``resources`` and the operator's `SchedulingConfig` meet here:

    cpu_cores, ram_gb   → each executor's requests and limits
    zones               → required node affinity on the zone label
    preemptible         → the operator's preemptible node selector and
                            tolerations (ignored when none is configured)
    backend_parameters  → GPUs, a PriorityClass, a node pool (only the
                            keys the operator allows)

The Pod-level security context and the executors' come from the
operator's ``executor_security_enforce`` profile and overrides
(`pod_security_context`, `executor_security_context`).

Executors run one after another as init containers, so each gets the
task's full cpu and memory; Kubernetes schedules the Pod on the largest
init container request, not on their sum.
"""

from __future__ import annotations

import copy
import math
from typing import TYPE_CHECKING, Any

from kubernetes.client import (
    V1LocalObjectReference,
    V1PodSecurityContext,
    V1ResourceRequirements,
    V1SecurityContext,
)

from poiesis.core.k8s_json import from_json
from poiesis.core.taskpod.config import ZONE_LABEL, PodSecurityEnforce

if TYPE_CHECKING:
    from collections.abc import Mapping

    from poiesis.api.tes.models import TesExecutor, TesTask
    from poiesis.core.taskpod.config import (
        NodePlacement,
        RuntimeConfig,
        SchedulingConfig,
    )


def pod_settings(task: TesTask, config: RuntimeConfig) -> dict[str, Any]:
    """Pod spec fields other than containers and volumes, as ``V1PodSpec`` kwargs.

    `job.build_job` passes them to ``V1PodSpec`` next to the containers and
    volumes. The operator's node selector and tolerations come first; a
    preemptible task's and the task's node pool add to them (on the same
    node selector key, the later wins). Fields left None are not sent.
    """
    scheduling = config.scheduling
    params = backend_parameters(task, config)
    node_selector = dict(scheduling.node_selector)
    tolerations = list(scheduling.tolerations)
    for placement in _placements(task, params, scheduling):
        node_selector.update(placement.node_selector)
        tolerations.extend(placement.tolerations)
    return {
        "restart_policy": "Never",
        "service_account_name": config.taskpod_service_account,
        # executors run user images: no token for them (see `build_trec`)
        "automount_service_account_token": False,
        "termination_grace_period_seconds": config.grace_period_seconds,
        "image_pull_secrets": (
            [V1LocalObjectReference(name=n) for n in config.image_pull_secrets] or None
        ),
        "node_selector": node_selector or None,
        "tolerations": tolerations or None,
        "affinity": _affinity(task, scheduling),
        "priority_class_name": (
            priority_class(params, scheduling) or scheduling.priority_class_name
        ),
        "runtime_class_name": scheduling.runtime_class_name,
        "security_context": pod_security_context(config),
    }


#: Pod-level security context per executor profile. `restricted` fixes a
#: numeric non-root user, the poiesis image's 65532, so that images whose
#: ``USER`` is root or a name still start, and every container owns the
#: task volume alike (``fsGroup``).
_POD_PROFILES: dict[PodSecurityEnforce, dict[str, Any]] = {
    PodSecurityEnforce.RESTRICTED: {
        "runAsNonRoot": True,
        "runAsUser": 65532,
        "runAsGroup": 65532,
        "fsGroup": 65532,
        "fsGroupChangePolicy": "OnRootMismatch",
        "seccompProfile": {"type": "RuntimeDefault"},
    },
}

#: Executor container security context per profile. No
#: ``readOnlyRootFilesystem``: user images expect to write where they like.
_EXECUTOR_PROFILES: dict[PodSecurityEnforce, dict[str, Any]] = {
    PodSecurityEnforce.RESTRICTED: {
        "runAsNonRoot": True,
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "seccompProfile": {"type": "RuntimeDefault"},
    },
    # Capabilities stay: root images may need them (chown, writing into
    # directories tif created), and Pod Security baseline allows them.
    PodSecurityEnforce.BASELINE: {"allowPrivilegeEscalation": False},
}


def pod_security_context(config: RuntimeConfig) -> V1PodSecurityContext | None:
    """The TaskPod's Pod-level securityContext.

    The ``executor_security_enforce`` profile with the operator's
    ``pod_security_context`` keys over it. None when both are empty.

    Raises:
        ValueError: A key that ``V1PodSecurityContext`` doesn't have.
    """
    merged = _merged(
        _POD_PROFILES.get(config.executor_security_enforce, {}),
        config.pod_security_context,
    )
    return None if merged is None else from_json(V1PodSecurityContext, merged)


def executor_security_context(config: RuntimeConfig) -> V1SecurityContext | None:
    """An executor container's securityContext.

    The ``executor_security_enforce`` profile with the operator's
    ``executor_security_context`` keys over it. None when both are empty.

    Raises:
        ValueError: A key that ``V1SecurityContext`` doesn't have.
    """
    merged = _merged(
        _EXECUTOR_PROFILES.get(config.executor_security_enforce, {}),
        config.executor_security_context,
    )
    return None if merged is None else from_json(V1SecurityContext, merged)


def _merged(
    profile: Mapping[str, Any], overrides: Mapping[str, Any]
) -> dict[str, Any] | None:
    """``overrides`` deep-merged over a copy of ``profile``; None if empty.

    Objects merge key by key, so ``{capabilities: {add: [X]}}`` keeps the
    profile's ``drop``; any other value, lists included, replaces the
    profile's.
    """
    merged = copy.deepcopy(dict(profile))
    for key, value in overrides.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merged(current, value) or {}
        else:
            merged[key] = copy.deepcopy(value)
    return merged or None


def executor_resources(
    executor: TesExecutor, task: TesTask, config: RuntimeConfig
) -> V1ResourceRequirements | None:
    """Resource requests and limits of an executor container.

    Memory: request = limit = ``ram_gb``, as GiB. CPU: request =
    ``cpu_cores``, and the same limit unless the operator turned CPU limits
    off. GPUs (``gpu_count``): a limit on the operator's GPU resource. The
    operator's defaults apply when the task sets no cpu or ram. None when
    there is nothing to set.
    """
    scheduling = config.scheduling
    cpu, ram = cpu_ram(task, config)
    requests: dict[str, str] = {}
    limits: dict[str, str] = {}
    if cpu is not None:
        requests["cpu"] = str(cpu)
        if scheduling.cpu_limit:
            limits["cpu"] = str(cpu)
    if ram is not None:
        requests["memory"] = limits["memory"] = memory_quantity(ram)
    gpus = gpu_count(backend_parameters(task, config))
    if gpus:
        limits[scheduling.gpu_resource_name] = str(gpus)
    if not requests and not limits:
        return None
    return V1ResourceRequirements(requests=requests or None, limits=limits or None)


def cpu_ram(task: TesTask, config: RuntimeConfig) -> tuple[int | None, float | None]:
    """The task's ``cpu_cores`` and ``ram_gb``, or the operator's defaults.

    A value of zero or less counts as unset, as for ``disk_gb``.
    """
    resources = task.resources
    scheduling = config.scheduling
    cpu = resources.cpu_cores if resources is not None else None
    ram = resources.ram_gb if resources is not None else None
    if cpu is None or cpu <= 0:
        cpu = scheduling.default_cpu_cores
    if ram is None or ram <= 0:
        ram = scheduling.default_ram_gb
    return cpu, ram


def memory_quantity(ram_gb: float) -> str:
    """``ram_gb`` as a Kubernetes quantity, in GiB, rounded up to whole MiB."""
    mib = math.ceil(ram_gb * 1024)
    return f"{mib // 1024}Gi" if mib % 1024 == 0 else f"{mib}Mi"


def backend_parameters(task: TesTask, config: RuntimeConfig) -> dict[str, str]:
    """The task's ``backend_parameters`` the operator allows, keys lower case.

    TES keys are case insensitive. The values are not checked here.
    """
    resources = task.resources
    params = (resources.backend_parameters if resources is not None else None) or {}
    allowed = config.scheduling.backend_parameters
    return {k.lower(): v for k, v in params.items() if k.lower() in allowed}


def gpu_count(params: dict[str, str]) -> int | None:
    """``gpu_count`` as a whole number >= 0; None if unset or not one."""
    value = params.get("gpu_count")
    if value is None or not value.strip().isdigit():
        return None
    return int(value)


def priority_class(params: dict[str, str], scheduling: SchedulingConfig) -> str | None:
    """``priority_class`` if it is one the operator lists, else None."""
    value = params.get("priority_class")
    return value if value in scheduling.priority_classes else None


def node_pool(
    params: dict[str, str], scheduling: SchedulingConfig
) -> NodePlacement | None:
    """The operator's placement for ``node_pool``, None if unset or unknown."""
    value = params.get("node_pool")
    return scheduling.node_pools.get(value) if value is not None else None


def _placements(
    task: TesTask, params: dict[str, str], scheduling: SchedulingConfig
) -> list[NodePlacement]:
    """Placements added for this task: preemptible, then its node pool."""
    placements: list[NodePlacement] = []
    resources = task.resources
    if resources is not None and resources.preemptible and scheduling.preemptible:
        placements.append(scheduling.preemptible)
    pool = node_pool(params, scheduling)
    if pool is not None:
        placements.append(pool)
    return placements


def _affinity(task: TesTask, scheduling: SchedulingConfig) -> dict[str, Any] | None:
    """The operator's affinity, with the task's ``zones`` as a required term.

    Required node selector terms are ORed, so the zone expression is added
    to each of the operator's terms: the Pod needs one of the zones and
    one of the operator's terms. None when there is neither.
    """
    affinity = copy.deepcopy(dict(scheduling.affinity))
    resources = task.resources
    zones = (
        list(dict.fromkeys(z for z in (resources.zones or []) if z))
        if resources
        else []
    )
    if zones:
        node = affinity.setdefault("nodeAffinity", {})
        required = node.setdefault("requiredDuringSchedulingIgnoredDuringExecution", {})
        terms = required.get("nodeSelectorTerms") or [{}]
        for term in terms:
            term.setdefault("matchExpressions", []).append(
                {"key": ZONE_LABEL, "operator": "In", "values": list(zones)}
            )
        required["nodeSelectorTerms"] = terms
    return affinity or None
