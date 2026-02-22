"""Merge record domain model — tracks session merges for rollback support."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class MergeRecord:
    """Record of a session branch merge into the main workspace."""

    session_id: str
    task_id: str
    branch_name: str
    merge_commit_sha: str
    reverted: bool = False
    revert_commit_sha: str = ""
    merged_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reverted_at: datetime | None = None
    id: str | None = None

    def to_doc(self) -> dict:
        doc: dict = {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "branch_name": self.branch_name,
            "merge_commit_sha": self.merge_commit_sha,
            "reverted": self.reverted,
            "revert_commit_sha": self.revert_commit_sha,
            "merged_at": self.merged_at,
            "reverted_at": self.reverted_at,
        }
        if self.id:
            doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> MergeRecord:
        return cls(
            id=str(doc["_id"]),
            session_id=doc["session_id"],
            task_id=doc["task_id"],
            branch_name=doc["branch_name"],
            merge_commit_sha=doc["merge_commit_sha"],
            reverted=doc.get("reverted", False),
            revert_commit_sha=doc.get("revert_commit_sha", ""),
            merged_at=doc.get("merged_at", datetime.now(timezone.utc)),
            reverted_at=doc.get("reverted_at"),
        )
