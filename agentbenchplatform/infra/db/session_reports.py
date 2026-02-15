"""Session report repository - MongoDB CRUD."""

from __future__ import annotations

import logging

from agentbenchplatform.models.session_report import SessionReport

logger = logging.getLogger(__name__)


class SessionReportRepo:
    """CRUD operations for session reports in MongoDB."""

    COLLECTION = "session_reports"

    def __init__(self, db) -> None:
        self._col = db[self.COLLECTION]

    async def insert(self, report: SessionReport) -> SessionReport:
        """Insert a new session report. Returns report with assigned id."""
        doc = report.to_doc()
        doc.pop("_id", None)
        result = await self._col.insert_one(doc)
        return SessionReport(
            id=str(result.inserted_id),
            session_id=report.session_id,
            task_id=report.task_id,
            agent=report.agent,
            status=report.status,
            summary=report.summary,
            files_changed=report.files_changed,
            test_results=report.test_results,
            diff_stats=report.diff_stats,
            agent_notes=report.agent_notes,
            created_at=report.created_at,
        )

    async def find_by_session(self, session_id: str) -> SessionReport | None:
        """Find a report by session ID."""
        doc = await self._col.find_one({"session_id": session_id})
        return SessionReport.from_doc(doc) if doc else None

    async def list_by_task(self, task_id: str, limit: int = 20) -> list[SessionReport]:
        """List reports for a task, most recent first."""
        cursor = (
            self._col.find({"task_id": task_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        return [SessionReport.from_doc(doc) async for doc in cursor]

    async def list_recent(self, limit: int = 10) -> list[SessionReport]:
        """List most recent reports across all tasks."""
        cursor = self._col.find().sort("created_at", -1).limit(limit)
        return [SessionReport.from_doc(doc) async for doc in cursor]
