"""Pod-level settings and per-executor resources: where they are decided.

This is the seam for scheduling and security features of the TaskPod.
Node selectors, tolerations, affinity, a Pod ``securityContext``
(``fsGroup``), GPUs, per-task ``backend_parameters`` and cpu/ram requests
and limits are added here, so the rest of the builder doesn't change when
they land. Today the functions return what the builder has always set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kubernetes.client import V1LocalObjectReference

if TYPE_CHECKING:
    from kubernetes.client import V1ResourceRequirements

    from poiesis.api.tes.models import TesExecutor, TesTask
    from poiesis.core.taskpod.config import RuntimeConfig


def pod_settings(task: TesTask, config: RuntimeConfig) -> dict[str, Any]:
    """Pod spec fields other than containers and volumes, as ``V1PodSpec`` kwargs.

    `job.build_job` passes them to ``V1PodSpec`` next to the containers and
    volumes. Scheduling (``node_selector``, ``tolerations``, ``affinity``)
    and the Pod ``security_context`` go here; ``task`` is passed so they
    can depend on the task's resources and backend parameters.
    """
    return {
        "restart_policy": "Never",
        "service_account_name": config.taskpod_service_account,
        # executors run user images: no token for them (see `build_trec`)
        "automount_service_account_token": False,
        "termination_grace_period_seconds": config.grace_period_seconds,
        "image_pull_secrets": (
            [V1LocalObjectReference(name=n) for n in config.image_pull_secrets] or None
        ),
    }


def executor_resources(
    executor: TesExecutor, task: TesTask, config: RuntimeConfig
) -> V1ResourceRequirements | None:
    """Resource requests and limits of an executor container.

    None today: executors run without requests or limits. cpu/ram from the
    task's ``resources``, and GPUs, go here.
    """
    return None
