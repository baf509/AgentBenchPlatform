"""Workspace repository - MongoDB CRUD for standalone workspaces."""

from __future__ import annotations

import logging

from bson import ObjectId
from bson.errors import InvalidId

from agentbenchplatform.models.workspace import Workspace

logger = logging.getLogger(__name__)


class WorkspaceRepo:
    """CRUD operations for workspaces in MongoDB."""

    COLLECTION = "workspaces"

    def __init__(self, db) -> None:
        self._col = db[self.COLLECTION]

    async def insert(self, workspace: Workspace) -> Workspace:
        """Insert a new workspace. Returns workspace with assigned id."""
        doc = workspace.to_doc()
        doc.pop("_id", None)
        result = await self._col.insert_one(doc)
        return Workspace(
            id=str(result.inserted_id),
            path=workspace.path,
            name=workspace.name,
            created_at=workspace.created_at,
        )

    async def list_all(self) -> list[Workspace]:
        """List all workspaces, most recent first."""
        cursor = self._col.find().sort("created_at", -1)
        return [Workspace.from_doc(doc) async for doc in cursor]

    async def find_by_path(self, path: str) -> Workspace | None:
        """Find a workspace by its filesystem path."""
        doc = await self._col.find_one({"path": path})
        return Workspace.from_doc(doc) if doc else None

    async def delete(self, workspace_id: str) -> bool:
        """Delete a workspace by ID."""
        try:
            result = await self._col.delete_one({"_id": ObjectId(workspace_id)})
            return result.deleted_count > 0
        except InvalidId:
            logger.debug("Invalid ObjectId: %s", workspace_id)
            return False
