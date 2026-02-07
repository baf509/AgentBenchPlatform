"""MongoDB index and vector search index creation."""

from __future__ import annotations

import logging

import pymongo

logger = logging.getLogger(__name__)


async def run_migrations(db) -> None:
    """Create indexes and vector search indexes on startup."""
    logger.info("Running MongoDB migrations...")

    # Tasks indexes
    tasks = db["tasks"]
    await tasks.create_index([("slug", pymongo.ASCENDING)], unique=True)
    await tasks.create_index([("status", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)])

    # Sessions indexes
    sessions = db["sessions"]
    await sessions.create_index(
        [("task_id", pymongo.ASCENDING), ("lifecycle", pymongo.ASCENDING)]
    )
    await sessions.create_index(
        [("lifecycle", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)]
    )

    # Memories indexes
    memories = db["memories"]
    await memories.create_index(
        [
            ("task_id", pymongo.ASCENDING),
            ("scope", pymongo.ASCENDING),
            ("key", pymongo.ASCENDING),
        ]
    )
    await memories.create_index([("scope", pymongo.ASCENDING)])

    # Coordinator conversations indexes
    conversations = db["coordinator_conversations"]
    await conversations.create_index(
        [("channel", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)]
    )

    logger.info("MongoDB migrations complete")


async def create_vector_search_index(db, dimensions: int = 768) -> None:
    """Create the vector search index for the memories collection.

    NOTE: This requires MongoDB Atlas or a local deployment with
    mongot (Atlas Search). It cannot be created via the standard
    createIndex command - it must be created via the Atlas API or
    mongosh createSearchIndex command.

    This function attempts the createSearchIndex command and logs
    instructions if it fails.
    """
    try:
        await db.command({
            "createSearchIndexes": "memories",
            "indexes": [
                {
                    "name": "memory_vector_index",
                    "type": "vectorSearch",
                    "definition": {
                        "fields": [
                            {
                                "type": "vector",
                                "path": "embedding",
                                "numDimensions": dimensions,
                                "similarity": "cosine",
                            }
                        ]
                    },
                }
            ],
        })
        logger.info("Vector search index created successfully")
    except Exception as e:
        logger.warning(
            "Could not create vector search index automatically: %s. "
            "You may need to create it manually via Atlas UI or mongosh.",
            e,
        )
