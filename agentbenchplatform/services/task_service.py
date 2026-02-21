"""Task business logic service."""

from __future__ import annotations

import logging

from agentbenchplatform.infra.db.tasks import TaskRepo
from agentbenchplatform.models.task import Task, TaskStatus

logger = logging.getLogger(__name__)


class TaskService:
    """Business logic for task management."""

    def __init__(self, task_repo: TaskRepo) -> None:
        self._repo = task_repo

    async def create_task(
        self,
        title: str,
        description: str = "",
        workspace_path: str = "",
        tags: tuple[str, ...] = (),
        complexity: str = "",
    ) -> Task:
        """Create a new task."""
        task = Task.create(
            title=title,
            description=description,
            workspace_path=workspace_path,
            tags=tags,
            complexity=complexity,
        )

        existing = await self._repo.find_by_slug(task.slug)
        if existing:
            raise ValueError(f"Task with slug '{task.slug}' already exists")

        created = await self._repo.insert(task)
        logger.info("Created task: %s (%s)", created.title, created.slug)
        return created

    async def get_task(self, slug: str) -> Task | None:
        """Get a task by slug."""
        return await self._repo.find_by_slug(slug)

    async def get_task_by_id(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return await self._repo.find_by_id(task_id)

    async def list_tasks(
        self,
        show_all: bool = False,
        archived: bool = False,
    ) -> list[Task]:
        """List tasks."""
        if archived:
            return await self._repo.list_tasks(status=TaskStatus.ARCHIVED)
        return await self._repo.list_tasks(include_archived=show_all)

    async def archive_task(self, slug: str) -> Task | None:
        """Archive a task."""
        task = await self._repo.update_status(slug, TaskStatus.ARCHIVED)
        if task:
            logger.info("Archived task: %s", slug)
        return task

    async def update_task(
        self,
        slug: str,
        description: str | None = None,
        workspace_path: str | None = None,
        tags: tuple[str, ...] | None = None,
        complexity: str | None = None,
    ) -> Task | None:
        """Update task fields. Only non-None values are applied."""
        updates: dict = {}
        if description is not None:
            updates["description"] = description
        if workspace_path is not None:
            updates["workspace_path"] = workspace_path
        if tags is not None:
            updates["tags"] = list(tags)
        if complexity is not None:
            updates["complexity"] = complexity
        if not updates:
            return await self._repo.find_by_slug(slug)
        task = await self._repo.update(slug, updates)
        if task:
            logger.info("Updated task: %s (fields: %s)", slug, list(updates.keys()))
        return task

    async def delete_task(self, slug: str) -> Task | None:
        """Soft-delete a task."""
        task = await self._repo.update_status(slug, TaskStatus.DELETED)
        if task:
            logger.info("Deleted task: %s", slug)
        return task
