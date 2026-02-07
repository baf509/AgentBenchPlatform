"""Memory business logic: store/search with auto-embedding."""

from __future__ import annotations

import logging

from agentbenchplatform.infra.db.memory import MemoryRepo
from agentbenchplatform.models.memory import MemoryEntry, MemoryQuery, MemoryScope
from agentbenchplatform.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class MemoryService:
    """Business logic for memory management with auto-embedding."""

    def __init__(
        self,
        memory_repo: MemoryRepo,
        embedding_service: EmbeddingService,
    ) -> None:
        self._repo = memory_repo
        self._embedding = embedding_service

    async def store(
        self,
        key: str,
        content: str,
        scope: MemoryScope = MemoryScope.GLOBAL,
        task_id: str = "",
        session_id: str = "",
        content_type: str = "text",
        metadata: dict | None = None,
    ) -> MemoryEntry:
        """Store a memory entry with auto-embedding."""
        # Generate embedding
        embedding = await self._embedding.embed(content)

        entry = MemoryEntry(
            key=key,
            content=content,
            scope=scope,
            task_id=task_id,
            session_id=session_id,
            content_type=content_type,
            embedding=embedding,
            metadata=metadata,
        )

        stored = await self._repo.insert(entry)

        if embedding:
            logger.debug("Stored memory '%s' with embedding (%d dims)", key, len(embedding))
        else:
            logger.debug("Stored memory '%s' without embedding", key)

        return stored

    async def search(self, query: MemoryQuery) -> list[MemoryEntry]:
        """Search memories using vector similarity.

        Falls back to listing by task if embeddings unavailable.
        """
        # Try vector search first
        query_embedding = await self._embedding.embed(query.query_text)

        if query_embedding:
            return await self._repo.vector_search(
                query_embedding=query_embedding,
                limit=query.limit,
                task_id=query.task_id,
                scope=query.scope,
            )

        # Fallback: return task memories if specified
        logger.debug("Vector search unavailable, falling back to listing")
        if query.task_id:
            return await self._repo.list_by_task(query.task_id, query.scope)
        if query.scope == MemoryScope.GLOBAL:
            return await self._repo.list_global()
        return []

    async def get_task_memories(self, task_id: str) -> list[MemoryEntry]:
        """All shared memories for a task."""
        return await self._repo.list_by_task(task_id, MemoryScope.TASK)

    async def get_context_for_agent(
        self, task_id: str, session_id: str
    ) -> list[MemoryEntry]:
        """Task-scoped + session-scoped memories for an agent."""
        task_memories = await self._repo.list_by_task(task_id, MemoryScope.TASK)
        session_memories = await self._repo.list_by_session(session_id)
        return task_memories + session_memories

    async def list_memories(
        self,
        task_id: str = "",
        scope: MemoryScope | None = None,
    ) -> list[MemoryEntry]:
        """List memories, optionally filtered."""
        if task_id:
            return await self._repo.list_by_task(task_id, scope)
        if scope == MemoryScope.GLOBAL:
            return await self._repo.list_global()
        return await self._repo.list_by_task("", scope)

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory entry."""
        return await self._repo.delete(memory_id)
