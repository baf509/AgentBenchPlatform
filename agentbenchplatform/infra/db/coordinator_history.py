"""Coordinator conversation history - MongoDB persistence."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from agentbenchplatform.models.provider import LLMMessage

logger = logging.getLogger(__name__)


class CoordinatorHistoryRepo:
    """Persists coordinator conversation history in MongoDB.

    Each conversation is keyed by channel:sender_id and stored as a
    single document with a messages array.
    """

    COLLECTION = "coordinator_history"

    def __init__(self, db) -> None:
        self._col = db[self.COLLECTION]

    async def load_conversation(self, channel: str, sender_id: str = "") -> list[LLMMessage]:
        """Load conversation history for a channel/sender."""
        key = f"{channel}:{sender_id}"
        doc = await self._col.find_one({"key": key})
        if not doc:
            return []
        return [
            LLMMessage(
                role=m["role"],
                content=m.get("content", ""),
                tool_call_id=m.get("tool_call_id", ""),
                tool_calls=m.get("tool_calls"),
                name=m.get("name", ""),
            )
            for m in doc.get("messages", [])
        ]

    async def save_conversation(
        self, channel: str, sender_id: str, messages: list[LLMMessage]
    ) -> None:
        """Save (upsert) conversation history for a channel/sender."""
        key = f"{channel}:{sender_id}"
        await self._col.update_one(
            {"key": key},
            {
                "$set": {
                    "key": key,
                    "channel": channel,
                    "sender_id": sender_id,
                    "messages": [m.to_dict() for m in messages],
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )

    async def clear_conversation(self, channel: str, sender_id: str = "") -> bool:
        """Clear conversation history for a channel/sender."""
        key = f"{channel}:{sender_id}"
        result = await self._col.delete_one({"key": key})
        return result.deleted_count > 0

    async def list_conversations(self) -> list[dict]:
        """List all conversations with metadata.

        Uses single aggregation to avoid N+1 queries.
        """
        pipeline = [
            {"$sort": {"updated_at": -1}},
            {
                "$project": {
                    "key": 1,
                    "channel": 1,
                    "sender_id": 1,
                    "updated_at": 1,
                    "message_count": {"$size": "$messages"},
                }
            },
        ]

        cursor = self._col.aggregate(pipeline)
        results = []
        async for doc in cursor:
            results.append({
                "key": doc["key"],
                "channel": doc.get("channel", ""),
                "sender_id": doc.get("sender_id", ""),
                "updated_at": doc.get("updated_at"),
                "message_count": doc.get("message_count", 0),
            })
        return results
