"""Task repository - MongoDB CRUD for tasks."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from agentbenchplatform.models.task import Task, TaskStatus

logger = logging.getLogger(__name__)


class TaskRepo:
    """CRUD operations for tasks in MongoDB."""

    COLLECTION = "tasks"

    def __init__(self, db) -> None:
        self._col = db[self.COLLECTION]

    async def insert(self, task: Task) -> Task:
        """Insert a new task. Returns task with assigned id."""
        doc = task.to_doc()
        doc.pop("_id", None)
        result = await self._col.insert_one(doc)
        return Task(
            id=str(result.inserted_id),
            slug=task.slug,
            title=task.title,
            status=task.status,
            description=task.description,
            workspace_path=task.workspace_path,
            tags=task.tags,
            complexity=task.complexity,
            depends_on=task.depends_on,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    async def find_by_slug(self, slug: str) -> Task | None:
        """Find a task by slug."""
        doc = await self._col.find_one({"slug": slug})
        return Task.from_doc(doc) if doc else None

    async def find_by_id(self, task_id: str) -> Task | None:
        """Find a task by ID."""
        try:
            doc = await self._col.find_one({"_id": ObjectId(task_id)})
            return Task.from_doc(doc) if doc else None
        except InvalidId:
            logger.debug("Invalid ObjectId: %s", task_id)
            return None

    async def list_tasks(
        self,
        status: TaskStatus | None = None,
        include_archived: bool = False,
    ) -> list[Task]:
        """List tasks, optionally filtered by status."""
        query: dict = {}
        if status:
            query["status"] = status.value
        elif not include_archived:
            query["status"] = {"$ne": TaskStatus.DELETED.value}
        cursor = self._col.find(query).sort("created_at", -1)
        return [Task.from_doc(doc) async for doc in cursor]

    async def update_status(self, slug: str, status: TaskStatus) -> Task | None:
        """Update a task's status by slug."""
        now = datetime.now(timezone.utc)
        result = await self._col.find_one_and_update(
            {"slug": slug},
            {"$set": {"status": status.value, "updated_at": now}},
            return_document=True,
        )
        return Task.from_doc(result) if result else None

    async def update(self, slug: str, updates: dict) -> Task | None:
        """Update arbitrary fields on a task."""
        updates["updated_at"] = datetime.now(timezone.utc)
        result = await self._col.find_one_and_update(
            {"slug": slug},
            {"$set": updates},
            return_document=True,
        )
        return Task.from_doc(result) if result else None

    async def delete(self, slug: str) -> bool:
        """Permanently delete a task by slug."""
        result = await self._col.delete_one({"slug": slug})
        return result.deleted_count > 0

    async def find_dependents(self, slug: str) -> list[Task]:
        """Find tasks that depend on the given task slug."""
        cursor = self._col.find({"depends_on": slug})
        return [Task.from_doc(doc) async for doc in cursor]

    async def find_ready_tasks(self) -> list[Task]:
        """Find active tasks whose dependencies are all satisfied (archived)."""
        # Get all active tasks that have dependencies
        cursor = self._col.find({
            "status": TaskStatus.ACTIVE.value,
            "depends_on": {"$exists": True, "$ne": []},
        })
        candidates = [Task.from_doc(doc) async for doc in cursor]

        # Also get active tasks with no dependencies
        cursor2 = self._col.find({
            "status": TaskStatus.ACTIVE.value,
            "$or": [
                {"depends_on": {"$exists": False}},
                {"depends_on": []},
            ],
        })
        no_deps = [Task.from_doc(doc) async for doc in cursor2]

        # Check each candidate's deps are all archived
        ready = list(no_deps)
        for task in candidates:
            all_satisfied = True
            for dep_slug in task.depends_on:
                dep = await self.find_by_slug(dep_slug)
                if not dep or dep.status != TaskStatus.ARCHIVED:
                    all_satisfied = False
                    break
            if all_satisfied:
                ready.append(task)

        return ready
