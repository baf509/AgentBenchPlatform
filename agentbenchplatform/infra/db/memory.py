"""Memory repository - MongoDB CRUD with vector search for memories."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bson import ObjectId

from agentbenchplatform.models.memory import MemoryEntry, MemoryScope

logger = logging.getLogger(__name__)


class MemoryRepo:
    """CRUD operations for memories in MongoDB with vector search support."""

    COLLECTION = "memories"

    def __init__(self, db) -> None:
        self._col = db[self.COLLECTION]

    async def insert(self, entry: MemoryEntry) -> MemoryEntry:
        """Insert a new memory entry."""
        doc = entry.to_doc()
        doc.pop("_id", None)
        result = await self._col.insert_one(doc)
        return MemoryEntry(
            id=str(result.inserted_id),
            key=entry.key,
            content=entry.content,
            scope=entry.scope,
            task_id=entry.task_id,
            session_id=entry.session_id,
            content_type=entry.content_type,
            embedding=entry.embedding,
            metadata=entry.metadata,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    async def find_by_id(self, memory_id: str) -> MemoryEntry | None:
        """Find a memory entry by ID."""
        doc = await self._col.find_one({"_id": ObjectId(memory_id)})
        return MemoryEntry.from_doc(doc) if doc else None

    async def find_by_key(self, key: str, task_id: str = "") -> MemoryEntry | None:
        """Find a memory entry by key (and optionally task_id)."""
        query: dict = {"key": key}
        if task_id:
            query["task_id"] = task_id
        doc = await self._col.find_one(query)
        return MemoryEntry.from_doc(doc) if doc else None

    async def list_by_task(
        self, task_id: str, scope: MemoryScope | None = None
    ) -> list[MemoryEntry]:
        """List memories for a task."""
        query: dict = {"task_id": task_id}
        if scope:
            query["scope"] = scope.value
        cursor = self._col.find(query).sort("created_at", -1)
        return [MemoryEntry.from_doc(doc) async for doc in cursor]

    async def list_by_session(self, session_id: str) -> list[MemoryEntry]:
        """List memories for a session."""
        cursor = self._col.find({"session_id": session_id}).sort("created_at", -1)
        return [MemoryEntry.from_doc(doc) async for doc in cursor]

    async def list_global(self) -> list[MemoryEntry]:
        """List all global-scoped memories."""
        cursor = self._col.find({"scope": MemoryScope.GLOBAL.value}).sort("created_at", -1)
        return [MemoryEntry.from_doc(doc) async for doc in cursor]

    async def vector_search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        task_id: str = "",
        scope: MemoryScope | None = None,
    ) -> list[MemoryEntry]:
        """Perform vector similarity search using MongoDB $vectorSearch.

        Requires a vector search index named 'memory_vector_index' on the
        'embedding' field.
        """
        pipeline: list[dict] = [
            {
                "$vectorSearch": {
                    "index": "memory_vector_index",
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": limit * 10,
                    "limit": limit,
                }
            },
            {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        ]

        # Post-filter by task_id and/or scope
        match_stage: dict = {}
        if task_id:
            match_stage["task_id"] = task_id
        if scope:
            match_stage["scope"] = scope.value
        if match_stage:
            pipeline.append({"$match": match_stage})

        results = []
        async for doc in self._col.aggregate(pipeline):
            results.append(MemoryEntry.from_doc(doc))
        return results

    async def update_content(
        self, memory_id: str, content: str, embedding: list[float] | None = None
    ) -> MemoryEntry | None:
        """Update content and optionally re-embed."""
        updates: dict = {
            "content": content,
            "updated_at": datetime.now(timezone.utc),
        }
        if embedding is not None:
            updates["embedding"] = embedding
        result = await self._col.find_one_and_update(
            {"_id": ObjectId(memory_id)},
            {"$set": updates},
            return_document=True,
        )
        return MemoryEntry.from_doc(result) if result else None

    async def delete(self, memory_id: str) -> bool:
        """Delete a memory entry by ID."""
        result = await self._col.delete_one({"_id": ObjectId(memory_id)})
        return result.deleted_count > 0
