"""Tests for Session model."""

import pytest

from agentbenchplatform.models.session import (
    ResearchProgress,
    Session,
    SessionAttachment,
    SessionKind,
    SessionLifecycle,
)


class TestSessionLifecycle:
    def test_terminal_states(self):
        assert SessionLifecycle.COMPLETED.is_terminal
        assert SessionLifecycle.FAILED.is_terminal
        assert SessionLifecycle.ARCHIVED.is_terminal

    def test_non_terminal_states(self):
        assert not SessionLifecycle.PENDING.is_terminal
        assert not SessionLifecycle.RUNNING.is_terminal
        assert not SessionLifecycle.PAUSED.is_terminal


class TestSession:
    def test_create(self):
        session = Session(task_id="task1", kind=SessionKind.CODING_AGENT)
        assert session.task_id == "task1"
        assert session.lifecycle == SessionLifecycle.PENDING

    def test_empty_task_id_raises(self):
        with pytest.raises(ValueError, match="must have a task_id"):
            Session(task_id="", kind=SessionKind.CODING_AGENT)

    def test_with_lifecycle(self):
        session = Session(task_id="task1", kind=SessionKind.CODING_AGENT)
        running = session.with_lifecycle(SessionLifecycle.RUNNING)
        assert running.lifecycle == SessionLifecycle.RUNNING
        assert session.lifecycle == SessionLifecycle.PENDING  # unchanged

    def test_with_lifecycle_archived_sets_timestamp(self):
        session = Session(task_id="task1", kind=SessionKind.CODING_AGENT)
        archived = session.with_lifecycle(SessionLifecycle.ARCHIVED)
        assert archived.archived_at is not None

    def test_with_attachment(self):
        session = Session(task_id="task1", kind=SessionKind.CODING_AGENT)
        att = SessionAttachment(pid=1234, tmux_session="ab-1")
        updated = session.with_attachment(att)
        assert updated.attachment.pid == 1234
        assert session.attachment.pid is None  # unchanged

    def test_frozen(self):
        session = Session(task_id="task1", kind=SessionKind.CODING_AGENT)
        with pytest.raises(AttributeError):
            session.lifecycle = SessionLifecycle.RUNNING  # type: ignore


class TestSessionAttachment:
    def test_to_doc(self):
        att = SessionAttachment(pid=1234, tmux_session="ab-1", tmux_window="main")
        doc = att.to_doc()
        assert doc["pid"] == 1234
        assert doc["tmux_session"] == "ab-1"

    def test_from_doc(self):
        doc = {"pid": 5678, "tmux_session": "ab-2", "tmux_window": "test"}
        att = SessionAttachment.from_doc(doc)
        assert att.pid == 5678

    def test_from_empty_doc(self):
        att = SessionAttachment.from_doc({})
        assert att.pid is None


class TestResearchProgress:
    def test_roundtrip(self):
        rp = ResearchProgress(
            current_depth=2, max_depth=3,
            queries_completed=5, queries_total=10,
            learnings_count=15,
        )
        doc = rp.to_doc()
        restored = ResearchProgress.from_doc(doc)
        assert restored.current_depth == 2
        assert restored.learnings_count == 15
