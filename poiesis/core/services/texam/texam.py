"""TExAM (Task Executor and Monitor) service."""

import asyncio
import contextlib
import logging
import os
import shlex
import time

from kubernetes import watch  # type: ignore
from kubernetes.client import (
    V1Container,
    V1EnvVar,
    V1ObjectMeta,
    V1PersistentVolumeClaimVolumeSource,
    V1Pod,
    V1PodSpec,
    V1ResourceRequirements,
    V1Volume,
    V1VolumeMount,
)

from poiesis.api.tes.models import TesExecutor, TesTask
from poiesis.core.adaptors.kubernetes.kubernetes import KubernetesAdapter
from poiesis.core.adaptors.message_broker.redis_adaptor import RedisMessageBroker
from poiesis.core.constants import (
    get_default_container_security_context,
    get_default_pod_security_context,
    get_poiesis_core_constants,
)
from poiesis.core.ports.message_broker import Message, MessageStatus
from poiesis.core.services.models import PodPhase
from poiesis.core.services.utils import split_path_for_mounting
from poiesis.repository.mongo import MongoDBClient

core_constants = get_poiesis_core_constants()

logger = logging.getLogger(__name__)


# Note: In future, add any other reasons consider fatal startup errors
CRITICAL_WAITING_REASONS = {
    "ImagePullBackOff",
    "ErrImagePull",
    "CrashLoopBackOff",
    "InvalidImageName",
    "ImageInspectError",
}


class Texam:
    """TExAM service.

    Args:
        name: Name of the task.
        executors: List of executors.
        resources: Resources for the executors.
        volumes: List of volumes to be mounted to the executors.

    Attributes:
        name: Name of the task.
        executors: List of executors.
        resources: Resources for the executors.
        volumes: List of volumes to be mounted to the executors.
        task_pool: List of executors.
        kubernetes_client: Kubernetes client.
        message_broker: Message broker.
        failed: Flag defining if TE failed.
    """

    def __init__(
        self,
        task: TesTask,
    ) -> None:
        """TExAM service.

        Args:
            task: TesTask object.

        Attributes:
            task: TesTask object.
            name: Name of the task.
            executors: List of executors.
            resources: Resources for the executors.
            volumes: List of volumes to be mounted to the executors.
            task_pool: List of executors pod name and then they were created.
            kubernetes_client: Kubernetes client.
            message_broker: Message broker.
            failed: Flag defining if TE failed.
        """
        self.task = task
        self.task_id = task.id
        self.task_pool: list[str] = []
        self.kubernetes_client = KubernetesAdapter()
        self.message_broker = RedisMessageBroker()
        self.failed = False
        self.db = MongoDBClient()
        self.pods_to_cleanup: list[str] = []

    async def execute(self) -> None:
        """Complete TExAM job."""
        await self.start_executors()
        self.pods_to_cleanup = self.task_pool.copy()
        await self.monitor_executors()
        await self.cleanup_pods()
        await self.message()

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

    async def start_executors(self) -> None:
        """Create the K8s job for Texam.

        Try to create all the pods for the executors, if the pod creation
        fails, gracefully retry with exponential backoff till a certain
        threshold, failing executors will be ignored and logged.

        Note:
            Parallelism can be achieved by using threads, but due to kubernetes
            limit on number of request per second and in the interest of scalability
            we are launching executors sequentially.
        """
        for idx, executor in enumerate(self.task.executors):
            executor_name = f"{core_constants.K8s.TE_PREFIX}-{self.task_id}-{idx}"

            async def create_pod_with_backoff(pod_manifest, executor_name):
                backoff_time = 1
                while backoff_time <= core_constants.Texam.BACKOFF_LIMIT:
                    try:
                        await self.db.add_task_executor_log(self.task_id)
                        logger.debug(pod_manifest)
                        pod_name = await self.kubernetes_client.create_pod(pod_manifest)
                        self.task_pool.append(pod_name)
                        break
                    except Exception as e:
                        # Cleans the previous pod if it exists, this is to avoid
                        #   the conflict with the same pod name, so we can try again
                        #   with the same pod name. Trying to keep the idx same so logs
                        #   can be associated with the same executor.
                        logger.error(f"Failed to create pod {executor_name}: {e}")
                        logger.info(f"Deleting pod {executor_name}")
                        await self.kubernetes_client.delete_pod(executor_name)
                        logger.info(f"Retrying in {backoff_time} seconds")
                        await asyncio.sleep(backoff_time)
                        backoff_time = min(
                            backoff_time * 2, core_constants.Texam.BACKOFF_LIMIT
                        )
                else:
                    # After all retries failed, add the executor to task_pool with a
                    # special status This ensures it will be monitored and properly
                    # logged
                    self.task_pool.append(executor_name)
                    await self.db.update_executor_log(
                        executor_name,
                        PodPhase.FAILED.value,
                        stdout=None,
                        stderr="Failed to create executor pod after multiple retries.",
                    )
                    logger.error(
                        f"Pod {executor_name} failed to be created after all retries"
                    )

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
                {k: v for k, v in _resource.items() if v is not None}
                if _resource
                else {}
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

            pod_manifest = V1Pod(
                api_version="v1",
                kind="Pod",
                metadata=V1ObjectMeta(
                    name=executor_name,
                    labels={
                        "service": core_constants.K8s.TE_PREFIX,
                        "parent": _parent,
                        "name": executor_name,
                    },
                ),
                spec=V1PodSpec(
                    security_context=get_default_pod_security_context(),
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
                            + _volume_pvc_mount,
                            image_pull_policy=core_constants.K8s.IMAGE_PULL_POLICY,
                            security_context=get_default_container_security_context(),
                        )
                    ],
                    volumes=[
                        V1Volume(
                            name=core_constants.K8s.COMMON_PVC_VOLUME_NAME,
                            persistent_volume_claim=V1PersistentVolumeClaimVolumeSource(
                                claim_name=f"{core_constants.K8s.PVC_PREFIX}-{self.task_id}"
                            ),
                        )
                    ],
                    restart_policy=core_constants.K8s.RESTART_POLICY,
                ),
            )
            await create_pod_with_backoff(pod_manifest, executor_name)

    async def monitor_executors(self) -> None:
        """Monitor the executors and log details in TaskDB."""
        if not self.task_pool:
            return

        pod_names_to_monitor = set(self.task_pool)
        active_pod_names = set(pod_names_to_monitor)

        if not active_pod_names:
            logger.info("No pods provided to monitor.")
            return

        label_selector = f"service={core_constants.K8s.TE_PREFIX},parent={core_constants.K8s.TEXAM_PREFIX}-{self.task_id}"  # noqa: E501
        timeout = int(
            os.getenv(
                "MONITOR_TIMEOUT_SECONDS", core_constants.Texam.MONITOR_TIMEOUT_SECONDS
            )
        )
        stream_args = {
            "namespace": self.kubernetes_client.namespace,
            "label_selector": label_selector,
            "timeout_seconds": timeout,
        }

        try:
            w = watch.Watch()
            start_time = time.time()
            logger.info(
                f"Starting watch for pods with label selector: {label_selector}"
            )

            stream_func = self.kubernetes_client.core_api.list_namespaced_pod
            for event in await asyncio.to_thread(w.stream, stream_func, **stream_args):
                event_type = event["type"]
                pod = event["object"]
                pod_name = str(pod.metadata.name)

                if pod_name not in active_pod_names:
                    continue

                logger.debug(
                    f"Event: {event_type}, Pod: {pod_name}, Phase: {pod.status.phase}"
                )
                await self._process_pod_event(pod, active_pod_names)

                if not active_pod_names:
                    w.stop()
                    logger.info(
                        "All monitored pods processed in "
                        f"{time.time() - start_time:.2f} seconds"
                    )
                    break

            await self._handle_unresolved_pods(active_pod_names, timeout, start_time)

        except asyncio.CancelledError:
            logger.info(
                f"Pod watch task cancelled in {time.time() - start_time:.2f} seconds"
            )
        except Exception as e:
            logger.exception(f"Error in watch stream: {e}")
            raise

    async def _process_pod_event(self, pod: V1Pod, active_pod_names: set) -> None:
        """Processes a single pod event."""
        # Poiesis adds these fields, so we can safely assert them
        assert pod.metadata is not None
        assert pod.status is not None

        pod_name = str(pod.metadata.name)
        pod_phase = pod.status.phase if pod.status else None

        if failure_reason := self._check_container_failure(pod):
            await self._handle_pod_failure(pod_name, failure_reason)
            self._remove_pod_from_pool(pod_name, active_pod_names)
            return

        if pod_phase in (PodPhase.SUCCEEDED.value, PodPhase.FAILED.value):
            logs_stdout, logs_stderr = await self._get_pod_logs(pod_name, pod_phase)
            await self.db.update_executor_log(
                pod_name,
                pod_phase,
                logs_stdout,
                logs_stderr if pod_phase == PodPhase.FAILED.value else None,
            )
            logger.info(
                f"Pod {pod_name} completed with status: {pod_phase}. Logs captured "
                "(if available)."
            )
            self._remove_pod_from_pool(pod_name, active_pod_names)

        elif pod_phase == PodPhase.UNKNOWN.value:
            logger.warning(f"Pod {pod_name} is in an Unknown state.")

    def _check_container_failure(self, pod: V1Pod) -> str | None:
        """Checks for container failures and returns the reason if found.

        Executor pod might be in pending state, if the pod is in pending state, it
        means that the pod might fail to start, that is why we need to check for
        container failures.
        """
        pod_phase = pod.status.phase if pod.status else None

        # If container is failing to start, it will be in the init_container_statuses
        # or container_statuses list
        if pod.status is None:
            return None

        all_container_statuses = (pod.status.init_container_statuses or []) + (
            pod.status.container_statuses or []
        )

        assert pod.metadata is not None

        if pod_phase == PodPhase.PENDING.value or (
            pod.status and all_container_statuses
        ):
            for status in all_container_statuses:
                if status.state and status.state.waiting:
                    logger.info(
                        f"Pending pod {pod.metadata.name} has container {status.name} "
                        f"in waiting state with reason: {status.state.waiting.reason}"
                    )
                    if status.state.waiting.reason in CRITICAL_WAITING_REASONS:
                        return status.state.waiting.reason
        return None

    async def _handle_pod_failure(self, pod_name: str, failure_reason: str) -> None:
        """Handles pod failure and updates the database."""
        error_log_message = f"Pod failed due to container error: {failure_reason}"
        try:
            await self.db.update_executor_log(
                pod_name, PodPhase.FAILED.value, stdout=None, stderr=error_log_message
            )
            logger.info(
                f"Pod {pod_name} marked as Failed in DB due to container error: "
                f"{failure_reason}"
            )
        except Exception as e:
            logger.error(f"Failed to update DB for failed pod {pod_name}: {e}")

    async def _get_pod_logs(
        self, pod_name: str, pod_phase: str
    ) -> tuple[str | None, str]:
        """Retrieves pod logs, handling potential errors.

        Logs are retrieved from the pod, if the pod is in failed state, we retrieve
        the logs from the pod, if the pod is in succeeded state, we don't retrieve
        the logs from the pod. This help in case the pod is in pending state or couldn't
        start due to some reason.
        """
        logs_stdout = None
        logs_stderr = f"Pod phase reported as {pod_phase} by Kubernetes."
        try:
            logs_stdout = await self.kubernetes_client.get_pod_log(pod_name)
        except Exception as e:
            logger.warning(
                f"Could not get logs for pod {pod_name} in phase {pod_phase}: {e}"
            )
            logs_stderr += f" Log retrieval failed: {str(e)}"
        return logs_stdout, logs_stderr

    def _remove_pod_from_pool(self, pod_name: str, active_pod_names: set) -> None:
        """Removes a pod from the active pool and task pool."""
        active_pod_names.discard(pod_name)
        if pod_entry := next((p for p in self.task_pool if p == pod_name), None):
            with contextlib.suppress(ValueError):
                self.task_pool.remove(pod_entry)

    async def _handle_unresolved_pods(
        self, active_pod_names: set, timeout: int, start_time: float
    ) -> None:
        """Handles unresolved pods after the watch ends."""
        if active_pod_names:
            logger.warning(
                f"Watch ended with {len(active_pod_names)} unresolved pods: "
                f"{active_pod_names}, Time taken: {time.time() - start_time:.2f} "
                "seconds"
            )
            for pod_name in active_pod_names.copy():
                logger.error(
                    f"Pod {pod_name} did not reach a terminal state before watch "
                    "timeout."
                )
                try:
                    await self.kubernetes_client.delete_pod(pod_name)
                    await self.db.update_executor_log(
                        pod_name,
                        PodPhase.FAILED.value,
                        stdout=None,
                        stderr=f"Pod monitoring timed out after {timeout} seconds.",
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to update DB for timed-out pod {pod_name}: {e}"
                    )
                self._remove_pod_from_pool(pod_name, active_pod_names)
                self.failed = True

    async def cleanup_pods(self) -> None:
        """Clean up completed executor pods to free PVC references.

        Deletes pods that allow PVCs to be properly cleaned up.
        """
        if not self.pods_to_cleanup:
            logger.debug("No executor pods to clean up")
            return

        logger.info(f"Starting cleanup of {len(self.pods_to_cleanup)} executor pods")
        cleanup_count = 0

        for pod_name in self.pods_to_cleanup[:]:
            try:
                await self.kubernetes_client.delete_pod(pod_name)
                cleanup_count += 1
            except Exception as e:
                logger.warning(f"Could not cleanup pod {pod_name}: {e}")

        logger.debug(
            "Pod cleanup completed. Cleaned up "
            f"{cleanup_count}/{len(self.task_pool)} pods"
        )

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
