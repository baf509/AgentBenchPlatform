"""Session report domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class TestResults:
    """Test execution results."""

    passed: int = 0
    failed: int = 0
    errors: int = 0
    output_snippet: str = ""

    def to_doc(self) -> dict:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "output_snippet": self.output_snippet,
        }

    @classmethod
    def from_doc(cls, doc: dict) -> TestResults:
        return cls(
            passed=doc.get("passed", 0),
            failed=doc.get("failed", 0),
            errors=doc.get("errors", 0),
            output_snippet=doc.get("output_snippet", ""),
        )


@dataclass(frozen=True)
class DiffStats:
    """Git diff statistics."""

    insertions: int = 0
    deletions: int = 0
    files: int = 0

    def to_doc(self) -> dict:
        return {
            "insertions": self.insertions,
            "deletions": self.deletions,
            "files": self.files,
        }

    @classmethod
    def from_doc(cls, doc: dict) -> DiffStats:
        return cls(
            insertions=doc.get("insertions", 0),
            deletions=doc.get("deletions", 0),
            files=doc.get("files", 0),
        )


@dataclass(frozen=True)
class SessionReport:
    """Structured report of a session's work output."""

    session_id: str
    task_id: str
    agent: str
    status: str  # "success", "partial", "failed"
    summary: str = ""
    files_changed: tuple[str, ...] = ()
    test_results: TestResults | None = None
    diff_stats: DiffStats | None = None
    agent_notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str | None = None

    def to_doc(self) -> dict:
        doc: dict = {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "agent": self.agent,
            "status": self.status,
            "summary": self.summary,
            "files_changed": list(self.files_changed),
            "test_results": self.test_results.to_doc() if self.test_results else None,
            "diff_stats": self.diff_stats.to_doc() if self.diff_stats else None,
            "agent_notes": self.agent_notes,
            "created_at": self.created_at,
        }
        if self.id:
            doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> SessionReport:
        tr = doc.get("test_results")
        ds = doc.get("diff_stats")
        return cls(
            id=str(doc["_id"]),
            session_id=doc["session_id"],
            task_id=doc["task_id"],
            agent=doc.get("agent", ""),
            status=doc.get("status", "unknown"),
            summary=doc.get("summary", ""),
            files_changed=tuple(doc.get("files_changed", [])),
            test_results=TestResults.from_doc(tr) if tr else None,
            diff_stats=DiffStats.from_doc(ds) if ds else None,
            agent_notes=doc.get("agent_notes", ""),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
        )
