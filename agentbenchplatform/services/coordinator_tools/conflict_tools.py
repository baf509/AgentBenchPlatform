"""Conflict detection and rollback tool handlers."""

from __future__ import annotations

from typing import Any

from agentbenchplatform.infra import git as git_ops
from agentbenchplatform.models.session import SessionLifecycle
from agentbenchplatform.services.coordinator_tools.context import ToolContext


async def check_session_conflicts(ctx: ToolContext, session_id: str) -> dict:
    """Check for file conflicts between sessions on the same task."""
    session = await ctx.session.get_session(session_id)
    if not session:
        return {"error": "Session not found"}
    if not session.worktree_path:
        return {"error": "Session has no worktree"}

    try:
        my_files = await git_ops.get_branch_changed_files(session.worktree_path)
    except Exception as e:
        return {"error": f"Could not get changed files: {e}"}

    all_sessions = await ctx.session.list_sessions(task_id=session.task_id)
    conflicts: list[dict] = []
    for other in all_sessions:
        if other.id == session_id or not other.worktree_path:
            continue
        if other.lifecycle not in (SessionLifecycle.RUNNING, SessionLifecycle.STOPPED):
            continue
        try:
            other_files = await git_ops.get_branch_changed_files(other.worktree_path)
            overlap = set(my_files) & set(other_files)
            if overlap:
                conflicts.append({
                    "session_id": other.id,
                    "overlapping_files": sorted(overlap),
                })
        except Exception:
            continue

    return {"has_conflicts": len(conflicts) > 0, "conflicts": conflicts}


async def handle_check_conflicts(ctx: ToolContext, arguments: dict) -> Any:
    return await check_session_conflicts(ctx, arguments["session_id"])


async def handle_rollback_session(ctx: ToolContext, arguments: dict) -> Any:
    """Revert a previously merged session."""
    session_id = arguments["session_id"]
    if not ctx.merge_record_repo:
        return {"error": "Merge record repo not available"}

    record = await ctx.merge_record_repo.find_by_session(session_id)
    if not record:
        return {"error": f"No merge record found for session: {session_id}"}
    if record.reverted:
        return {"error": "This merge has already been reverted"}

    task = await ctx.task.get_task_by_id(record.task_id)
    if not task or not task.workspace_path:
        return {"error": "Task has no workspace_path — cannot revert"}

    try:
        revert_sha = await git_ops.revert_merge(task.workspace_path, record.merge_commit_sha)
        await ctx.merge_record_repo.mark_reverted(session_id, revert_sha)
        return {"reverted": True, "revert_commit": revert_sha, "session_id": session_id}
    except Exception as e:
        return {"error": f"Git revert failed: {e}"}
