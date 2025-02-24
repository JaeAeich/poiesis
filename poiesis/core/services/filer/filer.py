"""Interface for TIF and TOF."""

from abc import ABC, abstractmethod

from poiesis.core.adaptors.message_broker.redis_adaptor import RedisMessageBroker
from poiesis.core.ports.message_broker import Message


class Filer(ABC):
    """Interface for TIF and TOF.

    Attributes:
        message_broker: Message broker
    """

    def __init__(self) -> None:
        """Initialize the filer.

        Attributes:
            message_broker: Message broker
        """
        self.message_broker = RedisMessageBroker()

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
        if not hasattr(self, "name"):
            raise AttributeError("The name attribute is not set.")
        self.message_broker.publish(self.name, message)
