"""TExAM (Task Executor and Monitor) service."""

import asyncio
import logging
import os
import shlex

from kubernetes import watch  # type: ignore
from kubernetes.client import (
    V1Container,
    V1EmptyDirVolumeSource,
    V1EnvVar,
    V1Job,
    V1JobSpec,
    V1ObjectMeta,
    V1PersistentVolumeClaimVolumeSource,
    V1PodSpec,
    V1PodTemplateSpec,
    V1ResourceRequirements,
    V1Volume,
    V1VolumeMount,
)

from poiesis.api.tes.models import TesExecutor, TesTask
from poiesis.core.adaptors.kubernetes.kubernetes import KubernetesAdapter
from poiesis.core.adaptors.message_broker.redis_adaptor import RedisMessageBroker
from poiesis.core.constants import (
    get_executor_container_security_context,
    get_executor_pod_security_context,
    get_poiesis_core_constants,
)
from poiesis.core.ports.message_broker import Message, MessageStatus
from poiesis.core.services.models import PodPhase
from poiesis.core.services.utils import split_path_for_mounting
from poiesis.repository.mongo import MongoDBClient

core_constants = get_poiesis_core_constants()

logger = logging.getLogger(__name__)


class Texam:
    """TExAM service.

    Args:
        task: TesTask object.

    Attributes:
        task: TesTask object.
        task_id: Task ID.
        kubernetes_client: Kubernetes client.
        message_broker: Message broker.
        failed: Flag defining if TE failed.
        db: MongoDB client.
    """

    def __init__(
        self,
        task: TesTask,
    ) -> None:
        """TExAM service.

        Args:
            task: TesTask object.
        """
        self.task = task
        self.task_id = task.id
        self.kubernetes_client = KubernetesAdapter()
        self.message_broker = RedisMessageBroker()
        self.failed = False
        self.db = MongoDBClient()

    async def execute(self) -> None:
        """Execute TExAM.

        Creates individual k8s Jobs for each executor sequentially.
        If any executor fails, remaining executors are marked as failed.
        """
        for idx, executor in enumerate(self.task.executors):
            if self.failed:
                # If previous executor failed, mark remaining executors as failed
                executor_name = f"{core_constants.K8s.TE_PREFIX}-{self.task_id}-{idx}"
                if self.task_id is not None:
                    await self.db.add_task_executor_log(self.task_id)
                await self.db.update_executor_log(
                    executor_name,
                    PodPhase.FAILED.value,
                    stdout="",
                    stderr=(
                        f"Executor {idx} failed to start because previous executor"
                        " failed."
                    ),
                )
                continue

            # Create and monitor executor sequentially
            success = await self.run_single_executor(executor, idx)
            if not success:
                self.failed = True
                # Mark remaining executors as failed
                for remaining_idx in range(idx + 1, len(self.task.executors)):
                    remaining_executor_name = (
                        f"{core_constants.K8s.TE_PREFIX}-{self.task_id}-{remaining_idx}"
                    )
                    if self.task_id is not None:
                        await self.db.add_task_executor_log(self.task_id)
                    await self.db.update_executor_log(
                        remaining_executor_name,
                        PodPhase.FAILED.value,
                        stdout="",
                        stderr=(
                            f"Executor {remaining_idx} failed to start because"
                            f" executor {idx} failed."
                        ),
                    )
                break

        await self.message()

    async def run_single_executor(self, executor: TesExecutor, idx: int) -> bool:
        """Run a single executor and monitor it to completion.

        Args:
            executor: Executor object.
            idx: Index of the executor.

        Returns:
            True if executor completed successfully, False otherwise.
        """
        # Create the executor job
        job_created = await self.create_executor_job(executor, idx)
        return await self.monitor_executor_job(executor, idx) if job_created else False

    def _build_command_string(self, executor: TesExecutor) -> str:
        """Constructs a shell command string.

        Get the command from the executor and construct a shell command string
        with proper redirection and error handling.

        Args:
            executor: Executor object.
        """
        # If the command is a single string, split it. Otherwise, use as is.
        # This handles both ["sleep 1h"] and ["sleep", "1h"] cases.
        if len(executor.command) == 1 and " " in executor.command[0]:
            command_parts = shlex.split(executor.command[0])
        else:
            command_parts = executor.command
        command_str = " ".join(shlex.quote(arg) for arg in command_parts)

        # Handle stdin redirection from a file
        if executor.stdin:
            command_str = f"{command_str} < {shlex.quote(executor.stdin)}"

        # Handle stdout and stderr redirection
        if executor.stdout and executor.stderr:
            # Create directories for both stdout and stderr files for safety
            stdout_dir = os.path.dirname(executor.stdout)
            stderr_dir = os.path.dirname(executor.stderr)
            command_str = (
                f"mkdir -p {shlex.quote(stdout_dir)} {shlex.quote(stderr_dir)} && "
                f"{command_str} > {shlex.quote(executor.stdout)} 2> {shlex.quote(executor.stderr)}"
            )
        elif executor.stdout:
            # Create directory for stdout file for safety
            stdout_dir = os.path.dirname(executor.stdout)
            command_str = f"mkdir -p {shlex.quote(stdout_dir)} && {command_str} > {shlex.quote(executor.stdout)}"
        elif executor.stderr:
            # Create directory for stderr file for safety
            stderr_dir = os.path.dirname(executor.stderr)
            command_str = f"mkdir -p {shlex.quote(stderr_dir)} && {command_str} 2> {shlex.quote(executor.stderr)}"

        # Ignore errors if required
        if executor.ignore_error:
            command_str += " || true"

        # Add post-processing to copy outputs back to transfer directory
        post_commands = []
        for _output in self.task.outputs or []:
            transfer_path = os.path.join(
                core_constants.K8s.TOF_PVC_PATH,
                _output.path.lstrip("/"),
            )
            transfer_dir = os.path.dirname(transfer_path)

            post_commands.extend(
                [
                    f"mkdir -p {shlex.quote(transfer_dir)}",
                    f"if [ -f {shlex.quote(_output.path)} ]; then mv {shlex.quote(_output.path)} {shlex.quote(transfer_path)}; fi",
                    f"if [ -d {shlex.quote(_output.path)} ]; then mv {shlex.quote(_output.path)}/* {shlex.quote(transfer_dir)}/; fi",
                ]
            )

        if post_commands:
            post_command_str = " && ".join(post_commands)
            command_str = f"({command_str}) && ({post_command_str})"

        return command_str

    async def create_executor_job(self, executor: TesExecutor, idx: int) -> bool:
        """Create a k8s Job for the executor.

        Args:
            executor: Executor object.
            idx: Index of the executor.

        Returns:
            True if job was created successfully, False otherwise.
        """
        executor_name = f"{core_constants.K8s.TE_PREFIX}-{self.task_id}-{idx}"
        job_manifest = self._create_executor_job_manifest(executor, idx)

        backoff_time = 1
        while backoff_time < core_constants.Texam.BACKOFF_LIMIT:
            logger.debug(
                "Exponential backoff attempt: "
                f"{backoff_time}/{core_constants.Texam.BACKOFF_LIMIT} "
                f"to create job for {executor_name}."
            )
            try:
                if self.task_id is None:
                    raise ValueError("Task ID is None")
                logger.debug(
                    f"Creating job for {executor_name}: {job_manifest.to_dict()}"
                )
                await self.kubernetes_client.create_job(job_manifest)
                await self.db.add_task_executor_log(self.task_id)
                return True
            except Exception as e:
                logger.error(f"Failed to create job {executor_name}: {e}")
                logger.info(f"Deleting job {executor_name}")
                await self.kubernetes_client.delete_job(executor_name)
                # We don't need to delete the executor log from the DB,
                # since it isn't added until after the job is created.
                # If TExAM has launched successfully, the DB is clearly functional.
                logger.info(f"Retrying in {backoff_time} seconds")
                await asyncio.sleep(backoff_time)
                backoff_time = min(backoff_time * 2, core_constants.Texam.BACKOFF_LIMIT)

        # After all retries failed, log the failure and mark run as failed so
        # all executors can be marked as failed.
        await self.db.update_executor_log(
            executor_name,
            PodPhase.FAILED.value,
            stdout="",
            stderr="Failed to create executor job after multiple retries.",
        )
        logger.error(f"Job {executor_name} failed to be created after all retries")
        return False

    def _create_executor_job_manifest(self, executor: TesExecutor, idx: int) -> V1Job:
        """Create a k8s Job for the executor.

        Args:
            executor: Executor object.
            idx: Index of the executor.
        """
        executor_name = f"{core_constants.K8s.TE_PREFIX}-{self.task_id}-{idx}"

        _resource = (
            {
                "cpu": str(self.task.resources.cpu_cores)
                if self.task.resources.cpu_cores
                else None,
                "memory": f"{self.task.resources.ram_gb}Gi"
                if self.task.resources.ram_gb
                else None,
            }
            if self.task.resources
            else {}
        )
        resource = (
            {k: v for k, v in _resource.items() if v is not None} if _resource else {}
        )

        _parent = f"{core_constants.K8s.TEXAM_PREFIX}-{self.task_id}"

        # Create volume mounts for file operations.
        # All the files downloaded by the executors are mounted to /tif.
        # All the files uploaded by the executors are mounted to /tof.
        _tif_volume_mounts = [
            V1VolumeMount(
                name=core_constants.K8s.COMMON_PVC_VOLUME_NAME,
                mount_path=core_constants.K8s.TIF_PVC_PATH,
            )
        ]
        _tof_volume_mounts = [
            V1VolumeMount(
                name=core_constants.K8s.COMMON_PVC_VOLUME_NAME,
                mount_path=core_constants.K8s.TOF_PVC_PATH,
            )
        ]

        # Create empty directories for the inputs.
        # We will use empty dirs to move the files from /tif to
        # the target path.
        _empty_dir_seen = set()
        _empty_dir_volumes: list[tuple[str, V1Volume]] = []
        for _input in self.task.inputs or []:
            path = split_path_for_mounting(_input.path)[0]
            if path not in _empty_dir_seen:
                # Sanitize the path to be a valid k8s volume name
                sanitized_path_name = path.lstrip("/").replace("/", "-")
                volume_name = f"empty-dir-{idx}-{sanitized_path_name}"
                _empty_dir_volumes.append(
                    (
                        path,
                        V1Volume(
                            name=volume_name,
                            empty_dir=V1EmptyDirVolumeSource(),
                        ),
                    )
                )
                _empty_dir_seen.add(path)

        # Create init container commands to set up file structure.
        init_script_lines = [
            "echo 'DEBUG: Contents of /tif:'",
            "find /tif -type f -ls || echo 'No files found in /tif'",
            "echo 'DEBUG: Available mount points:'",
            "df -h | grep -E '(tif|tof)' || echo 'No relevant mounts found'",
            "echo 'DEBUG: Starting file setup...'",
        ]

        # Copy input files from /tif/path to /path (now both are mounted volumes)
        for _input in self.task.inputs or []:
            transfer_path = os.path.join(
                core_constants.K8s.TIF_PVC_PATH,
                _input.path.lstrip("/"),
            )
            target_path = _input.path

            # Add commands for this specific input
            init_script_lines.extend(
                [
                    f"echo 'Processing input: {_input.path}'",
                    f"echo 'Source: {transfer_path}'",
                    f"echo 'Target: {target_path}'",
                    # Check if source file exists and copy
                    f"if [ -f {shlex.quote(transfer_path)} ]; then",
                    f"  echo 'Found source file: {transfer_path}'",
                    f"  cp {shlex.quote(transfer_path)} {shlex.quote(target_path)}",
                    f"  echo 'Copied file to: {target_path}'",
                    f"  ls -la {shlex.quote(target_path)}",
                    "else",
                    f"  echo 'ERROR: Source file not found: {transfer_path}'",
                    f"  ls -la {shlex.quote(os.path.dirname(transfer_path))} || echo 'Directory not found'",
                    "fi",
                    "",  # Empty line for readability
                ]
            )

        # No need to create output directories since they're now mounted volumes
        init_script_lines.extend(
            [
                "",  # Empty line
                "echo 'DEBUG: Final status check:'",
                "echo 'Input files created:'",
            ]
        )

        # Add individual file checks
        init_script_lines.extend(
            f"ls -la {shlex.quote(_input.path)} || echo 'Missing: {_input.path}'"
            for _input in self.task.inputs or []
        )
        init_script_lines.extend(
            [
                "echo 'DEBUG: Output directories:'",
                *[
                    f"ls -la {shlex.quote(os.path.dirname(_output.path))} || echo 'Missing dir: {os.path.dirname(_output.path)}'"
                    for _output in self.task.outputs or []
                ],
                "echo 'Init container setup completed'",
            ]
        )

        # Create init container setup command as a multi-line script
        init_command = (
            "\n".join(init_script_lines)
            if init_script_lines
            else "echo 'No setup needed'"
        )

        return V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=V1ObjectMeta(
                name=executor_name,
                labels={
                    "service": core_constants.K8s.TE_PREFIX,
                    "parent": _parent,
                    "name": executor_name,
                },
            ),
            spec=V1JobSpec(
                # Note: Backoff limit is set to 0 to fail immediately when pod fails.
                #   This is because we want to fail all subsequent executors if any
                #   executor fails.
                backoff_limit=0,
                ttl_seconds_after_finished=(
                    int(core_constants.K8s.JOB_TTL)
                    if core_constants.K8s.JOB_TTL
                    else None
                ),
                template=V1PodTemplateSpec(
                    metadata=V1ObjectMeta(
                        labels={
                            "service": core_constants.K8s.TE_PREFIX,
                            "parent": _parent,
                            "name": executor_name,
                        }
                    ),
                    spec=V1PodSpec(
                        security_context=get_executor_pod_security_context(),
                        init_containers=[
                            V1Container(
                                name="file-setup",
                                image="busybox:latest",
                                command=["/bin/sh", "-c"],
                                args=[init_command],
                                volume_mounts=_tif_volume_mounts
                                + _tof_volume_mounts
                                + [
                                    V1VolumeMount(
                                        name=volume_name.name,
                                        mount_path=path,
                                    )
                                    for path, volume_name in _empty_dir_volumes
                                ],
                                security_context=get_executor_container_security_context(),
                            )
                        ],
                        containers=[
                            V1Container(
                                name=executor_name,
                                image=executor.image,
                                command=["/bin/sh", "-c"],
                                args=[self._build_command_string(executor)],
                                working_dir=executor.workdir,
                                env=(
                                    [
                                        V1EnvVar(name=key, value=value)
                                        for key, value in executor.env.items()
                                    ]
                                    if executor.env is not None
                                    else []
                                ),
                                resources=V1ResourceRequirements(
                                    limits=resource,
                                    requests=resource,
                                ),
                                volume_mounts=_tof_volume_mounts
                                + [
                                    V1VolumeMount(
                                        name=volume_name.name,
                                        mount_path=path,
                                    )
                                    for path, volume_name in _empty_dir_volumes
                                ]
                                + [
                                    V1VolumeMount(
                                        name=core_constants.K8s.COMMON_PVC_VOLUME_NAME,
                                        mount_path=volume,
                                    )
                                    for volume in self.task.volumes or []
                                ],
                                image_pull_policy=core_constants.K8s.IMAGE_PULL_POLICY,
                                security_context=get_executor_container_security_context(),
                            )
                        ],
                        volumes=[
                            V1Volume(
                                name=core_constants.K8s.COMMON_PVC_VOLUME_NAME,
                                persistent_volume_claim=V1PersistentVolumeClaimVolumeSource(
                                    claim_name=f"{core_constants.K8s.PVC_PREFIX}-{self.task_id}"
                                ),
                            ),
                        ]
                        + [volume for _, volume in _empty_dir_volumes],
                        restart_policy=core_constants.K8s.RESTART_POLICY,
                    ),
                ),
            ),
        )

    async def monitor_executor_job(self, executor: TesExecutor, idx: int) -> bool:
        """Monitor the executor job and log details in TaskDB.

        Args:
            executor: Executor object.
            idx: Index of the executor.

        Returns:
            True if executor completed successfully, False otherwise.
        """
        executor_name = f"{core_constants.K8s.TE_PREFIX}-{self.task_id}-{idx}"

        timeout = int(
            os.getenv(
                "MONITOR_TIMEOUT_SECONDS", core_constants.Texam.MONITOR_TIMEOUT_SECONDS
            )
        )

        try:
            w = watch.Watch()
            logger.info(f"Starting watch for job: {executor_name}")

            # Watch for job completion
            for event in w.stream(
                self.kubernetes_client.batch_api.list_namespaced_job,
                namespace=self.kubernetes_client.namespace,
                field_selector=f"metadata.name={executor_name}",
                timeout_seconds=timeout,
            ):
                if not isinstance(event, dict):
                    continue

                job = event["object"]

                if job.metadata.name != executor_name:
                    continue

                # Check job status
                if job.status and job.status.conditions:
                    for condition in job.status.conditions:
                        if condition.type == "Complete" and condition.status == "True":
                            # Job completed successfully
                            logs = await self._get_job_logs(executor_name)
                            await self.db.update_executor_log(
                                executor_name,
                                PodPhase.SUCCEEDED.value,
                                stdout=logs[0],
                                stderr=logs[1],
                            )
                            logger.info(f"Job {executor_name} completed successfully")
                            w.stop()
                            return True
                        elif condition.type == "Failed" and condition.status == "True":
                            # Job failed
                            logs = await self._get_job_logs(executor_name)
                            await self.db.update_executor_log(
                                executor_name,
                                PodPhase.FAILED.value,
                                stdout=logs[0],
                                stderr=logs[1],
                            )
                            logger.error(
                                f"Job {executor_name} failed: {condition.message}"
                            )
                            w.stop()
                            return False

            # If we reach here, the timeout was reached
            logger.error(
                f"Job {executor_name} monitoring timed out after {timeout} seconds"
            )
            await self.db.update_executor_log(
                executor_name,
                PodPhase.FAILED.value,
                stdout="",
                stderr=f"Job monitoring timed out after {timeout} seconds.",
            )
            w.stop()
            return False

        except Exception as e:
            logger.exception(f"Error monitoring job {executor_name}: {e}")
            await self.db.update_executor_log(
                executor_name,
                PodPhase.FAILED.value,
                stdout="",
                stderr=f"Error monitoring job: {str(e)}",
            )
            return False

    async def _get_job_logs(self, job_name: str) -> tuple[str, str]:
        """Get logs from the job's pod.

        Args:
            job_name: Name of the job.

        Returns:
            Tuple of stdout and stderr logs.
        """
        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                # Get pods for this job using the job-name label
                pods = self.kubernetes_client.core_api.list_namespaced_pod(
                    namespace=self.kubernetes_client.namespace,
                    label_selector=f"job-name={job_name}",
                )

                if pods.items:
                    # Get logs from the first pod (jobs typically create one pod)
                    pod = pods.items[0]
                    if pod.metadata and pod.metadata.name:
                        pod_name = pod.metadata.name
                        logger.debug(
                            f"Getting logs from pod {pod_name} of job {job_name}"
                        )

                        # Try to get logs, with retry for pods that aren't ready yet
                        try:
                            return await self.kubernetes_client.get_pod_log(
                                pod_name
                            ), ""
                        except Exception as log_error:
                            logger.warning(
                                f"Failed to get logs from pod {pod_name}: {log_error}"
                            )
                            if attempt < max_retries - 1:
                                logger.info(
                                    f"Retrying log retrieval for pod {pod_name} "
                                    f"(attempt {attempt + 1}/{max_retries})"
                                )
                                await asyncio.sleep(retry_delay)
                                continue
                            else:
                                logger.error(
                                    f"Failed to get logs from pod {pod_name} after "
                                    f"{max_retries} attempts"
                                )
                                return (
                                    "",
                                    f"Failed to get logs for executor {job_name} "
                                    f"after {max_retries} attempts",
                                )
                    else:
                        logger.warning(
                            f"Pod metadata or name is missing for job {job_name}"
                        )
                else:
                    logger.warning(
                        f"No pods found for job {job_name} (attempt "
                        f"{attempt + 1}/{max_retries})"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        continue

            except Exception as e:
                logger.warning(
                    f"Could not get logs for job {job_name} (attempt "
                    f"{attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue

        logger.error(f"Failed to get logs for job {job_name} after all attempts")
        return "", f"Internal error while getting logs for executor {job_name}."

    async def message(self) -> None:
        """Send message to TORC."""
        assert self.task_id is not None
        if not self.failed:
            self.message_broker.publish(
                self.task_id,
                Message(f"TExAM job for {self.task_id} has been completed."),
            )
        else:
            self.message_broker.publish(
                self.task_id,
                Message(
                    message="TExAM job failed to run all jobs successfully.",
                    status=MessageStatus.ERROR,
                ),
            )
