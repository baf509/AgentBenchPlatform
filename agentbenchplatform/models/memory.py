"""Memory domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class MemoryScope(str, Enum):
    TASK = "task"
    SESSION = "session"
    GLOBAL = "global"


@dataclass(frozen=True)
class MemoryEntry:
    """A memory entry with optional embedding vector."""

    key: str
    content: str
    scope: MemoryScope
    task_id: str = ""
    session_id: str = ""
    content_type: str = "text"
    embedding: list[float] | None = None
    metadata: dict | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str | None = None

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("MemoryEntry key cannot be empty")
        if not self.content:
            raise ValueError("MemoryEntry content cannot be empty")
        if self.scope == MemoryScope.TASK and not self.task_id:
            raise ValueError("Task-scoped memory must have a task_id")
        if self.scope == MemoryScope.SESSION and not self.session_id:
            raise ValueError("Session-scoped memory must have a session_id")

    def to_doc(self) -> dict:
        doc: dict = {
            "key": self.key,
            "content": self.content,
            "scope": self.scope.value,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "content_type": self.content_type,
            "embedding": self.embedding,
            "metadata": self.metadata or {},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.id:
            doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> MemoryEntry:
        return cls(
            id=str(doc["_id"]),
            key=doc["key"],
            content=doc["content"],
            scope=MemoryScope(doc["scope"]),
            task_id=doc.get("task_id", ""),
            session_id=doc.get("session_id", ""),
            content_type=doc.get("content_type", "text"),
            embedding=doc.get("embedding"),
            metadata=doc.get("metadata"),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
            updated_at=doc.get("updated_at", datetime.now(timezone.utc)),
        )


@dataclass(frozen=True)
class MemoryQuery:
    """Parameters for searching memories."""

    query_text: str
    task_id: str = ""
    scope: MemoryScope | None = None
    limit: int = 10
    min_score: float = 0.0
