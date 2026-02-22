"""Tests for SessionMetric model."""

from bson import ObjectId
from datetime import datetime, timezone

from agentbenchplatform.models.session_metric import SessionMetric


class TestSessionMetric:
    def test_create(self):
        metric = SessionMetric(
            session_id="sess-1",
            task_id="task-1",
            agent_backend="opencode_local",
            complexity="junior",
            status="success",
            duration_seconds=120,
        )
        assert metric.session_id == "sess-1"
        assert metric.duration_seconds == 120

    def test_to_doc(self):
        metric = SessionMetric(
            session_id="sess-1",
            task_id="task-1",
            agent_backend="opencode_local",
            duration_seconds=300,
        )
        doc = metric.to_doc()
        assert doc["session_id"] == "sess-1"
        assert doc["duration_seconds"] == 300
        assert "_id" not in doc

    def test_from_doc(self):
        oid = ObjectId()
        doc = {
            "_id": oid,
            "session_id": "sess-1",
            "task_id": "task-1",
            "agent_backend": "claude_code",
            "complexity": "senior",
            "status": "success",
            "duration_seconds": 600,
            "created_at": datetime.now(timezone.utc),
        }
        metric = SessionMetric.from_doc(doc)
        assert metric.id == str(oid)
        assert metric.agent_backend == "claude_code"
        assert metric.complexity == "senior"
        assert metric.duration_seconds == 600

    def test_roundtrip(self):
        metric = SessionMetric(
            session_id="sess-1",
            task_id="task-1",
            agent_backend="opencode",
            complexity="mid",
            duration_seconds=450,
        )
        doc = metric.to_doc()
        doc["_id"] = ObjectId()
        restored = SessionMetric.from_doc(doc)
        assert restored.session_id == metric.session_id
        assert restored.duration_seconds == metric.duration_seconds
        assert restored.complexity == metric.complexity

    def test_backward_compat(self):
        """Old documents without optional fields should deserialize."""
        oid = ObjectId()
        doc = {
            "_id": oid,
            "session_id": "sess-1",
            "task_id": "task-1",
            "agent_backend": "opencode",
        }
        metric = SessionMetric.from_doc(doc)
        assert metric.complexity == ""
        assert metric.status == "success"
        assert metric.duration_seconds == 0
