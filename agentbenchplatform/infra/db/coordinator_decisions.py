"""Coordinator decision repository - MongoDB CRUD."""

from __future__ import annotations

import logging

from agentbenchplatform.models.coordinator_decision import CoordinatorDecision

logger = logging.getLogger(__name__)


class CoordinatorDecisionRepo:
    """CRUD operations for coordinator decision logs in MongoDB."""

    COLLECTION = "coordinator_decisions"

    def __init__(self, db) -> None:
        self._col = db[self.COLLECTION]

    async def insert(self, decision: CoordinatorDecision) -> CoordinatorDecision:
        """Insert a new decision record. Returns decision with assigned id."""
        doc = decision.to_doc()
        doc.pop("_id", None)
        result = await self._col.insert_one(doc)
        return CoordinatorDecision(
            id=str(result.inserted_id),
            conversation_key=decision.conversation_key,
            turn_number=decision.turn_number,
            user_input=decision.user_input,
            tools_called=decision.tools_called,
            reasoning_excerpt=decision.reasoning_excerpt,
            final_response=decision.final_response,
            tokens=decision.tokens,
            model=decision.model,
            timestamp=decision.timestamp,
        )

    async def list_by_conversation(
        self, key: str, limit: int = 50
    ) -> list[CoordinatorDecision]:
        """List decisions for a conversation, most recent first."""
        cursor = (
            self._col.find({"conversation_key": key})
            .sort("timestamp", -1)
            .limit(limit)
        )
        return [CoordinatorDecision.from_doc(doc) async for doc in cursor]

    async def list_recent(self, limit: int = 20) -> list[CoordinatorDecision]:
        """List most recent decisions across all conversations."""
        cursor = self._col.find().sort("timestamp", -1).limit(limit)
        return [CoordinatorDecision.from_doc(doc) async for doc in cursor]
