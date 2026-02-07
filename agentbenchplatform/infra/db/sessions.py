"""Session repository - MongoDB CRUD for sessions."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from agentbenchplatform.models.session import Session, SessionLifecycle

logger = logging.getLogger(__name__)


class SessionRepo:
    """CRUD operations for sessions in MongoDB."""

    COLLECTION = "sessions"

    def __init__(self, db) -> None:
        self._col = db[self.COLLECTION]

    async def insert(self, session: Session) -> Session:
        """Insert a new session. Returns session with assigned id."""
        doc = session.to_doc()
        doc.pop("_id", None)
        result = await self._col.insert_one(doc)
        return Session(
            id=str(result.inserted_id),
            task_id=session.task_id,
            kind=session.kind,
            lifecycle=session.lifecycle,
            agent_backend=session.agent_backend,
            display_name=session.display_name,
            agent_thread_id=session.agent_thread_id,
            worktree_path=session.worktree_path,
            attachment=session.attachment,
            research_progress=session.research_progress,
            created_at=session.created_at,
            updated_at=session.updated_at,
            archived_at=session.archived_at,
        )

    async def find_by_id(self, session_id: str) -> Session | None:
        """Find a session by ID."""
        try:
            doc = await self._col.find_one({"_id": ObjectId(session_id)})
            return Session.from_doc(doc) if doc else None
        except InvalidId:
            logger.debug("Invalid ObjectId: %s", session_id)
            return None

    async def list_by_task(
        self, task_id: str, lifecycle: SessionLifecycle | None = None
    ) -> list[Session]:
        """List sessions for a task."""
        query: dict = {"task_id": task_id}
        if lifecycle:
            query["lifecycle"] = lifecycle.value
        cursor = self._col.find(query).sort("created_at", -1)
        return [Session.from_doc(doc) async for doc in cursor]

    async def list_all(
        self, lifecycle: SessionLifecycle | None = None
    ) -> list[Session]:
        """List all sessions, optionally filtered by lifecycle."""
        query: dict = {}
        if lifecycle:
            query["lifecycle"] = lifecycle.value
        cursor = self._col.find(query).sort("created_at", -1)
        return [Session.from_doc(doc) async for doc in cursor]

    async def update_lifecycle(
        self, session_id: str, lifecycle: SessionLifecycle
    ) -> Session | None:
        """Update a session's lifecycle."""
        try:
            now = datetime.now(timezone.utc)
            updates: dict = {"lifecycle": lifecycle.value, "updated_at": now}
            if lifecycle == SessionLifecycle.ARCHIVED:
                updates["archived_at"] = now
            result = await self._col.find_one_and_update(
                {"_id": ObjectId(session_id)},
                {"$set": updates},
                return_document=True,
            )
            return Session.from_doc(result) if result else None
        except InvalidId:
            logger.debug("Invalid ObjectId: %s", session_id)
            return None

    async def update_worktree_path(self, session_id: str, path: str) -> Session | None:
        """Update a session's worktree_path."""
        try:
            result = await self._col.find_one_and_update(
                {"_id": ObjectId(session_id)},
                {"$set": {"worktree_path": path, "updated_at": datetime.now(timezone.utc)}},
                return_document=True,
            )
            return Session.from_doc(result) if result else None
        except InvalidId:
            logger.debug("Invalid ObjectId: %s", session_id)
            return None

    async def update_attachment(self, session_id: str, attachment_doc: dict) -> Session | None:
        """Update a session's attachment info."""
        try:
            result = await self._col.find_one_and_update(
                {"_id": ObjectId(session_id)},
                {"$set": {"attachment": attachment_doc, "updated_at": datetime.now(timezone.utc)}},
                return_document=True,
            )
            return Session.from_doc(result) if result else None
        except InvalidId:
            logger.debug("Invalid ObjectId: %s", session_id)
            return None

    async def update_research_progress(
        self, session_id: str, progress_doc: dict
    ) -> Session | None:
        """Update research progress on a session."""
        try:
            result = await self._col.find_one_and_update(
                {"_id": ObjectId(session_id)},
                {
                    "$set": {
                        "research_progress": progress_doc,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
                return_document=True,
            )
            return Session.from_doc(result) if result else None
        except InvalidId:
            logger.debug("Invalid ObjectId: %s", session_id)
            return None

    async def count_by_lifecycle(self, lifecycle: SessionLifecycle) -> int:
        """Count sessions with a given lifecycle."""
        return await self._col.count_documents({"lifecycle": lifecycle.value})
