"""Interface for TIF and TOF."""

from abc import ABC, abstractmethod

from poiesis.core.ports.message_broker import Message


class Filer(ABC):
    """Interface for TIF and TOF."""

    def execute(self):
        """Execute the filer.

        This will file the file and send a message to TORC via the message
        broker.
        """
        self.file()
        self.message(Message("TIF completed."))

    @abstractmethod
    def file(self):
        """Filing logic, upload or download.

        If TIF encounters any error, it will send a message to TORC
        and break.
        """
        pass

    def message(self, message: Message):
        """Message logic, send a message to TORC."""
        # TODO: Implement message logic.
        print(f"Message: {message}")
        pass
