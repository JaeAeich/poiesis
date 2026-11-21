"""Executor containers: the task's own images, one init container each."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kubernetes.client import V1Container, V1EnvVar

from poiesis.core import executor_shell, ignore_error
from poiesis.core.taskpod.pod import executor_resources
from poiesis.core.taskpod.volumes import executor_mounts

if TYPE_CHECKING:
    from kubernetes.client import V1VolumeMount

    from poiesis.api.tes.models import TesExecutor, TesTask
    from poiesis.core.taskpod.config import RuntimeConfig


def build_executor(
    executor: TesExecutor,
    index: int,
    config: RuntimeConfig,
    path_mounts: list[V1VolumeMount],
    task: TesTask,
) -> V1Container:
    """One executor init container.

    Image, command, workdir and env come from the TesExecutor. The command
    runs as submitted, with no shell, unless the executor sets
    ``ignore_error``, ``stdin``, ``stdout`` or ``stderr``: then it runs
    under ``/bin/sh``, which opens the ``stdin``/``stdout``/``stderr``
    files and, with ``ignore_error``, records the exit code in the
    termination message and exits 0 (see ``executor_shell``). The
    container's own stdin stays closed (``stdin: false``). Requests and
    limits come from `pod.executor_resources`.
    """
    env = [V1EnvVar(name=k, value=v) for k, v in (executor.env or {}).items()]
    container = V1Container(
        name=f"exec-{index}",
        image=executor.image,
        image_pull_policy=config.image_pull_policy,
        command=executor_shell.wrap(executor) or list(executor.command),
        working_dir=executor.workdir,
        env=env or None,
        volume_mounts=executor_mounts(config, path_mounts),
        stdin=False,
        resources=executor_resources(executor, task, config),
    )
    if executor.ignore_error:
        container.termination_message_path = ignore_error.TERMINATION_MESSAGE_PATH
        container.termination_message_policy = "File"
    return container
