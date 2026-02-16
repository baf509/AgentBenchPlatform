"""Tests for MemoryService with mocked dependencies."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agentbenchplatform.models.memory import MemoryEntry, MemoryQuery, MemoryScope
from agentbenchplatform.services.memory_service import MemoryService


@pytest.fixture
def mock_repo():
    return AsyncMock()


@pytest.fixture
def mock_embedding():
    svc = AsyncMock()
    svc.embed.return_value = [0.1, 0.2, 0.3]
    return svc


@pytest.fixture
def service(mock_repo, mock_embedding):
    return MemoryService(mock_repo, mock_embedding)


class TestMemoryService:
    @pytest.mark.asyncio
    async def test_store_with_embedding(self, service, mock_repo, mock_embedding):
        mock_repo.insert.return_value = MemoryEntry(
            key="test", content="hello",
            scope=MemoryScope.GLOBAL,
            embedding=[0.1, 0.2, 0.3],
            id="mem1",
        )
        entry = await service.store(key="test", content="hello")
        assert entry.embedding is not None
        mock_embedding.embed.assert_called_once_with("hello")

    @pytest.mark.asyncio
    async def test_store_without_embedding(self, service, mock_repo, mock_embedding):
        mock_embedding.embed.return_value = None
        mock_repo.insert.return_value = MemoryEntry(
            key="test", content="hello",
            scope=MemoryScope.GLOBAL,
            id="mem1",
        )
        await service.store(key="test", content="hello")
        mock_repo.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_with_vector(self, service, mock_repo, mock_embedding):
        mock_repo.vector_search.return_value = [
            MemoryEntry(
                key="result", content="found",
                scope=MemoryScope.GLOBAL, id="m1",
            )
        ]
        query = MemoryQuery(query_text="test query")
        results = await service.search(query)
        assert len(results) == 1
        mock_embedding.embed.assert_called_once_with("test query")
        mock_repo.vector_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_fallback_without_embedding(
        self, service, mock_repo, mock_embedding
    ):
        mock_embedding.embed.return_value = None
        mock_repo.list_global.return_value = []
        query = MemoryQuery(query_text="test", scope=MemoryScope.GLOBAL)
        await service.search(query)
        mock_repo.list_global.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_task_memories(self, service, mock_repo):
        mock_repo.list_by_task.return_value = []
        await service.get_task_memories("task1")
        mock_repo.list_by_task.assert_called_once_with("task1", MemoryScope.TASK)

    @pytest.mark.asyncio
    async def test_delete_memory(self, service, mock_repo):
        mock_repo.delete.return_value = True
        result = await service.delete_memory("mem1")
        assert result is True
