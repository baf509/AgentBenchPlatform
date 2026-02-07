"""Workspace domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    """A registered project directory, independent of tasks."""

    path: str  # absolute filesystem path
    name: str = ""  # display name (defaults to directory basename)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str | None = None

    @property
    def display_name(self) -> str:
        """Return name if set, otherwise the directory basename."""
        return self.name or Path(self.path).name

    def to_doc(self) -> dict:
        """Serialize to MongoDB document."""
        doc: dict = {
            "path": self.path,
            "name": self.name,
            "created_at": self.created_at,
        }
        if self.id:
            doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> Workspace:
        """Deserialize from MongoDB document."""
        return cls(
            id=str(doc["_id"]),
            path=doc["path"],
            name=doc.get("name", ""),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
        )
