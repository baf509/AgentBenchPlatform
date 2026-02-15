"""Conversation summary repository - MongoDB CRUD."""

from __future__ import annotations

import logging

from agentbenchplatform.models.conversation_summary import ConversationSummary

logger = logging.getLogger(__name__)


class ConversationSummaryRepo:
    """CRUD operations for conversation summaries in MongoDB."""

    COLLECTION = "conversation_summaries"

    def __init__(self, db) -> None:
        self._col = db[self.COLLECTION]

    async def insert(self, summary: ConversationSummary) -> ConversationSummary:
        """Insert a new summary. Returns summary with assigned id."""
        doc = summary.to_doc()
        doc.pop("_id", None)
        result = await self._col.insert_one(doc)
        return ConversationSummary(
            id=str(result.inserted_id),
            conversation_key=summary.conversation_key,
            summary=summary.summary,
            exchanges_summarized=summary.exchanges_summarized,
            key_decisions=summary.key_decisions,
            task_ids_referenced=summary.task_ids_referenced,
            created_at=summary.created_at,
            superseded_by=summary.superseded_by,
        )

    async def find_active(self, conversation_key: str) -> ConversationSummary | None:
        """Find the active (non-superseded) summary for a conversation."""
        doc = await self._col.find_one({
            "conversation_key": conversation_key,
            "superseded_by": None,
        })
        return ConversationSummary.from_doc(doc) if doc else None

    async def supersede(self, old_id: str, new_id: str) -> None:
        """Mark an old summary as superseded by a new one."""
        from bson import ObjectId

        await self._col.update_one(
            {"_id": ObjectId(old_id)},
            {"$set": {"superseded_by": new_id}},
        )
