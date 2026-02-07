"""Usage repository - MongoDB CRUD for token usage events."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from agentbenchplatform.models.usage import UsageEvent

logger = logging.getLogger(__name__)


class UsageRepo:
    """CRUD and aggregation operations for usage events in MongoDB."""

    COLLECTION = "usage_events"

    def __init__(self, db) -> None:
        self._col = db[self.COLLECTION]

    async def insert(self, event: UsageEvent) -> UsageEvent:
        """Insert a new usage event. Returns event with assigned id."""
        doc = event.to_doc()
        doc.pop("_id", None)
        result = await self._col.insert_one(doc)
        return UsageEvent(
            id=str(result.inserted_id),
            source=event.source,
            model=event.model,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            task_id=event.task_id,
            session_id=event.session_id,
            channel=event.channel,
            timestamp=event.timestamp,
        )

    async def list_by_source(
        self, source: str, limit: int = 50
    ) -> list[UsageEvent]:
        """List usage events by source, most recent first."""
        cursor = (
            self._col.find({"source": source})
            .sort("timestamp", -1)
            .limit(limit)
        )
        return [UsageEvent.from_doc(doc) async for doc in cursor]

    async def list_recent(self, limit: int = 20) -> list[UsageEvent]:
        """List most recent usage events across all sources."""
        cursor = self._col.find().sort("timestamp", -1).limit(limit)
        return [UsageEvent.from_doc(doc) async for doc in cursor]

    async def aggregate_by_task(self, task_id: str) -> dict:
        """Sum input/output tokens grouped by source for a task."""
        pipeline = [
            {"$match": {"task_id": task_id}},
            {
                "$group": {
                    "_id": "$source",
                    "input_tokens": {"$sum": "$input_tokens"},
                    "output_tokens": {"$sum": "$output_tokens"},
                    "count": {"$sum": 1},
                }
            },
        ]
        result = {}
        async for doc in self._col.aggregate(pipeline):
            result[doc["_id"]] = {
                "input_tokens": doc["input_tokens"],
                "output_tokens": doc["output_tokens"],
                "count": doc["count"],
            }
        return result

    async def aggregate_recent(self, hours: int = 6) -> dict:
        """Sums grouped by source and model within a recent time window."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        pipeline = [
            {"$match": {"timestamp": {"$gte": cutoff}}},
            {
                "$group": {
                    "_id": {"source": "$source", "model": "$model"},
                    "input_tokens": {"$sum": "$input_tokens"},
                    "output_tokens": {"$sum": "$output_tokens"},
                    "count": {"$sum": 1},
                }
            },
        ]
        result = {}
        async for doc in self._col.aggregate(pipeline):
            key = f"{doc['_id']['source']}:{doc['_id']['model']}"
            result[key] = {
                "input_tokens": doc["input_tokens"],
                "output_tokens": doc["output_tokens"],
                "count": doc["count"],
            }
        return result

    async def aggregate_totals(self) -> dict:
        """Global sums grouped by source and model."""
        pipeline = [
            {
                "$group": {
                    "_id": {"source": "$source", "model": "$model"},
                    "input_tokens": {"$sum": "$input_tokens"},
                    "output_tokens": {"$sum": "$output_tokens"},
                    "count": {"$sum": 1},
                }
            },
        ]
        result = {}
        async for doc in self._col.aggregate(pipeline):
            key = f"{doc['_id']['source']}:{doc['_id']['model']}"
            result[key] = {
                "input_tokens": doc["input_tokens"],
                "output_tokens": doc["output_tokens"],
                "count": doc["count"],
            }
        return result
