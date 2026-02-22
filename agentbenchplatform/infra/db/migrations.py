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

    # Session reports indexes
    session_reports = db["session_reports"]
    await session_reports.create_index([("session_id", pymongo.ASCENDING)], unique=True)
    await session_reports.create_index(
        [("task_id", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)]
    )

    # Coordinator decisions indexes
    coordinator_decisions = db["coordinator_decisions"]
    await coordinator_decisions.create_index(
        [("conversation_key", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)]
    )
    await coordinator_decisions.create_index([("timestamp", pymongo.DESCENDING)])

    # Conversation summaries indexes
    conversation_summaries = db["conversation_summaries"]
    await conversation_summaries.create_index(
        [("conversation_key", pymongo.ASCENDING), ("superseded_by", pymongo.ASCENDING)]
    )

    # Agent events indexes
    agent_events = db["agent_events"]
    await agent_events.create_index(
        [("session_id", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)]
    )
    await agent_events.create_index(
        [("acknowledged", pymongo.ASCENDING), ("event_type", pymongo.ASCENDING)]
    )

    # Additional usage_events indexes
    usage_events = db["usage_events"]
    await usage_events.create_index(
        [("source", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)]
    )
    await usage_events.create_index(
        [("task_id", pymongo.ASCENDING), ("source", pymongo.ASCENDING)]
    )

    # Task depends_on index
    await tasks.create_index([("depends_on", pymongo.ASCENDING)])

    # Merge records indexes
    merge_records = db["merge_records"]
    await merge_records.create_index([("session_id", pymongo.ASCENDING)], unique=True)
    await merge_records.create_index([("task_id", pymongo.ASCENDING)])

    # Session metrics indexes
    session_metrics = db["session_metrics"]
    await session_metrics.create_index([("session_id", pymongo.ASCENDING)], unique=True)
    await session_metrics.create_index(
        [("agent_backend", pymongo.ASCENDING), ("complexity", pymongo.ASCENDING)]
    )

    # Playbooks indexes
    playbooks = db["playbooks"]
    await playbooks.create_index([("name", pymongo.ASCENDING)], unique=True)

    logger.info("MongoDB migrations complete")
