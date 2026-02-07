"""Session domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SessionKind(str, Enum):
    CODING_AGENT = "coding_agent"
    RESEARCH_AGENT = "research_agent"
    SHELL = "shell"


class SessionLifecycle(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"

    @property
    def is_terminal(self) -> bool:
        return self in (
            SessionLifecycle.COMPLETED,
            SessionLifecycle.FAILED,
            SessionLifecycle.ARCHIVED,
        )


@dataclass(frozen=True)
class SessionAttachment:
    """Tracks how a session is attached to a subprocess."""

    pid: int | None = None
    tmux_session: str = ""
    tmux_window: str = ""
    tmux_pane_id: str = ""

    def to_doc(self) -> dict:
        return {
            "pid": self.pid,
            "tmux_session": self.tmux_session,
            "tmux_window": self.tmux_window,
            "tmux_pane_id": self.tmux_pane_id,
        }

    @classmethod
    def from_doc(cls, doc: dict) -> SessionAttachment:
        if not doc:
            return cls()
        return cls(
            pid=doc.get("pid"),
            tmux_session=doc.get("tmux_session", ""),
            tmux_window=doc.get("tmux_window", ""),
            tmux_pane_id=doc.get("tmux_pane_id", ""),
        )


@dataclass(frozen=True)
class ResearchProgress:
    """Tracks research agent progress."""

    current_depth: int = 0
    max_depth: int = 0
    queries_completed: int = 0
    queries_total: int = 0
    learnings_count: int = 0

    def to_doc(self) -> dict:
        return {
            "current_depth": self.current_depth,
            "max_depth": self.max_depth,
            "queries_completed": self.queries_completed,
            "queries_total": self.queries_total,
            "learnings_count": self.learnings_count,
        }

    @classmethod
    def from_doc(cls, doc: dict) -> ResearchProgress:
        if not doc:
            return cls()
        return cls(
            current_depth=doc.get("current_depth", 0),
            max_depth=doc.get("max_depth", 0),
            queries_completed=doc.get("queries_completed", 0),
            queries_total=doc.get("queries_total", 0),
            learnings_count=doc.get("learnings_count", 0),
        )


@dataclass(frozen=True)
class Session:
    """Execution record tied to a task."""

    task_id: str
    kind: SessionKind
    lifecycle: SessionLifecycle = SessionLifecycle.PENDING
    agent_backend: str = ""
    display_name: str = ""
    agent_thread_id: str = ""
    worktree_path: str = ""
    attachment: SessionAttachment = field(default_factory=SessionAttachment)
    research_progress: ResearchProgress | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    archived_at: datetime | None = None
    id: str | None = None

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("Session must have a task_id")

    def with_lifecycle(self, lifecycle: SessionLifecycle) -> Session:
        """Return a copy with updated lifecycle and timestamp."""
        now = datetime.now(timezone.utc)
        archived = now if lifecycle == SessionLifecycle.ARCHIVED else self.archived_at
        return Session(
            task_id=self.task_id,
            kind=self.kind,
            lifecycle=lifecycle,
            agent_backend=self.agent_backend,
            display_name=self.display_name,
            agent_thread_id=self.agent_thread_id,
            worktree_path=self.worktree_path,
            attachment=self.attachment,
            research_progress=self.research_progress,
            created_at=self.created_at,
            updated_at=now,
            archived_at=archived,
            id=self.id,
        )

    def with_attachment(self, attachment: SessionAttachment) -> Session:
        """Return a copy with updated attachment."""
        return Session(
            task_id=self.task_id,
            kind=self.kind,
            lifecycle=self.lifecycle,
            agent_backend=self.agent_backend,
            display_name=self.display_name,
            agent_thread_id=self.agent_thread_id,
            worktree_path=self.worktree_path,
            attachment=attachment,
            research_progress=self.research_progress,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
            archived_at=self.archived_at,
            id=self.id,
        )

    def with_research_progress(self, progress: ResearchProgress) -> Session:
        """Return a copy with updated research progress."""
        return Session(
            task_id=self.task_id,
            kind=self.kind,
            lifecycle=self.lifecycle,
            agent_backend=self.agent_backend,
            display_name=self.display_name,
            agent_thread_id=self.agent_thread_id,
            worktree_path=self.worktree_path,
            attachment=self.attachment,
            research_progress=progress,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
            archived_at=self.archived_at,
            id=self.id,
        )

    def with_worktree_path(self, path: str) -> Session:
        """Return a copy with updated worktree_path."""
        return Session(
            task_id=self.task_id,
            kind=self.kind,
            lifecycle=self.lifecycle,
            agent_backend=self.agent_backend,
            display_name=self.display_name,
            agent_thread_id=self.agent_thread_id,
            worktree_path=path,
            attachment=self.attachment,
            research_progress=self.research_progress,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
            archived_at=self.archived_at,
            id=self.id,
        )

    def to_doc(self) -> dict:
        doc: dict = {
            "task_id": self.task_id,
            "kind": self.kind.value,
            "lifecycle": self.lifecycle.value,
            "agent_backend": self.agent_backend,
            "display_name": self.display_name,
            "agent_thread_id": self.agent_thread_id,
            "worktree_path": self.worktree_path,
            "attachment": self.attachment.to_doc(),
            "research_progress": (
                self.research_progress.to_doc() if self.research_progress else None
            ),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "archived_at": self.archived_at,
        }
        if self.id:
            doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> Session:
        rp = doc.get("research_progress")
        return cls(
            id=str(doc["_id"]),
            task_id=doc["task_id"],
            kind=SessionKind(doc["kind"]),
            lifecycle=SessionLifecycle(doc["lifecycle"]),
            agent_backend=doc.get("agent_backend", ""),
            display_name=doc.get("display_name", ""),
            agent_thread_id=doc.get("agent_thread_id", ""),
            worktree_path=doc.get("worktree_path", ""),
            attachment=SessionAttachment.from_doc(doc.get("attachment", {})),
            research_progress=ResearchProgress.from_doc(rp) if rp else None,
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
            updated_at=doc.get("updated_at", datetime.now(timezone.utc)),
            archived_at=doc.get("archived_at"),
        )
