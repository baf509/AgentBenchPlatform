"""Playbook repository - MongoDB CRUD."""

from __future__ import annotations

import logging

from agentbenchplatform.models.playbook import Playbook

logger = logging.getLogger(__name__)


class PlaybookRepo:
    """CRUD operations for playbooks in MongoDB."""

    COLLECTION = "playbooks"

    def __init__(self, db) -> None:
        self._col = db[self.COLLECTION]

    async def insert(self, playbook: Playbook) -> Playbook:
        """Insert a new playbook."""
        doc = playbook.to_doc()
        doc.pop("_id", None)
        result = await self._col.insert_one(doc)
        return Playbook(
            id=str(result.inserted_id),
            name=playbook.name,
            description=playbook.description,
            steps=playbook.steps,
            workspace_path=playbook.workspace_path,
            tags=playbook.tags,
            created_at=playbook.created_at,
        )

    async def find_by_name(self, name: str) -> Playbook | None:
        """Find a playbook by name."""
        doc = await self._col.find_one({"name": name})
        return Playbook.from_doc(doc) if doc else None

    async def list_all(self) -> list[Playbook]:
        """List all playbooks."""
        cursor = self._col.find().sort("created_at", -1)
        return [Playbook.from_doc(doc) async for doc in cursor]

    async def delete(self, name: str) -> bool:
        """Delete a playbook by name."""
        result = await self._col.delete_one({"name": name})
        return result.deleted_count > 0
