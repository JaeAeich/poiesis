"""Reject TES tasks the TaskPod can't run, before anything is created.

Every check raises ``ValueError``; the API translates this into HTTP 400.
"""

from __future__ import annotations

import math
import posixpath
from typing import TYPE_CHECKING

from poiesis.api.tes.models import TesFileType
from poiesis.core import executor_shell
from poiesis.core.services.filer import filer_strategy_factory as _filer
from poiesis.core.taskpod.paths import is_within, normalised
from poiesis.core.taskpod.pod import (
    backend_parameters,
    gpu_count,
    node_pool,
    priority_class,
)
from poiesis.core.taskpod.volumes import executor_path_mounts

if TYPE_CHECKING:
    from kubernetes.client import V1VolumeMount

    from poiesis.api.tes.models import TesTask
    from poiesis.core.taskpod.config import RuntimeConfig


def reject_unsupported_features(task: TesTask, config: RuntimeConfig) -> None:
    """Reject TES features the single-Pod model or operator policy cannot honour.

    Raises ``ValueError``; the API translates this into HTTP 400.
    """
    for idx, inp in enumerate(task.inputs or []):
        if not inp.url and inp.content is None:
            raise ValueError(f"inputs[{idx}] must set url or content")
        # Inline `content` wins over `url`; the empty-scheme entry in the
        # filer registry handles it, so `can_input(None)` is True.
        url = _filer.input_url(inp)
        reject_refused_url(f"inputs[{idx}].url", url)
        if not _filer.can_input(url):
            raise ValueError(
                f"inputs[{idx}].url scheme is not supported as a TES input: {inp.url!r}"
            )
        if inp.type == TesFileType.DIRECTORY:
            reject_unstageable_directory(f"inputs[{idx}]", url)
        reject_unconfigured_storage(f"inputs[{idx}].url", url, config)

    for idx, out in enumerate(task.outputs or []):
        if _filer.scheme(out.url) != "drs":
            reject_refused_url(f"outputs[{idx}].url", out.url)
        if not _filer.can_output(out.url):
            raise ValueError(
                f"outputs[{idx}].url scheme is not supported as a TES output: "
                f"{out.url!r}"
            )
        reject_unconfigured_storage(f"outputs[{idx}].url", out.url, config)

    # paths the executor can't be given (raises before anything is created)
    path_mounts = executor_path_mounts(task)
    reject_operator_mount_conflicts(path_mounts, config)
    reject_relative_stream_paths(task)

    reject_oversized_disk(task, config)
    reject_oversized_cpu_ram(task, config)
    reject_unsupported_backend_parameters(task, config)


def reject_refused_url(where: str, url: str | None) -> None:
    """Reject a URL of a scheme this deployment turned off, saying why.

    FTP turned off, DRS turned off, a DRS host not allowed, or a DRS URI
    that isn't hostname-based (`filer_strategy_factory.refusal`).
    """
    if reason := _filer.refusal(url):
        raise ValueError(f"{where} {reason}")


def reject_unstageable_directory(where: str, url: str | None) -> None:
    """Reject a DIRECTORY input TIF can't stage: inline content, HTTP(S) or DRS.

    HTTP has no standard directory listing, content is one file, and so is
    a DRS object (bundles aren't supported).
    """
    if url is None:
        raise ValueError(f"{where} has inline content, which can't be a DIRECTORY")
    if _filer.scheme(url) == "drs":
        raise ValueError(
            f"{where} is a DIRECTORY with a drs:// url; a DRS object is staged "
            "as a FILE (bundles aren't supported)"
        )
    if _filer.scheme(url) in {"http", "https"}:
        raise ValueError(
            f"{where} is a DIRECTORY with an HTTP(S) url; directories can't be "
            "downloaded over HTTP(S), list each file as a FILE input"
        )


#: For submit errors, by URL scheme: the article for the scheme, the
#: provider's name, and what to ask the administrator to configure.
_PROVIDERS = {
    "s3": ("an", "S3", "S3 storage"),
    "gs": ("a", "Google Cloud Storage", "Google Cloud Storage"),
    "az": ("an", "Azure Blob Storage", "Azure Blob Storage"),
}


def reject_unconfigured_storage(
    where: str, url: str | None, config: RuntimeConfig
) -> None:
    """Reject an object-store URL whose provider the operator didn't enable."""
    scheme = _filer.scheme(url)
    if scheme in _PROVIDERS and not config.storage_enabled(scheme):
        article, provider, storage = _PROVIDERS[scheme]
        raise ValueError(
            f"{where} is {article} {scheme}:// URL, but this deployment has no "
            f"{provider} credentials; ask your administrator to configure "
            f"{storage}"
        )


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


def reject_oversized_cpu_ram(task: TesTask, config: RuntimeConfig) -> None:
    """Reject ``cpu_cores`` or ``ram_gb`` above the operator's maximum."""
    resources = task.resources
    if resources is None:
        return
    scheduling = config.scheduling
    cpu, ram = resources.cpu_cores, resources.ram_gb
    if (
        cpu is not None
        and scheduling.max_cpu_cores is not None
        and cpu > scheduling.max_cpu_cores
    ):
        raise ValueError(
            f"resources.cpu_cores={cpu} exceeds the operator-configured maximum "
            f"of {scheduling.max_cpu_cores}. Ask your administrator to raise "
            "taskpods.resources.maxCpuCores or reduce the request."
        )
    if (
        ram is not None
        and scheduling.max_ram_gb is not None
        and ram > scheduling.max_ram_gb
    ):
        raise ValueError(
            f"resources.ram_gb={ram} exceeds the operator-configured maximum "
            f"of {scheduling.max_ram_gb:g} GB. Ask your administrator to raise "
            "taskpods.resources.maxRamGb or reduce the request."
        )


def reject_unsupported_backend_parameters(task: TesTask, config: RuntimeConfig) -> None:
    """Reject ``backend_parameters`` this deployment can't honour.

    A ``gpu_count`` above the operator's maximum is always rejected, as
    ``cpu_cores`` above its maximum is. Under ``backend_parameters_strict``
    (TES: fail the task if any key or value is unsupported) also keys the
    operator doesn't allow, and values it can't honour: a ``gpu_count``
    that isn't a whole number, a ``priority_class`` or ``node_pool`` the
    operator doesn't list. Without it they are ignored. Keys are matched
    without case, as TES says.
    """
    resources = task.resources
    if resources is None or not resources.backend_parameters:
        return
    scheduling = config.scheduling
    params = backend_parameters(task, config)
    gpus = gpu_count(params)
    if (
        gpus is not None
        and scheduling.max_gpu_count is not None
        and gpus > scheduling.max_gpu_count
    ):
        raise ValueError(
            f"resources.backend_parameters.gpu_count={gpus} exceeds the "
            f"operator-configured maximum of {scheduling.max_gpu_count}. Ask "
            "your administrator to raise taskpods.gpu.maxCount or reduce the "
            "request."
        )
    if not resources.backend_parameters_strict:
        return
    unknown = sorted(
        k
        for k in resources.backend_parameters
        if k.lower() not in scheduling.backend_parameters
    )
    if unknown:
        msg = (
            f"resources.backend_parameters contains unsupported keys "
            f"under backend_parameters_strict=true: {unknown}"
        )
        raise ValueError(msg)
    honoured = {
        "gpu_count": gpus is not None,
        "priority_class": priority_class(params, scheduling) is not None,
        "node_pool": node_pool(params, scheduling) is not None,
    }
    invalid = sorted(k for k in params if not honoured[k])
    if invalid:
        values = ", ".join(f"{k}={params[k]!r}" for k in invalid)
        msg = (
            "resources.backend_parameters contains unsupported values "
            f"under backend_parameters_strict=true: {values}"
        )
        raise ValueError(msg)


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
