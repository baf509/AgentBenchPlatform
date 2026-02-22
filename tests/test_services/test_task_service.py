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


class TestTaskDependencies:
    @pytest.mark.asyncio
    async def test_add_dependency(self, service, mock_repo):
        mock_repo.find_by_slug.side_effect = lambda slug: {
            "child": Task(slug="child", title="Child"),
            "parent": Task(slug="parent", title="Parent"),
        }.get(slug)
        mock_repo.update.return_value = Task(
            slug="child", title="Child", depends_on=("parent",),
        )
        task = await service.add_dependency("child", "parent")
        assert "parent" in task.depends_on

    @pytest.mark.asyncio
    async def test_add_dependency_self_raises(self, service, mock_repo):
        mock_repo.find_by_slug.return_value = Task(slug="task", title="Task")
        with pytest.raises(ValueError, match="cannot depend on itself"):
            await service.add_dependency("task", "task")

    @pytest.mark.asyncio
    async def test_add_dependency_not_found_raises(self, service, mock_repo):
        mock_repo.find_by_slug.return_value = None
        with pytest.raises(ValueError, match="not found"):
            await service.add_dependency("child", "parent")

    @pytest.mark.asyncio
    async def test_add_duplicate_dependency_raises(self, service, mock_repo):
        mock_repo.find_by_slug.side_effect = lambda slug: {
            "child": Task(slug="child", title="Child", depends_on=("parent",)),
            "parent": Task(slug="parent", title="Parent"),
        }.get(slug)
        with pytest.raises(ValueError, match="already exists"):
            await service.add_dependency("child", "parent")

    @pytest.mark.asyncio
    async def test_cycle_detection(self, service, mock_repo):
        """A -> B -> C, adding C -> A should fail."""
        mock_repo.find_by_slug.side_effect = lambda slug: {
            "a": Task(slug="a", title="A"),
            "b": Task(slug="b", title="B", depends_on=("a",)),
            "c": Task(slug="c", title="C", depends_on=("b",)),
        }.get(slug)
        with pytest.raises(ValueError, match="cycle"):
            await service.add_dependency("a", "c")

    @pytest.mark.asyncio
    async def test_remove_dependency(self, service, mock_repo):
        mock_repo.find_by_slug.return_value = Task(
            slug="child", title="Child", depends_on=("parent",),
        )
        mock_repo.update.return_value = Task(
            slug="child", title="Child", depends_on=(),
        )
        task = await service.remove_dependency("child", "parent")
        assert "parent" not in task.depends_on

    @pytest.mark.asyncio
    async def test_remove_nonexistent_dependency_raises(self, service, mock_repo):
        mock_repo.find_by_slug.return_value = Task(
            slug="child", title="Child", depends_on=(),
        )
        with pytest.raises(ValueError, match="not found"):
            await service.remove_dependency("child", "parent")

    @pytest.mark.asyncio
    async def test_get_task_dependencies(self, service, mock_repo):
        mock_repo.find_by_slug.side_effect = lambda slug: {
            "c": Task(slug="c", title="C", depends_on=("b",)),
            "b": Task(slug="b", title="B", depends_on=("a",), status=TaskStatus.ACTIVE),
            "a": Task(slug="a", title="A", status=TaskStatus.ARCHIVED),
        }.get(slug)
        deps = await service.get_task_dependencies("c")
        assert deps["direct"] == ["b"]
        assert "a" in deps["transitive"]
        assert "b" in deps["blocking"]  # b is ACTIVE, not ARCHIVED

    @pytest.mark.asyncio
    async def test_get_ready_tasks(self, service, mock_repo):
        mock_repo.find_ready_tasks.return_value = [
            Task(slug="ready", title="Ready"),
        ]
        tasks = await service.get_ready_tasks()
        assert len(tasks) == 1
        assert tasks[0].slug == "ready"

    @pytest.mark.asyncio
    async def test_get_downstream_tasks(self, service, mock_repo):
        mock_repo.find_dependents.return_value = [
            Task(slug="downstream", title="Downstream", depends_on=("parent",)),
        ]
        tasks = await service.get_downstream_tasks("parent")
        assert len(tasks) == 1
        assert tasks[0].slug == "downstream"
