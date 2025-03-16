"""MongoDB adaptor for NoSQL database operations."""

from contextlib import asynccontextmanager

import motor.motor_asyncio
from pydantic import BaseModel

from poiesis.api.exceptions import DBException
from poiesis.constants import get_poiesis_constants

poiesis_constants = get_poiesis_constants()


class MongoDBClient:
    """Simple MongoDB client using Motor for async operations."""

    def __init__(self) -> None:
        """Initialize MongoDB client with connection pooling.

        Args:
            connection_string: MongoDB connection URI
            database: Default database name
            max_pool_size: Maximum number of connections in the pool
        """
        self.connection_string = poiesis_constants.Database.MongoDB.CONNECTION_STRING
        self.database = poiesis_constants.Database.MongoDB.DATABASE
        self.max_pool_size = poiesis_constants.Database.MongoDB.MAX_POOL_SIZE
        self.client: motor.motor_asyncio.AsyncIOMotorClient = (
            motor.motor_asyncio.AsyncIOMotorClient(
                self.connection_string, maxPoolSize=self.max_pool_size
            )
        )
        self.db = self.client[self.database]

    async def insert_one(self, collection: str, document: BaseModel) -> str:
        """Insert a single document into the specified collection.

        Args:
            collection: Collection name
            document: Document to insert

        Returns:
            The inserted document ID as a string

        Raises:
            DBException: If the document is not valid or the insert operation fails
        """
        try:
            result = await self.db[collection].insert_one(document.model_dump())
            return str(result.inserted_id)
        except Exception as e:
            raise DBException(
                f"Error inserting document into collection {collection}: {e}"
            ) from e

    @asynccontextmanager
    async def connection(self):
        """Async context manager for explicit connection handling.

        Yields:
            AsyncIOMotorDatabase instance
        """
        try:
            yield self.db
        finally:
            # Motor handles connection pooling internally
            pass

    async def close(self):
        """Close all connections in the pool."""
        self.client.close()
