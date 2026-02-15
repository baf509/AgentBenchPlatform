"""Conversation summary domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class ConversationSummary:
    """Summary of a portion of coordinator conversation history."""

    conversation_key: str
    summary: str
    exchanges_summarized: int = 0
    key_decisions: tuple[str, ...] = ()
    task_ids_referenced: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    superseded_by: str | None = None
    id: str | None = None

    def to_doc(self) -> dict:
        doc: dict = {
            "conversation_key": self.conversation_key,
            "summary": self.summary,
            "exchanges_summarized": self.exchanges_summarized,
            "key_decisions": list(self.key_decisions),
            "task_ids_referenced": list(self.task_ids_referenced),
            "created_at": self.created_at,
            "superseded_by": self.superseded_by,
        }
        if self.id:
            doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> ConversationSummary:
        return cls(
            id=str(doc["_id"]),
            conversation_key=doc["conversation_key"],
            summary=doc.get("summary", ""),
            exchanges_summarized=doc.get("exchanges_summarized", 0),
            key_decisions=tuple(doc.get("key_decisions", [])),
            task_ids_referenced=tuple(doc.get("task_ids_referenced", [])),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
            superseded_by=doc.get("superseded_by"),
        )
