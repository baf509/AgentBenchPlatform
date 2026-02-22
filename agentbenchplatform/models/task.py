"""Task domain model."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class TaskStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


def _slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


@dataclass(frozen=True)
class Task:
    """Durable unit of work with slug, title, status, workspace path, tags."""

    slug: str
    title: str
    status: TaskStatus = TaskStatus.ACTIVE
    description: str = ""
    workspace_path: str = ""
    tags: tuple[str, ...] = ()
    complexity: str = ""  # "", "junior", "mid", "senior"
    depends_on: tuple[str, ...] = ()  # slugs of tasks this task depends on
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str | None = None

    def __post_init__(self) -> None:
        if not self.slug:
            raise ValueError("Task slug cannot be empty")
        if not self.title:
            raise ValueError("Task title cannot be empty")

    @classmethod
    def create(
        cls,
        title: str,
        description: str = "",
        workspace_path: str = "",
        tags: tuple[str, ...] = (),
        complexity: str = "",
        depends_on: tuple[str, ...] = (),
    ) -> Task:
        """Create a new task, auto-generating slug from title."""
        slug = _slugify(title)
        if not slug:
            raise ValueError(f"Cannot generate slug from title: {title!r}")
        return cls(
            slug=slug,
            title=title,
            description=description,
            workspace_path=workspace_path,
            tags=tags,
            complexity=complexity,
            depends_on=depends_on,
        )

    def with_status(self, status: TaskStatus) -> Task:
        """Return a copy with updated status and timestamp."""
        now = datetime.now(timezone.utc)
        return Task(
            slug=self.slug,
            title=self.title,
            status=status,
            description=self.description,
            workspace_path=self.workspace_path,
            tags=self.tags,
            complexity=self.complexity,
            depends_on=self.depends_on,
            created_at=self.created_at,
            updated_at=now,
            id=self.id,
        )

    def to_doc(self) -> dict:
        """Serialize to MongoDB document."""
        doc: dict = {
            "slug": self.slug,
            "title": self.title,
            "status": self.status.value,
            "description": self.description,
            "workspace_path": self.workspace_path,
            "tags": list(self.tags),
            "complexity": self.complexity,
            "depends_on": list(self.depends_on),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.id:
            doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> Task:
        """Deserialize from MongoDB document."""
        return cls(
            id=str(doc["_id"]),
            slug=doc["slug"],
            title=doc["title"],
            status=TaskStatus(doc["status"]),
            description=doc.get("description", ""),
            workspace_path=doc.get("workspace_path", ""),
            tags=tuple(doc.get("tags", [])),
            complexity=doc.get("complexity", ""),
            depends_on=tuple(doc.get("depends_on", [])),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
            updated_at=doc.get("updated_at", datetime.now(timezone.utc)),
        )
