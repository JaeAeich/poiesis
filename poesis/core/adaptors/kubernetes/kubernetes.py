"""Kubernetes adaptor."""

import asyncio
import logging
import os
from http import HTTPStatus

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from poesis.core.ports.kubernetes import KubernetesPort

logger = logging.getLogger(__name__)


class KubernetesAdapter(KubernetesPort):
    """Kubernetes adaptor.

    Attributes:
        core_api: The Kubernetes Core API
        batch_api: The Kubernetes Batch API
        namespace: The Kubernetes namespace
    """

    def __init__(self):
        """Initialize the Kubernetes adaptor.

        Attributes:
            core_api: The Kubernetes Core API
            batch_api: The Kubernetes Batch API
            namespace: The Kubernetes
        """
        config.load_kube_config()

        self.core_api = client.CoreV1Api()
        self.batch_api = client.BatchV1Api()
        self.namespace = os.getenv("K8S_NAMESPACE", "poesis")

    async def create_job(self, job: client.V1Job) -> str:
        """Create a Kubernetes Job.

        Args:
            job: The Kubernetes Job object.
        """
        try:
            api_response = await asyncio.to_thread(
                self.batch_api.create_namespaced_job, namespace=self.namespace, body=job
            )
            assert job.metadata is not None, "Job should have metadata"
            assert job.metadata.name is not None, "Job name is None"
            logger.info(
                f"Created job {job.metadata.name} in namespace {self.namespace}"
            )
            return str(api_response.metadata.name)
        except ApiException as e:
            logger.error(f"Error creating job: {e}")
            raise

    async def get_job(self, name: str) -> client.V1Job:
        """Get a Kubernetes Job.

        Args:
            name: The name of the Job.
        """
        try:
            return await asyncio.to_thread(
                self.batch_api.read_namespaced_job, name=name, namespace=self.namespace
            )
        except ApiException as e:
            logger.error(f"Error getting job: {e}")
            raise

    async def create_pvc(self, pvc: client.V1PersistentVolumeClaim) -> str:
        """Create a Persistent Volume Claim.

        Args:
            pvc: The Persistent Volume Claim object.
        """
        try:
            api_response = await asyncio.to_thread(
                self.core_api.create_namespaced_persistent_volume_claim,
                namespace=self.namespace,
                body=pvc,
            )
            assert pvc.metadata is not None, "PVC should have metadata"
            assert pvc.metadata.name is not None, "PVC name is None"
            logger.info(
                f"Created PVC {pvc.metadata.name} in namespace {self.namespace}"
            )
            return str(api_response.metadata.name)
        except ApiException as e:
            logger.error(f"Error creating PVC: {e}")
            raise

    async def delete_pvc(self, name: str) -> None:
        """Delete a Persistent Volume Claim."""
        try:
            await asyncio.to_thread(
                self.core_api.delete_namespaced_persistent_volume_claim,
                name=name,
                namespace=self.namespace,
            )
            logger.info(f"Deleted PVC {name} from namespace {self.namespace}")
        except ApiException as e:
            if e.status != HTTPStatus.NOT_FOUND:
                logger.error(f"Error deleting PVC: {e}")
                raise

    async def create_pod(self, pod: client.V1Pod) -> str:
        """Create a task execution pod.

        Args:
            pod: The pod object.
        """
        try:
            api_response = await asyncio.to_thread(
                self.core_api.create_namespaced_pod, namespace=self.namespace, body=pod
            )
            assert pod.metadata is not None, "Pod should have metadata"
            assert pod.metadata.name is not None, "Pod name is None"
            logger.info(
                f"Created pod {pod.metadata.name} in namespace {self.namespace}"
            )
            return str(api_response.metadata.name)
        except ApiException as e:
            logger.error(f"Error creating pod: {e}")
            raise

    async def get_pod(self, name: str) -> client.V1Pod:
        """Get a specific pod.

        Args:
            name: The name of the pod.
        """
        try:
            return await asyncio.to_thread(
                self.core_api.read_namespaced_pod, name=name, namespace=self.namespace
            )
        except ApiException as e:
            logger.error(f"Error getting pod: {e}")
            raise

    async def get_pods(self, label_selector: str) -> list[client.V1Pod]:
        """Get all pods matching the label selector.

        Args:
            label_selector: The label selector.
        """
        try:
            api_response = await asyncio.to_thread(
                self.core_api.list_namespaced_pod,
                namespace=self.namespace,
                label_selector=label_selector,
            )
            pods: list[client.V1Pod] = api_response.items
            return pods
        except ApiException as e:
            logger.error(f"Error listing pods: {e}")
            raise

    async def get_pod_log(self, name: str) -> str:
        """Get log of a pod.

        Args:
            name: The name of the pod.
        """
        try:
            return await asyncio.to_thread(
                self.core_api.read_namespaced_pod_log,
                name=name,
                namespace=self.namespace,
            )
        except ApiException as e:
            logger.error(f"Error getting pod logs: {e}")
            raise
