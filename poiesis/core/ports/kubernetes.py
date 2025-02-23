"""Container orchestrator port."""

from abc import ABC, abstractmethod

from kubernetes.client import V1Job, V1PersistentVolumeClaim, V1Pod


class KubernetesPort(ABC):
    """Container orchestrator port."""

    @abstractmethod
    async def create_job(self, job: V1Job) -> str:
        """Create a Kubernetes Job.

        Args:
            job: The Kubernetes Job object.
        """
        pass

    @abstractmethod
    async def get_job(self, name: str) -> V1Job:
        """Get a Kubernetes Job.

        Args:
            name: The name of the Job.
        """
        pass

    @abstractmethod
    async def create_pvc(self, pvc: V1PersistentVolumeClaim) -> str:
        """Create a Persistent Volume Claim.

        Args:
            pvc: The Persistent Volume Claim object.
        """
        pass

    @abstractmethod
    async def delete_pvc(self, name: str) -> None:
        """Delete a Persistent Volume Claim.

        Args:
            name: The name of the Persistent Volume Claim.
        """
        pass

    @abstractmethod
    async def create_pod(self, pod: V1Pod) -> str:
        """Create a task execution pod.

        Args:
            pod: The pod object.
        """
        pass

    @abstractmethod
    async def get_pod(self, name: str) -> V1Pod:
        """Get a specific pod.

        Args:
            name: The name of the pod.
        """
        pass

    @abstractmethod
    async def get_pods(self, label_selector: str) -> list[V1Pod]:
        """Get all pods matching the label selector.

        Args:
            label_selector: The label selector.
        """
        pass

    @abstractmethod
    async def get_pod_log(self, name: str) -> str:
        """Get log of a pod.

        Args:
            name: The name of the pod.
        """
        pass
