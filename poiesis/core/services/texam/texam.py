"""TExAM (Task Executor and Monitor) service."""

import asyncio
import logging
import os
import shlex
from datetime import datetime

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
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.ports.message_broker import Message
from poiesis.core.services.models import PodPhase
from poiesis.core.services.utils import split_path_for_mounting
from poiesis.repository.mongo import MongoDBClient

core_constants = get_poiesis_core_constants()

logger = logging.getLogger(__name__)


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
        """
        self.task = task
        self.task_id = task.id
        self.task_pool: list[tuple[str, datetime]] = []
        self.kubernetes_client = KubernetesAdapter()
        self.message_broker = RedisMessageBroker()
        self.db = MongoDBClient()

    async def execute(self) -> None:
        """Complete TExAM job."""
        await self.start_executors()
        await self.monitor_executors()
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
                        pod_name = await self.kubernetes_client.create_pod(pod_manifest)
                        await self.db.add_task_executor_log(self.task_id)
                        self.task_pool.append((pod_name, datetime.now()))
                        break
                    except Exception as e:
                        # TODO: clean the previous pod else we will get a conflict with
                        #   the same pod name
                        logger.error(f"Failed to create pod {executor_name}: {e}")
                        await asyncio.sleep(backoff_time)
                        backoff_time = min(
                            backoff_time * 2, core_constants.Texam.BACKOFF_LIMIT
                        )
                else:
                    logger.error(f"Failed to create pod {executor_name}")
                    # TODO: Log the failed executor in TaskDB

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
                    service_account_name="pod-creator",
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
                    restart_policy="Never",
                ),
            )
            await create_pod_with_backoff(pod_manifest, executor_name)

    async def monitor_executors(self) -> None:
        """Monitor the executors and log details in TaskDB.

        Create a watch on the pods in the task pool, if the pod is in
        Succeeded or Failed state, log the details in TaskDB and remove
        the pod from the task pool.
        """
        if not self.task_pool:
            return

        pod_names = {pod_name for pod_name, _ in self.task_pool}

        # Use asyncio to run the watch in a separate thread
        await self._watch_pods(pod_names)

    async def _watch_pods(self, pod_names) -> None:
        """Watch pods and process status changes.

        Args:
            pod_names: Set of pod names to monitor
        """
        try:
            w = watch.Watch()

            # Create a label selector for our task executor pods
            label_selector = f"service={core_constants.K8s.TE_PREFIX},parent={core_constants.K8s.TEXAM_PREFIX}-{self.task_id}"  # noqa: E501

            # Run the watch in a separate thread to avoid blocking the event loop
            stream_func = self.kubernetes_client.core_api.list_namespaced_pod
            stream_args = {
                "namespace": self.kubernetes_client.namespace,
                "label_selector": label_selector,
                "timeout_seconds": os.getenv(
                    "MONITOR_TIMEOUT_SECONDS",
                    core_constants.Texam.MONITOR_TIMEOUT_SECONDS,
                ),
            }

            for event in await asyncio.to_thread(w.stream, stream_func, **stream_args):
                pod = event["object"]
                pod_name = pod.metadata.name
                pod_phase = pod.status.phase if pod.status else None

                if pod_name not in pod_names:
                    continue
                # TODO: Handle unknown phase
                if pod_phase in [PodPhase.SUCCEEDED.value, PodPhase.FAILED.value]:
                    pod_entry = next(
                        ((p, t) for p, t in self.task_pool if p == pod_name), None
                    )

                    if pod_entry:
                        logs = await self.kubernetes_client.get_pod_log(pod_name)

                        await self.db.update_executor_log(pod_name, pod_phase, logs)
                        self.task_pool.remove(pod_entry)
                        logger.info(
                            f"Pod {pod_name} completed with status: {pod_phase}"
                        )

                        if not self.task_pool:
                            w.stop()
                            break
        except Exception as e:
            logger.error(f"Error in watch stream: {e}")
            raise e

    async def message(self) -> None:
        """Send message to TORC."""
        assert self.task_id is not None
        self.message_broker.publish(
            self.task_id, Message(f"Texam job for {self.task_id} has been completed.")
        )
