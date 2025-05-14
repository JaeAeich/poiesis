"""Redis message broker adaptor."""

import json
import os
from collections.abc import Iterator

import redis

from poiesis.constants import get_poiesis_constants
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.ports.message_broker import Message, MessageBroker

constants = get_poiesis_constants()
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
        host = os.getenv("MESSAGE_BROKER_HOST")
        port = os.getenv("MESSAGE_BROKER_PORT")

        if not host or not port:
            raise RuntimeError(
                "Redis configuration is incomplete: both MESSAGE_BROKER_HOST"
                " and MESSAGE_BROKER_PORT are required."
            )

        password = os.getenv("MESSAGE_BROKER_PASSWORD")

        redis_args = {
            "host": host,
            "port": int(port),
        }

        if password:
            redis_args["password"] = password

        self.redis = redis.Redis(**redis_args)
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
