"""Motor async MongoDB wrapper."""

from __future__ import annotations

import logging

import motor.motor_asyncio

logger = logging.getLogger(__name__)


class MongoClient:
    """Thin wrapper around Motor's async MongoDB client."""

    def __init__(self, uri: str = "mongodb://localhost:27017", database: str = "agentbenchplatform"):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self._db = self._client[database]
        logger.info("MongoDB client created: %s/%s", uri, database)

    @property
    def db(self) -> motor.motor_asyncio.AsyncIOMotorDatabase:
        return self._db

    @property
    def client(self) -> motor.motor_asyncio.AsyncIOMotorClient:
        return self._client

    def close(self) -> None:
        self._client.close()
        logger.info("MongoDB client closed")

    async def ping(self) -> bool:
        """Check if MongoDB is reachable."""
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:
            logger.warning("MongoDB ping failed")
            return False
