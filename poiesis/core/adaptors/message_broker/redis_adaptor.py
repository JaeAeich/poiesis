"""Redis message broker adaptor."""

import json
from collections.abc import Iterator

import redis

from poiesis.core.ports.message_broker import Message, MessageBroker


class RedisMessageBroker(MessageBroker):
    """Redis message broker.

    Args:
        host: The host of the Redis server
        port: The port of the Redis server

    Attributes:
        host: The host of the Redis server
        port: The port of the Redis server
        redis: The Redis client
        pubsub: The Redis pubsub client
    """

    def __init__(self, host: str = "localhost", port: int = 6379):
        """Initialise the Redis message broker.

        Args:
            host: The host of the Redis server
            port: The port of the Redis server

        Attributes:
            host: The host of the Redis server
            port: The port of the Redis server
            redis: The Redis client
            pubsub: The Redis pubsub client
        """
        self.host = host
        self.port = port
        self.redis = redis.Redis(host=host, port=port)
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
