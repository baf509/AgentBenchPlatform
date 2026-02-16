"""Tests for TaskService with mocked repo."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agentbenchplatform.models.task import Task, TaskStatus
from agentbenchplatform.services.task_service import TaskService


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    return repo


@pytest.fixture
def service(mock_repo):
    return TaskService(mock_repo)


class TestTaskService:
    @pytest.mark.asyncio
    async def test_create_task(self, service, mock_repo):
        mock_repo.find_by_slug.return_value = None
        mock_repo.insert.return_value = Task(
            slug="fix-auth", title="Fix Auth", id="abc123"
        )
        task = await service.create_task("Fix Auth")
        assert task.slug == "fix-auth"
        mock_repo.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self, service, mock_repo):
        mock_repo.find_by_slug.return_value = Task(
            slug="fix-auth", title="Fix Auth"
        )
        with pytest.raises(ValueError, match="already exists"):
            await service.create_task("Fix Auth")

    @pytest.mark.asyncio
    async def test_get_task(self, service, mock_repo):
        mock_repo.find_by_slug.return_value = Task(
            slug="fix-auth", title="Fix Auth"
        )
        task = await service.get_task("fix-auth")
        assert task is not None
        assert task.slug == "fix-auth"

    @pytest.mark.asyncio
    async def test_list_tasks(self, service, mock_repo):
        mock_repo.list_tasks.return_value = [
            Task(slug="a", title="A"),
            Task(slug="b", title="B"),
        ]
        tasks = await service.list_tasks()
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_archive_task(self, service, mock_repo):
        mock_repo.update_status.return_value = Task(
            slug="fix-auth", title="Fix Auth",
            status=TaskStatus.ARCHIVED,
        )
        task = await service.archive_task("fix-auth")
        assert task.status == TaskStatus.ARCHIVED

    @pytest.mark.asyncio
    async def test_delete_task(self, service, mock_repo):
        mock_repo.update_status.return_value = Task(
            slug="fix-auth", title="Fix Auth",
            status=TaskStatus.DELETED,
        )
        task = await service.delete_task("fix-auth")
        assert task.status == TaskStatus.DELETED
