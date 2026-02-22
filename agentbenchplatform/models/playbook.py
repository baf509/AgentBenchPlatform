"""Playbook domain model — reusable multi-step task templates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class PlaybookStep:
    """A single step in a playbook."""

    action: str  # "create_task", "start_session", "review_session", "merge_session"
    params: dict = field(default_factory=dict)

    def to_doc(self) -> dict:
        return {"action": self.action, "params": self.params}

    @classmethod
    def from_doc(cls, doc: dict) -> PlaybookStep:
        return cls(action=doc["action"], params=doc.get("params", {}))


@dataclass(frozen=True)
class Playbook:
    """Reusable multi-step recipe stored in MongoDB."""

    name: str
    description: str = ""
    steps: tuple[PlaybookStep, ...] = ()
    workspace_path: str = ""
    tags: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str | None = None

    def to_doc(self) -> dict:
        doc: dict = {
            "name": self.name,
            "description": self.description,
            "steps": [s.to_doc() for s in self.steps],
            "workspace_path": self.workspace_path,
            "tags": list(self.tags),
            "created_at": self.created_at,
        }
        if self.id:
            doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> Playbook:
        return cls(
            id=str(doc["_id"]),
            name=doc["name"],
            description=doc.get("description", ""),
            steps=tuple(PlaybookStep.from_doc(s) for s in doc.get("steps", [])),
            workspace_path=doc.get("workspace_path", ""),
            tags=tuple(doc.get("tags", [])),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
        )
