"""Merge record repository - MongoDB CRUD."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from agentbenchplatform.models.merge_record import MergeRecord

logger = logging.getLogger(__name__)


class MergeRecordRepo:
    """CRUD operations for merge records in MongoDB."""

    COLLECTION = "merge_records"

    def __init__(self, db) -> None:
        self._col = db[self.COLLECTION]

    async def insert(self, record: MergeRecord) -> MergeRecord:
        """Insert a new merge record."""
        doc = record.to_doc()
        doc.pop("_id", None)
        result = await self._col.insert_one(doc)
        return MergeRecord(
            id=str(result.inserted_id),
            session_id=record.session_id,
            task_id=record.task_id,
            branch_name=record.branch_name,
            merge_commit_sha=record.merge_commit_sha,
            merged_at=record.merged_at,
        )

    async def find_by_session(self, session_id: str) -> MergeRecord | None:
        """Find a merge record by session ID."""
        doc = await self._col.find_one({"session_id": session_id})
        return MergeRecord.from_doc(doc) if doc else None

    async def mark_reverted(self, session_id: str, revert_sha: str) -> bool:
        """Mark a merge record as reverted."""
        result = await self._col.find_one_and_update(
            {"session_id": session_id},
            {"$set": {
                "reverted": True,
                "revert_commit_sha": revert_sha,
                "reverted_at": datetime.now(timezone.utc),
            }},
        )
        return result is not None

    async def list_by_task(self, task_id: str) -> list[MergeRecord]:
        """List merge records for a task."""
        cursor = self._col.find({"task_id": task_id}).sort("merged_at", -1)
        return [MergeRecord.from_doc(doc) async for doc in cursor]
