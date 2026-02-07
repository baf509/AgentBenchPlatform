"""Usage event domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class UsageEvent:
    """Token usage event from coordinator or research LLM calls."""

    source: str  # "coordinator", "research"
    model: str
    input_tokens: int
    output_tokens: int
    task_id: str = ""
    session_id: str = ""
    channel: str = ""  # for coordinator: "tui", "signal"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str | None = None

    def to_doc(self) -> dict:
        """Serialize to MongoDB document."""
        doc: dict = {
            "source": self.source,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "channel": self.channel,
            "timestamp": self.timestamp,
        }
        if self.id:
            doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> UsageEvent:
        """Deserialize from MongoDB document."""
        return cls(
            id=str(doc["_id"]),
            source=doc["source"],
            model=doc.get("model", ""),
            input_tokens=doc.get("input_tokens", 0),
            output_tokens=doc.get("output_tokens", 0),
            task_id=doc.get("task_id", ""),
            session_id=doc.get("session_id", ""),
            channel=doc.get("channel", ""),
            timestamp=doc.get("timestamp", datetime.now(timezone.utc)),
        )
