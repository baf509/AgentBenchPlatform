"""Tool handler registry — maps tool names to async handler functions."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from agentbenchplatform.services.coordinator_tools.context import ToolContext

# Type alias for tool handlers
ToolHandler = Callable[[ToolContext, dict], Coroutine[Any, Any, Any]]

# Lazy-populated on first access to avoid circular imports
_HANDLERS: dict[str, ToolHandler] | None = None


def _build_registry() -> dict[str, ToolHandler]:
    """Build the tool name -> handler function mapping."""
    from agentbenchplatform.services.coordinator_tools import (
        admin_tools,
        conflict_tools,
        memory_tools,
        report_tools,
        session_tools,
        task_tools,
    )

    return {
        # --- Session tools ---
        "list_sessions": session_tools.handle_list_sessions,
        "start_coding_session": session_tools.handle_start_coding_session,
        "stop_session": session_tools.handle_stop_session,
        "get_session_output": session_tools.handle_get_session_output,
        "send_to_session": session_tools.handle_send_to_session,
        "get_session_diff": session_tools.handle_get_session_diff,
        "run_in_worktree": session_tools.handle_run_in_worktree,
        "pause_session": session_tools.handle_pause_session,
        "resume_session": session_tools.handle_resume_session,
        "get_session_git_log": session_tools.handle_get_session_git_log,
        "archive_session": session_tools.handle_archive_session,
        "check_session_liveness": session_tools.handle_check_session_liveness,
        "set_session_deadline": session_tools.handle_set_session_deadline,
        "merge_session": session_tools.handle_merge_session,
        "send_notification": session_tools.handle_send_notification,
        # --- Task tools ---
        "list_tasks": task_tools.handle_list_tasks,
        "create_task": task_tools.handle_create_task,
        "delete_task": task_tools.handle_delete_task,
        "get_task_detail": task_tools.handle_get_task_detail,
        "update_task": task_tools.handle_update_task,
        "archive_task": task_tools.handle_archive_task,
        "add_dependency": task_tools.handle_add_dependency,
        "remove_dependency": task_tools.handle_remove_dependency,
        "get_task_dependencies": task_tools.handle_get_task_dependencies,
        "get_ready_tasks": task_tools.handle_get_ready_tasks,
        # --- Memory tools ---
        "search_memory": memory_tools.handle_search_memory,
        "store_memory": memory_tools.handle_store_memory,
        "list_memories": memory_tools.handle_list_memories,
        "delete_memory": memory_tools.handle_delete_memory,
        "get_memory_by_key": memory_tools.handle_get_memory_by_key,
        "update_memory": memory_tools.handle_update_memory,
        "list_memories_by_session": memory_tools.handle_list_memories_by_session,
        # --- Report & event tools ---
        "review_session": report_tools.handle_review_session,
        "get_session_report": report_tools.handle_get_session_report,
        "list_reports_by_task": report_tools.handle_list_reports_by_task,
        "list_recent_reports": report_tools.handle_list_recent_reports,
        "list_agent_events": report_tools.handle_list_agent_events,
        "acknowledge_events": report_tools.handle_acknowledge_events,
        "list_events_by_session": report_tools.handle_list_events_by_session,
        # --- Conflict & rollback tools ---
        "check_conflicts": conflict_tools.handle_check_conflicts,
        "rollback_session": conflict_tools.handle_rollback_session,
        # --- Admin tools ---
        "start_research": admin_tools.handle_start_research,
        "get_research_status": admin_tools.handle_get_research_status,
        "get_research_results": admin_tools.handle_get_research_results,
        "get_usage_summary": admin_tools.handle_get_usage_summary,
        "get_usage_by_task": admin_tools.handle_get_usage_by_task,
        "list_workspaces": admin_tools.handle_list_workspaces,
        "register_workspace": admin_tools.handle_register_workspace,
        "delete_workspace": admin_tools.handle_delete_workspace,
        "list_conversations": admin_tools.handle_list_conversations,
        "clear_conversation": admin_tools.handle_clear_conversation,
        "estimate_duration": admin_tools.handle_estimate_duration,
        "list_playbooks": admin_tools.handle_list_playbooks,
        "create_playbook": admin_tools.handle_create_playbook,
        "run_playbook": admin_tools.handle_run_playbook,
    }


def get_tool_handlers() -> dict[str, ToolHandler]:
    """Get the tool handler registry (lazily initialized)."""
    global _HANDLERS
    if _HANDLERS is None:
        _HANDLERS = _build_registry()
    return _HANDLERS


