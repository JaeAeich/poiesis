"""Torc's template for each service."""

from abc import ABC, abstractmethod
from typing import Optional

from poiesis.core.adaptors.kubernetes.kubernetes import KubernetesAdapter
from poiesis.core.adaptors.message_broker.redis_adaptor import RedisMessageBroker
from poiesis.core.ports.message_broker import Message


class TorcExecutionTemplate(ABC):
    """TorcTemplate is a template class for the Torc service.

    Attributes:
        kubernetes_client: Kubernetes client.
        message_broker: Message broker.
        message: Message for the message broker, which would be sent to TOrc.
    """

    def __init__(self) -> None:
        """TorcTemplate initialization.

        Attributes:
            kubernetes_client: Kubernetes client.
            message_broker: Message broker.
            message: Message for the message broker, which would be sent to TOrc.
        """
        self.kubernetes_client = KubernetesAdapter()
        self.message_broker = RedisMessageBroker()
        self.message: Optional[Message] = None

    async def execute(self) -> None:
        """Defines the template method, for each service namely Texam, Tif, Tof."""
        await self.start_job()
        self.wait()
        self.log()

    @abstractmethod
    async def start_job(self) -> None:
        """Create the K8s job.

        It could be a Tif, Tof or Texam job.
        """
        pass

    def wait(self) -> None:
        """Wait for the job to finish.

        Uses message broker with task name as channel name
        and waits on that channel for the message.
        """
        if not hasattr(self, "name"):
            raise AttributeError("The name attribute is not set.")
        message = None
        for message in self.message_broker.subscribe(self.name):
            if message:
                self.message = message
                break

    def log(self) -> None:
        """Log the job status in TaskDB."""
        # TODO: Implement the logging logic.
        print("Logging the job status in TaskDB.")
