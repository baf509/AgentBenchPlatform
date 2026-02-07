"""Tests for DashboardService."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agentbenchplatform.models.session import Session, SessionKind, SessionLifecycle
from agentbenchplatform.models.task import Task, TaskStatus
from agentbenchplatform.services.dashboard_service import DashboardService, DashboardSnapshot


@pytest.fixture
def mock_task_repo():
    return AsyncMock()


@pytest.fixture
def mock_session_repo():
    return AsyncMock()


@pytest.fixture
def service(mock_task_repo, mock_session_repo):
    return DashboardService(mock_task_repo, mock_session_repo)


class TestDashboardService:
    @pytest.mark.asyncio
    async def test_load_snapshot_empty(self, service, mock_task_repo):
        mock_task_repo.list_tasks.return_value = []
        snapshot = await service.load_snapshot()
        assert isinstance(snapshot, DashboardSnapshot)
        assert len(snapshot.tasks) == 0
        assert snapshot.total_running == 0

    @pytest.mark.asyncio
    async def test_load_snapshot_with_data(
        self, service, mock_task_repo, mock_session_repo
    ):
        mock_task_repo.list_tasks.return_value = [
            Task(slug="fix-auth", title="Fix Auth", id="t1"),
        ]
        mock_session_repo.list_by_task.return_value = [
            Session(
                task_id="t1", kind=SessionKind.CODING_AGENT,
                lifecycle=SessionLifecycle.RUNNING, id="s1",
            ),
            Session(
                task_id="t1", kind=SessionKind.CODING_AGENT,
                lifecycle=SessionLifecycle.COMPLETED, id="s2",
            ),
        ]
        snapshot = await service.load_snapshot()
        assert len(snapshot.tasks) == 1
        assert snapshot.total_running == 1
        assert snapshot.total_sessions == 2
        assert snapshot.active_task_count == 1

    def test_summary_text(self):
        snapshot = DashboardSnapshot(
            tasks=[], total_running=0, total_sessions=0,
        )
        text = snapshot.summary_text()
        assert "System snapshot" in text
        assert "0 active tasks" in text
