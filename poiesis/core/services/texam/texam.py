"""TExAM (Task Executor and Monitor) service."""

import asyncio
import logging
import os
import shlex
import time

from kubernetes import watch  # type: ignore
from kubernetes.client import (
    V1Container,
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
    get_executor_security_volume,
    get_executor_security_volume_mount,
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
                    stdout=None,
                    stderr=f"Executor {idx} failed to start because previous executor failed.",
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
                        stdout=None,
                        stderr=f"Executor {remaining_idx} failed to start because executor {idx} failed.",
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
        command_str = " ".join(shlex.quote(arg) for arg in executor.command)
        # Handle stdin redirection from a file
        if executor.stdin:
            command_str = f"{command_str} < {shlex.quote(executor.stdin)}"

        # Handle stdout and stderr redirection
        if executor.stdout and executor.stderr:
            command_str += (
                f" > {shlex.quote(executor.stdout)} 2> {shlex.quote(executor.stderr)}"
            )
        elif executor.stdout:
            command_str += f" > {shlex.quote(executor.stdout)}"
        elif executor.stderr:
            command_str += f" 2> {shlex.quote(executor.stderr)}"

        # Ignore errors if required
        if executor.ignore_error:
            command_str += " || true"

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

        async def create_job_with_backoff(job_manifest, executor_name) -> bool:
            backoff_time = 1
            while backoff_time <= core_constants.Texam.BACKOFF_LIMIT:
                try:
                    if self.task_id is None:
                        raise ValueError("Task ID is None")
                    await self.db.add_task_executor_log(self.task_id)
                    logger.debug(f"Creating job for {executor_name}: {job_manifest}")
                    await self.kubernetes_client.create_job(job_manifest)
                    return True
                except Exception as e:
                    # Clean up the previous job if it exists
                    logger.error(f"Failed to create job {executor_name}: {e}")
                    logger.info(f"Deleting job {executor_name}")
                    await self.kubernetes_client.delete_job(executor_name)
                    logger.info(f"Retrying in {backoff_time} seconds")
                    await asyncio.sleep(backoff_time)
                    backoff_time = min(
                        backoff_time * 2, core_constants.Texam.BACKOFF_LIMIT
                    )
            # After all retries failed, log the failure
            await self.db.update_executor_log(
                executor_name,
                PodPhase.FAILED.value,
                stdout=None,
                stderr="Failed to create executor job after multiple retries.",
            )
            logger.error(
                f"Job {executor_name} failed to be created after all retries"
            )
            return False

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

        # Note: Here we create mount paths for each input, since the PVC
        #   all the data in downloaded in PVC at
        #   `/transfer/{split_path_for_mounting(input.path)[1]}` directory.
        #   So we need to mount the PVC at
        #   `/transfer/{split_path_for_mounting(input.path)[0]}` directory.
        #   This way the executor can access the data from PVC at the correct
        #   location, that will be `{split_path_for_mounting(input.path)[1]}/
        #   {split_path_for_mounting(input.path)[2]}` directory.
        _volume_pvc_mount = []
        for input in self.task.inputs or []:
            _mount_path = split_path_for_mounting(input.path)[0].rstrip("/")
            _volume_mount = V1VolumeMount(
                name=core_constants.K8s.COMMON_PVC_VOLUME_NAME,
                mount_path=_mount_path,
            )
            # Check if the volume mount is already in the list else
            #   K8s won't process and throw 422 error.
            if input.path and _volume_mount not in _volume_pvc_mount:
                _volume_pvc_mount.append(_volume_mount)

        job_manifest = V1Job(
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
                ttl_seconds_after_finished=int(core_constants.K8s.JOB_TTL)
                if core_constants.K8s.JOB_TTL
                else None,
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
                        containers=[
                            V1Container(
                                name=executor_name,
                                image=executor.image,
                                command=["/bin/sh", "-c"],
                                args=[self._build_command_string(executor)],
                                working_dir=executor.workdir,
                                env=[
                                    V1EnvVar(name=key, value=value)
                                    for key, value in executor.env.items()
                                ]
                                if executor.env is not None
                                else [],
                                resources=V1ResourceRequirements(
                                    limits=resource,
                                    requests=resource,
                                ),
                                volume_mounts=[
                                    V1VolumeMount(
                                        name=core_constants.K8s.COMMON_PVC_VOLUME_NAME,
                                        mount_path=volume,
                                    )
                                    for volume in self.task.volumes or []
                                ]
                                + _volume_pvc_mount
                                + get_executor_security_volume_mount(),
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
                        + get_executor_security_volume(),
                        restart_policy=core_constants.K8s.RESTART_POLICY,
                    ),
                ),
            ),
        )
        return await create_job_with_backoff(job_manifest, executor_name)

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

                event_type = event["type"]
                job = event["object"]

                if job.metadata.name != executor_name:
                    continue

                logger.debug(f"Job event: {event_type}, Job: {executor_name}")

                # Check job status
                if job.status and job.status.conditions:
                    for condition in job.status.conditions:
                        if condition.type == "Complete" and condition.status == "True":
                            # Job completed successfully
                            logs_stdout = await self._get_job_logs(executor_name)
                            await self.db.update_executor_log(
                                executor_name,
                                PodPhase.SUCCEEDED.value,
                                logs_stdout,
                                None,
                            )
                            logger.info(f"Job {executor_name} completed successfully")
                            w.stop()
                            return True
                        elif condition.type == "Failed" and condition.status == "True":
                            # Job failed
                            logs_stdout = await self._get_job_logs(executor_name)
                            await self.db.update_executor_log(
                                executor_name,
                                PodPhase.FAILED.value,
                                logs_stdout,
                                f"Job failed: {condition.message}",
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
                stdout=None,
                stderr=f"Job monitoring timed out after {timeout} seconds.",
            )
            w.stop()
            return False

        except Exception as e:
            logger.exception(f"Error monitoring job {executor_name}: {e}")
            await self.db.update_executor_log(
                executor_name,
                PodPhase.FAILED.value,
                stdout=None,
                stderr=f"Error monitoring job: {str(e)}",
            )
            return False

    async def _get_job_logs(self, job_name: str) -> str | None:
        """Get logs from the job's pod.

        Args:
            job_name: Name of the job.

        Returns:
            Job logs or None if not available.
        """
        try:
            # Get pods for this job
            pods = self.kubernetes_client.core_api.list_namespaced_pod(
                namespace=self.kubernetes_client.namespace,
                label_selector=f"job-name={job_name}",
            )

            if pods.items:
                # Get logs from the first pod
                pod = pods.items[0]
                if pod.metadata and pod.metadata.name:
                    pod_name = pod.metadata.name
                    return await self.kubernetes_client.get_pod_log(pod_name)
        except Exception as e:
            logger.warning(f"Could not get logs for job {job_name}: {e}")

        return None

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
