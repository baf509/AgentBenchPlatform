"""Model <-> JSON conversion for RPC transport."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agentbenchplatform.models.agent_event import AgentEvent, AgentEventType
from agentbenchplatform.models.coordinator_decision import CoordinatorDecision, ToolCallRecord
from agentbenchplatform.models.memory import MemoryEntry, MemoryScope
from agentbenchplatform.models.session import (
    ResearchProgress,
    Session,
    SessionAttachment,
    SessionKind,
    SessionLifecycle,
)
from agentbenchplatform.models.session_report import DiffStats, SessionReport, TestResults
from agentbenchplatform.models.task import Task, TaskStatus
from agentbenchplatform.models.usage import UsageEvent
from agentbenchplatform.models.workspace import Workspace


def _dt_to_str(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _str_to_dt(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.fromisoformat(s)


# --- Task ---

def serialize_task(task: Task) -> dict:
    return {
        "slug": task.slug,
        "title": task.title,
        "status": task.status.value,
        "description": task.description,
        "workspace_path": task.workspace_path,
        "tags": list(task.tags),
        "complexity": task.complexity,
        "created_at": _dt_to_str(task.created_at),
        "updated_at": _dt_to_str(task.updated_at),
        "id": task.id,
    }


def deserialize_task(data: dict) -> Task:
    return Task(
        slug=data["slug"],
        title=data["title"],
        status=TaskStatus(data["status"]),
        description=data.get("description", ""),
        workspace_path=data.get("workspace_path", ""),
        tags=tuple(data.get("tags", [])),
        complexity=data.get("complexity", ""),
        created_at=_str_to_dt(data.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_str_to_dt(data.get("updated_at")) or datetime.now(timezone.utc),
        id=data.get("id"),
    )


# --- Session ---

def serialize_attachment(att: SessionAttachment) -> dict:
    return {
        "pid": att.pid,
        "tmux_session": att.tmux_session,
        "tmux_window": att.tmux_window,
        "tmux_pane_id": att.tmux_pane_id,
    }


def deserialize_attachment(data: dict) -> SessionAttachment:
    return SessionAttachment(
        pid=data.get("pid"),
        tmux_session=data.get("tmux_session", ""),
        tmux_window=data.get("tmux_window", ""),
        tmux_pane_id=data.get("tmux_pane_id", ""),
    )


def serialize_research_progress(rp: ResearchProgress) -> dict:
    return {
        "current_depth": rp.current_depth,
        "max_depth": rp.max_depth,
        "queries_completed": rp.queries_completed,
        "queries_total": rp.queries_total,
        "learnings_count": rp.learnings_count,
    }


def deserialize_research_progress(data: dict) -> ResearchProgress:
    return ResearchProgress(
        current_depth=data.get("current_depth", 0),
        max_depth=data.get("max_depth", 0),
        queries_completed=data.get("queries_completed", 0),
        queries_total=data.get("queries_total", 0),
        learnings_count=data.get("learnings_count", 0),
    )


def serialize_session(session: Session) -> dict:
    return {
        "task_id": session.task_id,
        "kind": session.kind.value,
        "lifecycle": session.lifecycle.value,
        "agent_backend": session.agent_backend,
        "display_name": session.display_name,
        "agent_thread_id": session.agent_thread_id,
        "worktree_path": session.worktree_path,
        "attachment": serialize_attachment(session.attachment),
        "research_progress": (
            serialize_research_progress(session.research_progress)
            if session.research_progress
            else None
        ),
        "created_at": _dt_to_str(session.created_at),
        "updated_at": _dt_to_str(session.updated_at),
        "archived_at": _dt_to_str(session.archived_at),
        "id": session.id,
    }


def deserialize_session(data: dict) -> Session:
    rp = data.get("research_progress")
    return Session(
        task_id=data["task_id"],
        kind=SessionKind(data["kind"]),
        lifecycle=SessionLifecycle(data["lifecycle"]),
        agent_backend=data.get("agent_backend", ""),
        display_name=data.get("display_name", ""),
        agent_thread_id=data.get("agent_thread_id", ""),
        worktree_path=data.get("worktree_path", ""),
        attachment=deserialize_attachment(data.get("attachment", {})),
        research_progress=deserialize_research_progress(rp) if rp else None,
        created_at=_str_to_dt(data.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_str_to_dt(data.get("updated_at")) or datetime.now(timezone.utc),
        archived_at=_str_to_dt(data.get("archived_at")),
        id=data.get("id"),
    )


# --- Memory ---

def serialize_memory(entry: MemoryEntry) -> dict:
    return {
        "key": entry.key,
        "content": entry.content,
        "scope": entry.scope.value,
        "task_id": entry.task_id,
        "session_id": entry.session_id,
        "content_type": entry.content_type,
        "embedding": entry.embedding,
        "metadata": entry.metadata,
        "created_at": _dt_to_str(entry.created_at),
        "updated_at": _dt_to_str(entry.updated_at),
        "id": entry.id,
    }


def deserialize_memory(data: dict) -> MemoryEntry:
    return MemoryEntry(
        key=data["key"],
        content=data["content"],
        scope=MemoryScope(data["scope"]),
        task_id=data.get("task_id", ""),
        session_id=data.get("session_id", ""),
        content_type=data.get("content_type", "text"),
        embedding=data.get("embedding"),
        metadata=data.get("metadata"),
        created_at=_str_to_dt(data.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_str_to_dt(data.get("updated_at")) or datetime.now(timezone.utc),
        id=data.get("id"),
    )


# --- Usage ---

def serialize_usage(event: UsageEvent) -> dict:
    return {
        "source": event.source,
        "model": event.model,
        "input_tokens": event.input_tokens,
        "output_tokens": event.output_tokens,
        "task_id": event.task_id,
        "session_id": event.session_id,
        "channel": event.channel,
        "timestamp": _dt_to_str(event.timestamp),
        "id": event.id,
    }


def deserialize_usage(data: dict) -> UsageEvent:
    return UsageEvent(
        source=data["source"],
        model=data.get("model", ""),
        input_tokens=data.get("input_tokens", 0),
        output_tokens=data.get("output_tokens", 0),
        task_id=data.get("task_id", ""),
        session_id=data.get("session_id", ""),
        channel=data.get("channel", ""),
        timestamp=_str_to_dt(data.get("timestamp")) or datetime.now(timezone.utc),
        id=data.get("id"),
    )


# --- Workspace ---

def serialize_workspace(ws: Workspace) -> dict:
    return {
        "path": ws.path,
        "name": ws.name,
        "created_at": _dt_to_str(ws.created_at),
        "id": ws.id,
    }


def deserialize_workspace(data: dict) -> Workspace:
    return Workspace(
        path=data["path"],
        name=data.get("name", ""),
        created_at=_str_to_dt(data.get("created_at")) or datetime.now(timezone.utc),
        id=data.get("id"),
    )


# --- Dashboard Snapshot ---

def serialize_dashboard_snapshot(snapshot: Any) -> dict:
    """Serialize a DashboardSnapshot for RPC transport."""
    from agentbenchplatform.services.dashboard_service import DashboardSnapshot

    if not isinstance(snapshot, DashboardSnapshot):
        return {}
    return {
        "tasks": [
            {
                "task": serialize_task(ts.task),
                "sessions": [serialize_session(s) for s in ts.sessions],
            }
            for ts in snapshot.tasks
        ],
        "total_running": snapshot.total_running,
        "total_sessions": snapshot.total_sessions,
        "timestamp": _dt_to_str(snapshot.timestamp),
    }


def deserialize_dashboard_snapshot(data: dict) -> Any:
    """Deserialize a DashboardSnapshot from RPC transport."""
    from agentbenchplatform.services.dashboard_service import (
        DashboardSnapshot,
        TaskSnapshot,
    )

    task_snapshots = []
    for ts_data in data.get("tasks", []):
        task = deserialize_task(ts_data["task"])
        sessions = [deserialize_session(s) for s in ts_data.get("sessions", [])]
        task_snapshots.append(TaskSnapshot(task=task, sessions=sessions))

    return DashboardSnapshot(
        tasks=task_snapshots,
        total_running=data.get("total_running", 0),
        total_sessions=data.get("total_sessions", 0),
        timestamp=_str_to_dt(data.get("timestamp")) or datetime.now(timezone.utc),
    )


def serialize_workspace_snapshot(ws: Any) -> dict:
    """Serialize a WorkspaceSnapshot for RPC transport."""
    return {
        "workspace_path": ws.workspace_path,
        "tasks": [
            {
                "task": serialize_task(ts.task),
                "sessions": [serialize_session(s) for s in ts.sessions],
            }
            for ts in ws.tasks
        ],
        "standalone": ws.standalone,
        "workspace_id": ws.workspace_id,
        "display_name": ws.display_name,
    }


def deserialize_workspace_snapshot(data: dict) -> Any:
    """Deserialize a WorkspaceSnapshot from RPC transport."""
    from agentbenchplatform.services.dashboard_service import (
        TaskSnapshot,
        WorkspaceSnapshot,
    )

    task_snapshots = []
    for ts_data in data.get("tasks", []):
        task = deserialize_task(ts_data["task"])
        sessions = [deserialize_session(s) for s in ts_data.get("sessions", [])]
        task_snapshots.append(TaskSnapshot(task=task, sessions=sessions))

    return WorkspaceSnapshot(
        workspace_path=data.get("workspace_path", ""),
        tasks=task_snapshots,
        standalone=data.get("standalone", False),
        workspace_id=data.get("workspace_id"),
        display_name=data.get("display_name", ""),
    )


# --- Session Report ---

def serialize_session_report(report: SessionReport) -> dict:
    return {
        "session_id": report.session_id,
        "task_id": report.task_id,
        "agent": report.agent,
        "status": report.status,
        "summary": report.summary,
        "files_changed": list(report.files_changed),
        "test_results": report.test_results.to_doc() if report.test_results else None,
        "diff_stats": report.diff_stats.to_doc() if report.diff_stats else None,
        "agent_notes": report.agent_notes,
        "created_at": _dt_to_str(report.created_at),
        "id": report.id,
    }


def deserialize_session_report(data: dict) -> SessionReport:
    tr = data.get("test_results")
    ds = data.get("diff_stats")
    return SessionReport(
        session_id=data["session_id"],
        task_id=data["task_id"],
        agent=data.get("agent", ""),
        status=data.get("status", "unknown"),
        summary=data.get("summary", ""),
        files_changed=tuple(data.get("files_changed", [])),
        test_results=TestResults.from_doc(tr) if tr else None,
        diff_stats=DiffStats.from_doc(ds) if ds else None,
        agent_notes=data.get("agent_notes", ""),
        created_at=_str_to_dt(data.get("created_at")) or datetime.now(timezone.utc),
        id=data.get("id"),
    )


# --- Agent Event ---

def serialize_agent_event(event: AgentEvent) -> dict:
    return {
        "session_id": event.session_id,
        "task_id": event.task_id,
        "event_type": event.event_type.value,
        "detail": event.detail,
        "acknowledged": event.acknowledged,
        "created_at": _dt_to_str(event.created_at),
        "id": event.id,
    }


def deserialize_agent_event(data: dict) -> AgentEvent:
    return AgentEvent(
        session_id=data["session_id"],
        task_id=data.get("task_id", ""),
        event_type=AgentEventType(data["event_type"]),
        detail=data.get("detail", ""),
        acknowledged=data.get("acknowledged", False),
        created_at=_str_to_dt(data.get("created_at")) or datetime.now(timezone.utc),
        id=data.get("id"),
    )


# --- Coordinator Decision ---

def serialize_coordinator_decision(decision: CoordinatorDecision) -> dict:
    return {
        "conversation_key": decision.conversation_key,
        "turn_number": decision.turn_number,
        "user_input": decision.user_input,
        "tools_called": [tc.to_doc() for tc in decision.tools_called],
        "reasoning_excerpt": decision.reasoning_excerpt,
        "final_response": decision.final_response,
        "tokens": decision.tokens,
        "model": decision.model,
        "timestamp": _dt_to_str(decision.timestamp),
        "id": decision.id,
    }


def deserialize_coordinator_decision(data: dict) -> CoordinatorDecision:
    return CoordinatorDecision(
        conversation_key=data["conversation_key"],
        turn_number=data.get("turn_number", 0),
        user_input=data.get("user_input", ""),
        tools_called=tuple(
            ToolCallRecord.from_doc(tc) for tc in data.get("tools_called", [])
        ),
        reasoning_excerpt=data.get("reasoning_excerpt", ""),
        final_response=data.get("final_response", ""),
        tokens=data.get("tokens", {}),
        model=data.get("model", ""),
        timestamp=_str_to_dt(data.get("timestamp")) or datetime.now(timezone.utc),
        id=data.get("id"),
    )
