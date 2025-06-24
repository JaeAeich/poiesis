"""Interface for TIF and TOF."""

import logging
import sys
from abc import ABC, abstractmethod

from poiesis.core.adaptors.message_broker.redis_adaptor import RedisMessageBroker
from poiesis.core.ports.message_broker import Message, MessageStatus

logger = logging.getLogger(__name__)


class Filer(ABC):
    """Interface for TIF and TOF.

    Attributes:
        message_broker: Message broker
        name: Name of the filer
    """

    def __init__(self) -> None:
        """Initialize the filer.

        Attributes:
            message_broker: Message broker
            name: Name of the filer
        """
        self.message_broker = RedisMessageBroker()

    async def execute(self):
        """Execute the filer.

        This will file the file and send a message to TORC via the message
        broker.
        """
        try:
            logger.info("Starting file operation")
            await self.file()
        except Exception as e:
            logger.error(f"File operation failed: {e}")
            self.message(
                Message(status=MessageStatus.ERROR, message=f"Filer failed: {e}")
            )
            sys.exit(1)  # TODO: We should update the task status, tell torc
        logger.info("File operation completed successfully")
        self.message(Message("Filer completed."))

    @abstractmethod
    async def file(self):
        """Filing logic, upload or download.

        If TIF encounters any error, it will send a message to TORC
        and break.
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the filer."""
        pass

    def message(self, message: Message):
        """Message logic, send a message to TORC."""
        # TODO: Change this to id, it shouldn't be name
        if not hasattr(self, "name"):
            logger.error("The name attribute is not set")
            raise AttributeError("The name attribute is not set.")
        logger.info(f"Sending message to TORC: {message}")
        self.message_broker.publish(self.name, message)
