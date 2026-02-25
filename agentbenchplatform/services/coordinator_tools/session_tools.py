"""Session management tool handlers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agentbenchplatform.infra import git as git_ops
from agentbenchplatform.models.agent_event import AgentEventType
from agentbenchplatform.services.coordinator_tools.context import ToolContext

logger = logging.getLogger(__name__)


async def handle_list_sessions(ctx: ToolContext, arguments: dict) -> Any:
    task_slug = arguments.get("task_slug", "")
    task_id = ""
    if task_slug:
        task = await ctx.task.get_task(task_slug)
        task_id = task.id if task else ""
    sessions = await ctx.session.list_sessions(task_id=task_id)
    return [
        {
            "id": s.id,
            "display_name": s.display_name,
            "kind": s.kind.value,
            "lifecycle": s.lifecycle.value,
            "task_id": s.task_id,
            "agent_backend": s.agent_backend,
            "worktree_path": s.worktree_path,
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat(),
        }
        for s in sessions
    ]


async def handle_start_coding_session(ctx: ToolContext, arguments: dict) -> Any:
    task = await ctx.task.get_task(arguments["task_slug"])
    if not task:
        return {"error": f"Task not found: {arguments['task_slug']}"}
    session = await ctx.session.start_coding_session(
        task_id=task.id,
        agent_type=arguments.get("agent", ""),
        prompt=arguments.get("prompt", ""),
        workspace_path=task.workspace_path,
        task_tags=task.tags,
        task_complexity=task.complexity,
    )
    await ctx.emit_event(
        session.id, task.id,
        AgentEventType.STARTED,
        f"Agent {session.agent_backend} started",
    )
    return {"session_id": session.id, "status": session.lifecycle.value}


async def handle_stop_session(ctx: ToolContext, arguments: dict) -> Any:
    from agentbenchplatform.services.coordinator_tools.report_tools import auto_report_on_stop

    session = await ctx.session.get_session(arguments["session_id"])
    stopped = await ctx.session.stop_session(arguments["session_id"])
    if stopped and session:
        await auto_report_on_stop(ctx, session)
        await ctx.emit_event(
            session.id, session.task_id,
            AgentEventType.COMPLETED,
            "Session stopped",
        )
    return {"stopped": stopped is not None}


async def handle_get_session_output(ctx: ToolContext, arguments: dict) -> Any:
    output = await ctx.session.get_session_output(
        arguments["session_id"],
        lines=arguments.get("lines", 50),
    )
    return {"output": output}


async def handle_send_to_session(ctx: ToolContext, arguments: dict) -> Any:
    success = await ctx.session.send_to_session(
        arguments["session_id"], arguments["text"]
    )
    return {"sent": success}


async def handle_get_session_diff(ctx: ToolContext, arguments: dict) -> Any:
    try:
        diff = await ctx.session.get_session_diff(arguments["session_id"])
    except Exception:
        diff = await ctx.session.run_in_worktree(
            arguments["session_id"], "git status --short"
        )
    return {"diff": diff or "(no changes)"}


async def handle_run_in_worktree(ctx: ToolContext, arguments: dict) -> Any:
    output = await ctx.session.run_in_worktree(
        arguments["session_id"], arguments["command"]
    )
    return {"output": output}


async def handle_pause_session(ctx: ToolContext, arguments: dict) -> Any:
    session = await ctx.session.pause_session(arguments["session_id"])
    return {"paused": session is not None}


async def handle_resume_session(ctx: ToolContext, arguments: dict) -> Any:
    session = await ctx.session.resume_session(arguments["session_id"])
    return {"resumed": session is not None}


async def handle_get_session_git_log(ctx: ToolContext, arguments: dict) -> Any:
    session = await ctx.session.get_session(arguments["session_id"])
    if not session:
        return {"error": "Session not found"}
    if not session.worktree_path:
        return {"error": "Session has no worktree"}
    log = await git_ops.get_log(
        session.worktree_path,
        max_commits=arguments.get("max_commits", 10),
    )
    return {"log": log}


async def handle_archive_session(ctx: ToolContext, arguments: dict) -> Any:
    sid = arguments["session_id"]
    # Explicit cleanup of mutable coordinator state
    if ctx.session_output_hashes is not None:
        ctx.session_output_hashes.pop(sid, None)
    if ctx.session_deadlines is not None:
        ctx.session_deadlines.pop(sid, None)
    session = await ctx.session.archive_session(sid)
    if not session:
        return {"error": "Session not found"}
    return {"archived": True, "session_id": session.id}


async def handle_check_session_liveness(ctx: ToolContext, arguments: dict) -> Any:
    alive = await ctx.session.check_session_liveness(arguments["session_id"])
    return {"alive": alive, "session_id": arguments["session_id"]}


async def handle_set_session_deadline(ctx: ToolContext, arguments: dict) -> Any:
    import time

    sid = arguments["session_id"]
    minutes = arguments["minutes"]
    if ctx.session_deadlines is not None:
        ctx.session_deadlines[sid] = time.time() + (minutes * 60)
    return {"deadline_set": True, "session_id": sid, "minutes": minutes}


async def handle_merge_session(ctx: ToolContext, arguments: dict) -> Any:
    from agentbenchplatform.services.coordinator_tools.conflict_tools import (
        check_session_conflicts,
    )

    session = await ctx.session.get_session(arguments["session_id"])
    if not session:
        return {"error": "Session not found"}
    if not session.worktree_path:
        return {"error": "Session has no worktree"}
    task = await ctx.task.get_task_by_id(session.task_id)
    if not task or not task.workspace_path:
        return {"error": "Task has no workspace_path — cannot determine merge target"}

    force = arguments.get("force", False)
    if not force:
        conflict_result = await check_session_conflicts(ctx, arguments["session_id"])
        if conflict_result.get("has_conflicts"):
            return {
                "merged": False,
                "warning": "Conflicting file changes detected. Use force=true to merge anyway.",
                "conflicts": conflict_result["conflicts"],
            }

    branch_proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "--abbrev-ref", "HEAD",
        cwd=session.worktree_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await branch_proc.communicate()
    branch_name = stdout.decode().strip()
    if not branch_name:
        return {"error": "Could not determine session branch name"}

    result = await git_ops.merge_branch(task.workspace_path, branch_name)

    if ctx.merge_record_repo:
        try:
            merge_sha = await git_ops.get_head_sha(task.workspace_path)
            from agentbenchplatform.models.merge_record import MergeRecord
            await ctx.merge_record_repo.insert(MergeRecord(
                session_id=session.id,
                task_id=session.task_id,
                branch_name=branch_name,
                merge_commit_sha=merge_sha,
            ))
        except Exception:
            logger.debug("Failed to record merge", exc_info=True)

    return {"merged": True, "branch": branch_name, "output": result}


async def handle_send_notification(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.signal:
        return {"error": "Signal service not available"}
    sent = await ctx.signal.send_notification(
        arguments["recipient"], arguments["text"],
    )
    return {"sent": sent}
