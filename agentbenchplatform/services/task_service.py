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

    async def add_dependency(self, task_slug: str, depends_on_slug: str) -> Task:
        """Add a dependency from task_slug -> depends_on_slug. Detects cycles."""
        task = await self._repo.find_by_slug(task_slug)
        if not task:
            raise ValueError(f"Task not found: {task_slug}")
        dep = await self._repo.find_by_slug(depends_on_slug)
        if not dep:
            raise ValueError(f"Dependency task not found: {depends_on_slug}")
        if task_slug == depends_on_slug:
            raise ValueError("A task cannot depend on itself")
        if depends_on_slug in task.depends_on:
            raise ValueError(f"Dependency already exists: {task_slug} -> {depends_on_slug}")

        # Cycle detection: check if depends_on_slug transitively depends on task_slug
        if await self._has_path(depends_on_slug, task_slug):
            raise ValueError(
                f"Adding dependency {task_slug} -> {depends_on_slug} would create a cycle"
            )

        new_deps = list(task.depends_on) + [depends_on_slug]
        updated = await self._repo.update(task_slug, {"depends_on": new_deps})
        if not updated:
            raise ValueError(f"Failed to update task: {task_slug}")
        logger.info("Added dependency: %s -> %s", task_slug, depends_on_slug)
        return updated

    async def remove_dependency(self, task_slug: str, depends_on_slug: str) -> Task:
        """Remove a dependency from task_slug -> depends_on_slug."""
        task = await self._repo.find_by_slug(task_slug)
        if not task:
            raise ValueError(f"Task not found: {task_slug}")
        if depends_on_slug not in task.depends_on:
            raise ValueError(f"Dependency not found: {task_slug} -> {depends_on_slug}")

        new_deps = [d for d in task.depends_on if d != depends_on_slug]
        updated = await self._repo.update(task_slug, {"depends_on": new_deps})
        if not updated:
            raise ValueError(f"Failed to update task: {task_slug}")
        logger.info("Removed dependency: %s -> %s", task_slug, depends_on_slug)
        return updated

    async def get_task_dependencies(self, task_slug: str) -> dict:
        """Get dependency info for a task: direct, transitive, and blocking deps."""
        task = await self._repo.find_by_slug(task_slug)
        if not task:
            raise ValueError(f"Task not found: {task_slug}")

        direct = list(task.depends_on)

        # Compute transitive closure via BFS
        transitive: list[str] = []
        visited = set(direct)
        queue = list(direct)
        while queue:
            slug = queue.pop(0)
            dep_task = await self._repo.find_by_slug(slug)
            if not dep_task:
                continue
            for upstream in dep_task.depends_on:
                if upstream not in visited:
                    visited.add(upstream)
                    transitive.append(upstream)
                    queue.append(upstream)

        # Blocking = deps that are not yet archived
        blocking: list[str] = []
        for slug in direct:
            dep_task = await self._repo.find_by_slug(slug)
            if dep_task and dep_task.status != TaskStatus.ARCHIVED:
                blocking.append(slug)

        return {"direct": direct, "transitive": transitive, "blocking": blocking}

    async def get_ready_tasks(self) -> list[Task]:
        """Get active tasks with all dependencies satisfied."""
        return await self._repo.find_ready_tasks()

    async def get_downstream_tasks(self, task_slug: str) -> list[Task]:
        """Get tasks that directly depend on the given task."""
        return await self._repo.find_dependents(task_slug)

    async def _has_path(self, from_slug: str, to_slug: str) -> bool:
        """Check if there's a dependency path from from_slug to to_slug (DFS)."""
        visited: set[str] = set()
        stack = [from_slug]
        while stack:
            current = stack.pop()
            if current == to_slug:
                return True
            if current in visited:
                continue
            visited.add(current)
            task = await self._repo.find_by_slug(current)
            if task:
                for dep in task.depends_on:
                    if dep not in visited:
                        stack.append(dep)
        return False
