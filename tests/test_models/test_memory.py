"""Tests for Memory model."""

import pytest

from agentbenchplatform.models.memory import MemoryEntry, MemoryQuery, MemoryScope


class TestMemoryEntry:
    def test_create_global(self):
        entry = MemoryEntry(key="test", content="hello", scope=MemoryScope.GLOBAL)
        assert entry.key == "test"
        assert entry.scope == MemoryScope.GLOBAL

    def test_task_scope_requires_task_id(self):
        with pytest.raises(ValueError, match="must have a task_id"):
            MemoryEntry(key="test", content="hello", scope=MemoryScope.TASK)

    def test_task_scope_with_task_id(self):
        entry = MemoryEntry(
            key="test", content="hello",
            scope=MemoryScope.TASK, task_id="task1",
        )
        assert entry.task_id == "task1"

    def test_session_scope_requires_session_id(self):
        with pytest.raises(ValueError, match="must have a session_id"):
            MemoryEntry(key="test", content="hello", scope=MemoryScope.SESSION)

    def test_empty_key_raises(self):
        with pytest.raises(ValueError, match="key cannot be empty"):
            MemoryEntry(key="", content="hello", scope=MemoryScope.GLOBAL)

    def test_empty_content_raises(self):
        with pytest.raises(ValueError, match="content cannot be empty"):
            MemoryEntry(key="test", content="", scope=MemoryScope.GLOBAL)

    def test_to_doc(self):
        entry = MemoryEntry(
            key="test", content="hello",
            scope=MemoryScope.GLOBAL,
            embedding=[0.1, 0.2, 0.3],
        )
        doc = entry.to_doc()
        assert doc["key"] == "test"
        assert doc["embedding"] == [0.1, 0.2, 0.3]

    def test_from_doc(self):
        from bson import ObjectId

        doc = {
            "_id": ObjectId(),
            "key": "test",
            "content": "hello",
            "scope": "global",
            "task_id": "",
            "session_id": "",
        }
        entry = MemoryEntry.from_doc(doc)
        assert entry.key == "test"
        assert entry.scope == MemoryScope.GLOBAL


class TestMemoryQuery:
    def test_create(self):
        q = MemoryQuery(query_text="auth patterns", task_id="task1", limit=5)
        assert q.query_text == "auth patterns"
        assert q.limit == 5
