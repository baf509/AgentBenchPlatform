"""Agent event domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class AgentEventType(str, Enum):
    STARTED = "started"
    OUTPUT = "output"
    STALLED = "stalled"
    ERROR = "error"
    COMPLETED = "completed"
    NEEDS_HELP = "needs_help"


@dataclass(frozen=True)
class AgentEvent:
    """Event emitted during agent session lifecycle."""

    session_id: str
    task_id: str
    event_type: AgentEventType
    detail: str = ""
    acknowledged: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str | None = None

    def to_doc(self) -> dict:
        doc: dict = {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "event_type": self.event_type.value,
            "detail": self.detail,
            "acknowledged": self.acknowledged,
            "created_at": self.created_at,
        }
        if self.id:
            doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> AgentEvent:
        return cls(
            id=str(doc["_id"]),
            session_id=doc["session_id"],
            task_id=doc.get("task_id", ""),
            event_type=AgentEventType(doc["event_type"]),
            detail=doc.get("detail", ""),
            acknowledged=doc.get("acknowledged", False),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
        )
