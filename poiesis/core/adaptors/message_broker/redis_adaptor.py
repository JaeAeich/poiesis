"""Redis message broker adaptor."""

import json
import os
from collections.abc import Iterator

import redis

from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.ports.message_broker import Message, MessageBroker

core_constants = get_poiesis_core_constants()


class RedisMessageBroker(MessageBroker):
    """Redis message broker.

    Attributes:
        redis: The Redis client
        pubsub: The Redis pubsub client
    """

    def __init__(self):
        """Initialise the Redis message broker.

        Attributes:
            redis: The Redis client
            pubsub: The Redis pubsub client
        """
        self.redis = redis.Redis(
            host=os.getenv("MESSAGE_BROKER_HOST", "redis"),
            port=int(os.getenv("MESSAGE_BROKER_PORT", "6379")),
        )
        self.pubsub = self.redis.pubsub()

    def publish(self, channel: str, message: Message) -> None:
        """Publish a message to a channel.

        Args:
            channel: The channel/topic to publish to
            message: The message to publish
        """
        self.redis.publish(channel, message.to_json())

    def subscribe(self, channel: str) -> Iterator[Message]:
        """Subscribe to a channel.

        Args:
            channel: The channel/topic to subscribe to

        Returns:
            An async iterator of messages
        """
        self.pubsub.subscribe(channel)
        for message in self.pubsub.listen():
            if message["type"] == "message":
                yield Message(**json.loads(message["data"]))

    def close(self) -> None:
        """Close the message broker."""
        self.pubsub.close()
        self.redis.close()
        del self
