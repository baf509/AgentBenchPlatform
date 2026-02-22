"""Session metric repository - MongoDB CRUD and aggregation."""

from __future__ import annotations

import logging

from agentbenchplatform.models.session_metric import SessionMetric

logger = logging.getLogger(__name__)


class SessionMetricRepo:
    """CRUD and aggregation for session duration metrics."""

    COLLECTION = "session_metrics"

    def __init__(self, db) -> None:
        self._col = db[self.COLLECTION]

    async def insert(self, metric: SessionMetric) -> SessionMetric:
        """Insert a new session metric."""
        doc = metric.to_doc()
        doc.pop("_id", None)
        result = await self._col.insert_one(doc)
        return SessionMetric(
            id=str(result.inserted_id),
            session_id=metric.session_id,
            task_id=metric.task_id,
            agent_backend=metric.agent_backend,
            complexity=metric.complexity,
            status=metric.status,
            duration_seconds=metric.duration_seconds,
            created_at=metric.created_at,
        )

    async def find_by_session(self, session_id: str) -> SessionMetric | None:
        """Find a metric by session ID."""
        doc = await self._col.find_one({"session_id": session_id})
        return SessionMetric.from_doc(doc) if doc else None

    async def get_stats(
        self, agent: str | None = None, complexity: str | None = None
    ) -> dict:
        """Get aggregated stats (avg, count, p90) with optional filters."""
        query: dict = {}
        if agent:
            query["agent_backend"] = agent
        if complexity:
            query["complexity"] = complexity

        # MongoDB aggregation for avg and count
        pipeline: list[dict] = []
        if query:
            pipeline.append({"$match": query})
        pipeline.append({
            "$group": {
                "_id": None,
                "avg_seconds": {"$avg": "$duration_seconds"},
                "sample_count": {"$sum": 1},
                "durations": {"$push": "$duration_seconds"},
            }
        })

        results = []
        async for doc in self._col.aggregate(pipeline):
            results.append(doc)

        if not results:
            return {"avg_seconds": 0, "sample_count": 0, "p90_seconds": 0}

        stats = results[0]
        durations = sorted(stats.get("durations", []))
        sample_count = stats.get("sample_count", 0)

        # Compute p90 in Python
        p90 = 0
        if durations:
            idx = int(len(durations) * 0.9)
            idx = min(idx, len(durations) - 1)
            p90 = durations[idx]

        return {
            "avg_seconds": int(stats.get("avg_seconds", 0)),
            "sample_count": sample_count,
            "p90_seconds": p90,
        }
