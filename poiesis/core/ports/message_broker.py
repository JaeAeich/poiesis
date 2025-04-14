"""Messaging/Eventing ports."""

import json
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum


class MessageStatus(Enum):
    """Status of K8s job sent via message broker."""

    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


@dataclass
class Message:
    """Base message class for all messages in the system."""

    message: str
    status: MessageStatus = field(default_factory=lambda: MessageStatus.SUCCESS)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_json(self) -> str:
        """Convert to json string."""
        dict_data = asdict(self)
        dict_data["timestamp"] = dict_data["timestamp"].isoformat()
        dict_data["status"] = dict_data["status"].value

        return json.dumps(dict_data)


class MessageBroker(ABC):
    """Abstract base class for message broker implementations."""

    @abstractmethod
    def publish(self, channel: str, message: Message) -> None:
        """Publish a message to a specific channel.

        Args:
            channel: The channel/topic to publish to
            message: The message to publish
        """
        pass

    @abstractmethod
    def subscribe(self, channel: str) -> Iterator[Message]:
        """Subscribe to a channel and yield messages as they arrive.

        Args:
            channel: The channel/topic to subscribe to

        Returns:
            Iterator yielding messages as they arrive
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the message broker."""
        pass
