"""Agent event repository - MongoDB CRUD."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from agentbenchplatform.models.agent_event import AgentEvent

logger = logging.getLogger(__name__)


class AgentEventRepo:
    """CRUD operations for agent events in MongoDB."""

    COLLECTION = "agent_events"

    def __init__(self, db) -> None:
        self._col = db[self.COLLECTION]

    async def insert(self, event: AgentEvent) -> AgentEvent:
        """Insert a new event. Returns event with assigned id."""
        doc = event.to_doc()
        doc.pop("_id", None)
        result = await self._col.insert_one(doc)
        return AgentEvent(
            id=str(result.inserted_id),
            session_id=event.session_id,
            task_id=event.task_id,
            event_type=event.event_type,
            detail=event.detail,
            acknowledged=event.acknowledged,
            created_at=event.created_at,
        )

    async def has_recent_unacked(
        self, session_id: str, event_type: str, within_seconds: int = 600,
    ) -> bool:
        """Check if an unacknowledged event of this type exists for the session
        within the given time window. Used to prevent duplicate STALLED/WAITING
        events from being inserted."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=within_seconds)
        count = await self._col.count_documents({
            "session_id": session_id,
            "event_type": event_type,
            "acknowledged": False,
            "created_at": {"$gte": cutoff},
        })
        return count > 0

    async def list_by_session(
        self, session_id: str, limit: int = 50
    ) -> list[AgentEvent]:
        """List events for a session, most recent first."""
        cursor = (
            self._col.find({"session_id": session_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        return [AgentEvent.from_doc(doc) async for doc in cursor]

    async def list_unacknowledged(
        self,
        event_types: list[str] | None = None,
        limit: int = 50,
    ) -> list[AgentEvent]:
        """List unacknowledged events, optionally filtered by type."""
        query: dict = {"acknowledged": False}
        if event_types:
            query["event_type"] = {"$in": event_types}
        cursor = (
            self._col.find(query)
            .sort("created_at", -1)
            .limit(limit)
        )
        return [AgentEvent.from_doc(doc) async for doc in cursor]

    async def acknowledge(self, event_ids: list[str]) -> int:
        """Mark events as acknowledged. Returns count of modified documents."""
        if not event_ids:
            return 0
        result = await self._col.update_many(
            {"_id": {"$in": [ObjectId(eid) for eid in event_ids]}},
            {"$set": {"acknowledged": True}},
        )
        return result.modified_count

    async def list_recent(self, limit: int = 20) -> list[AgentEvent]:
        """List most recent events across all sessions."""
        cursor = self._col.find().sort("created_at", -1).limit(limit)
        return [AgentEvent.from_doc(doc) async for doc in cursor]
