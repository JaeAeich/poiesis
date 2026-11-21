"""Reject TES tasks the TaskPod can't run, before anything is created.

Every check raises ``ValueError``; the API translates this into HTTP 400.
"""

from __future__ import annotations

import math
import posixpath
from typing import TYPE_CHECKING

from poiesis.core import executor_shell
from poiesis.core.services.filer import filer_strategy_factory as _filer
from poiesis.core.taskpod.paths import is_within, normalised
from poiesis.core.taskpod.volumes import executor_path_mounts

if TYPE_CHECKING:
    from kubernetes.client import V1VolumeMount

    from poiesis.api.tes.models import TesTask
    from poiesis.core.taskpod.config import RuntimeConfig


#: Backend parameter keys this server knows how to honour. Empty until
#: we ship a backend feature that consumes one. Per TES spec, any key
#: not in this set is rejected with 400 when `backend_parameters_strict`
#: is true; non-strict tasks silently ignore unknowns.
_SUPPORTED_BACKEND_PARAMETERS: frozenset[str] = frozenset()


def reject_unsupported_features(task: TesTask, config: RuntimeConfig) -> None:
    """Reject TES features the single-Pod model or operator policy cannot honour.

    Raises ``ValueError``; the API translates this into HTTP 400.
    """
    for idx, inp in enumerate(task.inputs or []):
        # Inline `content` inputs carry no URL; the empty-scheme entry
        # in the filer registry handles them, so `can_input(None)` is True.
        if not _filer.can_input(inp.url):
            raise ValueError(
                f"inputs[{idx}].url scheme is not supported as a TES input: {inp.url!r}"
            )

    for idx, out in enumerate(task.outputs or []):
        if not _filer.can_output(out.url):
            raise ValueError(
                f"outputs[{idx}].url scheme is not supported as a TES output: "
                f"{out.url!r}"
            )

    # paths the executor can't be given (raises before anything is created)
    path_mounts = executor_path_mounts(task)
    reject_operator_mount_conflicts(path_mounts, config)
    reject_relative_stream_paths(task)

    reject_oversized_disk(task, config)

    resources = task.resources
    if (
        resources is not None
        and resources.backend_parameters_strict
        and resources.backend_parameters
    ):
        unknown = sorted(
            set(resources.backend_parameters) - _SUPPORTED_BACKEND_PARAMETERS
        )
        if unknown:
            msg = (
                f"resources.backend_parameters contains unsupported keys "
                f"under backend_parameters_strict=true: {unknown}"
            )
            raise ValueError(msg)


def reject_oversized_disk(task: TesTask, config: RuntimeConfig) -> None:
    """Reject TES requests whose ``disk_gb`` exceeds the operator cap.

    Cap is matched against the *rounded-up* size — the value the chart will
    actually try to provision — so the error names the same number an
    operator would see in ``kubectl get pvc``.
    """
    resources = task.resources
    if resources is None or resources.disk_gb is None or resources.disk_gb <= 0:
        return
    if config.pvc_max_size_gi is None:
        return
    rounded = max(1, math.ceil(float(resources.disk_gb)))
    if rounded > config.pvc_max_size_gi:
        raise ValueError(
            f"resources.disk_gb={resources.disk_gb} GiB exceeds the "
            f"operator-configured maximum of {config.pvc_max_size_gi} "
            "GiB. Ask your administrator to raise "
            "taskpods.persistence.maxSizeGi or reduce the request."
        )


def reject_relative_stream_paths(task: TesTask) -> None:
    """Reject ``stdin``/``stdout``/``stderr`` paths that aren't absolute.

    TES requires them to be absolute.
    """
    for idx, executor in enumerate(task.executors):
        for stream, path in executor_shell.streams(executor).items():
            if not posixpath.isabs(path):
                msg = f"executors[{idx}].{stream} must be an absolute path: {path!r}"
                raise ValueError(msg)


def reject_operator_mount_conflicts(
    path_mounts: list[V1VolumeMount], config: RuntimeConfig
) -> None:
    """Reject TES mounts at or below an operator mount (``extraVolumeMounts``).

    A mount at the same path is a duplicate ``mountPath``, which Kubernetes
    refuses when the Job is created, after the task is stored; one below it
    would need a mount point inside the operator's volume (e.g. a read-only
    reference volume).
    """
    for extra in config.taskpod_extra_volume_mounts:
        operator_path = extra.get("mountPath") if isinstance(extra, dict) else None
        if not operator_path:
            continue
        operator_path = normalised(operator_path)
        for mount in path_mounts:
            if is_within(mount.mount_path, operator_path):
                msg = (
                    f"TES path {mount.mount_path!r} is at or below "
                    f"{operator_path!r}, where the operator mounts a volume; "
                    "use another directory"
                )
                raise ValueError(msg)
