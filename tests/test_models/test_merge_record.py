"""Tests for MergeRecord model."""

from bson import ObjectId
from datetime import datetime, timezone

from agentbenchplatform.models.merge_record import MergeRecord


class TestMergeRecord:
    def test_create(self):
        record = MergeRecord(
            session_id="sess-1",
            task_id="task-1",
            branch_name="abp/sess-1",
            merge_commit_sha="abc123",
        )
        assert record.session_id == "sess-1"
        assert record.reverted is False
        assert record.revert_commit_sha == ""

    def test_to_doc(self):
        record = MergeRecord(
            session_id="sess-1",
            task_id="task-1",
            branch_name="abp/sess-1",
            merge_commit_sha="abc123",
        )
        doc = record.to_doc()
        assert doc["session_id"] == "sess-1"
        assert doc["merge_commit_sha"] == "abc123"
        assert doc["reverted"] is False
        assert "_id" not in doc

    def test_to_doc_with_id(self):
        record = MergeRecord(
            session_id="sess-1",
            task_id="task-1",
            branch_name="abp/sess-1",
            merge_commit_sha="abc123",
            id="myid",
        )
        doc = record.to_doc()
        assert doc["_id"] == "myid"

    def test_from_doc(self):
        oid = ObjectId()
        doc = {
            "_id": oid,
            "session_id": "sess-1",
            "task_id": "task-1",
            "branch_name": "abp/sess-1",
            "merge_commit_sha": "abc123",
            "reverted": True,
            "revert_commit_sha": "def456",
            "merged_at": datetime.now(timezone.utc),
            "reverted_at": datetime.now(timezone.utc),
        }
        record = MergeRecord.from_doc(doc)
        assert record.id == str(oid)
        assert record.session_id == "sess-1"
        assert record.reverted is True
        assert record.revert_commit_sha == "def456"

    def test_roundtrip(self):
        record = MergeRecord(
            session_id="sess-1",
            task_id="task-1",
            branch_name="abp/sess-1",
            merge_commit_sha="abc123",
        )
        doc = record.to_doc()
        doc["_id"] = ObjectId()
        restored = MergeRecord.from_doc(doc)
        assert restored.session_id == record.session_id
        assert restored.merge_commit_sha == record.merge_commit_sha

    def test_backward_compat(self):
        """Old documents without reverted fields should deserialize."""
        oid = ObjectId()
        doc = {
            "_id": oid,
            "session_id": "sess-1",
            "task_id": "task-1",
            "branch_name": "abp/sess-1",
            "merge_commit_sha": "abc123",
        }
        record = MergeRecord.from_doc(doc)
        assert record.reverted is False
        assert record.revert_commit_sha == ""
        assert record.reverted_at is None
