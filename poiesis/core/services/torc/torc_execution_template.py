"""Torc's template for each service."""

from abc import ABC, abstractmethod


class TorcExecutionTemplate(ABC):
    """TorcTemplate is a template class for the Torc service."""

    def execute(self) -> None:
        """Defines the template method, for each service namely Texam, Tif, Tof."""
        self.start_job()
        self.wait()
        self.log()

    @abstractmethod
    def start_job(self) -> None:
        """Create the K8s job.

        It could be a Tif, Tof or Texam job.
        """
        pass

    def wait(self) -> None:
        """Wait for the job to finish.

        Uses message broker with task name as channel name
        and waits on that channel for the message.
        """
        # TODO: Implement the wait logic.
        print("Waiting for the job to finish.")

    def log(self) -> None:
        """Log the job status in TaskDB."""
        # TODO: Implement the logging logic.
        print("Logging the job status in TaskDB.")
