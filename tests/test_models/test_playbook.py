"""Tests for Playbook model."""

from bson import ObjectId
from datetime import datetime, timezone

from agentbenchplatform.models.playbook import Playbook, PlaybookStep


class TestPlaybookStep:
    def test_create(self):
        step = PlaybookStep(action="create_task", params={"title": "Test"})
        assert step.action == "create_task"
        assert step.params == {"title": "Test"}

    def test_to_doc(self):
        step = PlaybookStep(action="start_session", params={"agent": "claude_code"})
        doc = step.to_doc()
        assert doc["action"] == "start_session"
        assert doc["params"]["agent"] == "claude_code"

    def test_from_doc(self):
        doc = {"action": "review_session", "params": {"test_command": "pytest"}}
        step = PlaybookStep.from_doc(doc)
        assert step.action == "review_session"
        assert step.params["test_command"] == "pytest"

    def test_default_params(self):
        step = PlaybookStep(action="merge_session")
        assert step.params == {}


class TestPlaybook:
    def test_create(self):
        steps = (
            PlaybookStep(action="create_task", params={"title": "Backend"}),
            PlaybookStep(action="start_session", params={"task_ref": 0}),
        )
        playbook = Playbook(name="test-playbook", description="A test", steps=steps)
        assert playbook.name == "test-playbook"
        assert len(playbook.steps) == 2

    def test_to_doc(self):
        steps = (PlaybookStep(action="create_task", params={"title": "Test"}),)
        playbook = Playbook(
            name="my-pb",
            description="desc",
            steps=steps,
            workspace_path="/tmp/ws",
            tags=("backend",),
        )
        doc = playbook.to_doc()
        assert doc["name"] == "my-pb"
        assert len(doc["steps"]) == 1
        assert doc["steps"][0]["action"] == "create_task"
        assert doc["tags"] == ["backend"]
        assert "_id" not in doc

    def test_from_doc(self):
        oid = ObjectId()
        doc = {
            "_id": oid,
            "name": "my-pb",
            "description": "desc",
            "steps": [
                {"action": "create_task", "params": {"title": "Test"}},
                {"action": "start_session", "params": {"task_ref": 0}},
            ],
            "workspace_path": "/tmp/ws",
            "tags": ["backend"],
            "created_at": datetime.now(timezone.utc),
        }
        playbook = Playbook.from_doc(doc)
        assert playbook.id == str(oid)
        assert playbook.name == "my-pb"
        assert len(playbook.steps) == 2
        assert playbook.steps[0].action == "create_task"
        assert playbook.tags == ("backend",)

    def test_roundtrip(self):
        steps = (
            PlaybookStep(action="create_task", params={"title": "Test"}),
            PlaybookStep(action="merge_session", params={"task_ref": 0}),
        )
        playbook = Playbook(name="roundtrip", steps=steps)
        doc = playbook.to_doc()
        doc["_id"] = ObjectId()
        restored = Playbook.from_doc(doc)
        assert restored.name == playbook.name
        assert len(restored.steps) == len(playbook.steps)
        assert restored.steps[0].action == "create_task"

    def test_backward_compat(self):
        """Old documents without optional fields should deserialize."""
        oid = ObjectId()
        doc = {
            "_id": oid,
            "name": "old-pb",
        }
        playbook = Playbook.from_doc(doc)
        assert playbook.description == ""
        assert playbook.steps == ()
        assert playbook.tags == ()
