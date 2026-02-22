"""Session metric domain model — tracks session durations for progress estimation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class SessionMetric:
    """Duration metric for a completed session."""

    session_id: str
    task_id: str
    agent_backend: str
    complexity: str = ""
    status: str = "success"
    duration_seconds: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str | None = None

    def to_doc(self) -> dict:
        doc: dict = {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "agent_backend": self.agent_backend,
            "complexity": self.complexity,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at,
        }
        if self.id:
            doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> SessionMetric:
        return cls(
            id=str(doc["_id"]),
            session_id=doc["session_id"],
            task_id=doc["task_id"],
            agent_backend=doc["agent_backend"],
            complexity=doc.get("complexity", ""),
            status=doc.get("status", "success"),
            duration_seconds=doc.get("duration_seconds", 0),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
        )
