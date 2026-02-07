"""Tests for Task model."""

import pytest
from datetime import datetime, timezone

from agentbenchplatform.models.task import Task, TaskStatus, _slugify


class TestSlugify:
    def test_basic(self):
        assert _slugify("Fix Auth Bug") == "fix-auth-bug"

    def test_special_chars(self):
        assert _slugify("Hello, World!") == "hello-world"

    def test_multiple_spaces(self):
        assert _slugify("fix   the   bug") == "fix-the-bug"

    def test_underscores(self):
        assert _slugify("fix_the_bug") == "fix-the-bug"

    def test_leading_trailing(self):
        assert _slugify("  fix auth  ") == "fix-auth"


class TestTask:
    def test_create(self):
        task = Task.create("Fix Auth Bug", description="Fix the auth issue")
        assert task.slug == "fix-auth-bug"
        assert task.title == "Fix Auth Bug"
        assert task.status == TaskStatus.ACTIVE
        assert task.description == "Fix the auth issue"

    def test_create_with_tags(self):
        task = Task.create("Fix Auth", tags=("backend", "urgent"))
        assert task.tags == ("backend", "urgent")

    def test_empty_slug_raises(self):
        with pytest.raises(ValueError, match="slug cannot be empty"):
            Task(slug="", title="Test")

    def test_empty_title_raises(self):
        with pytest.raises(ValueError, match="title cannot be empty"):
            Task(slug="test", title="")

    def test_create_from_unparseable_title(self):
        with pytest.raises(ValueError, match="Cannot generate slug"):
            Task.create("!!!")

    def test_with_status(self):
        task = Task.create("Fix Auth")
        archived = task.with_status(TaskStatus.ARCHIVED)
        assert archived.status == TaskStatus.ARCHIVED
        assert archived.slug == task.slug
        assert archived.title == task.title
        # Original unchanged (frozen)
        assert task.status == TaskStatus.ACTIVE

    def test_frozen(self):
        task = Task.create("Fix Auth")
        with pytest.raises(AttributeError):
            task.slug = "changed"  # type: ignore

    def test_to_doc(self):
        task = Task.create("Fix Auth")
        doc = task.to_doc()
        assert doc["slug"] == "fix-auth"
        assert doc["title"] == "Fix Auth"
        assert doc["status"] == "active"
        assert "_id" not in doc  # no id yet

    def test_to_doc_with_id(self):
        task = Task(slug="test", title="Test", id="abc123")
        doc = task.to_doc()
        assert doc["_id"] == "abc123"

    def test_from_doc(self):
        from bson import ObjectId

        oid = ObjectId()
        doc = {
            "_id": oid,
            "slug": "fix-auth",
            "title": "Fix Auth",
            "status": "active",
            "description": "desc",
            "workspace_path": "/tmp",
            "tags": ["backend"],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        task = Task.from_doc(doc)
        assert task.id == str(oid)
        assert task.slug == "fix-auth"
        assert task.tags == ("backend",)

    def test_roundtrip(self):
        from bson import ObjectId

        task = Task.create("Roundtrip Test")
        doc = task.to_doc()
        doc["_id"] = ObjectId()
        restored = Task.from_doc(doc)
        assert restored.slug == task.slug
        assert restored.title == task.title
        assert restored.status == task.status
