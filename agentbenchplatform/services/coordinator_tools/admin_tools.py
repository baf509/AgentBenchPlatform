"""Administrative tool handlers: usage, workspaces, conversations, research, estimation, playbooks."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from agentbenchplatform.models.research import ResearchConfig
from agentbenchplatform.services.coordinator_tools.context import ToolContext

logger = logging.getLogger(__name__)


async def handle_start_research(ctx: ToolContext, arguments: dict) -> Any:
    task = await ctx.task.get_task(arguments["task_slug"])
    if not task:
        return {"error": f"Task not found: {arguments['task_slug']}"}
    if not ctx.research:
        return {"error": "Research service not available"}

    research_config = ResearchConfig(
        query=arguments["query"],
        breadth=arguments.get("breadth", 4),
        depth=arguments.get("depth", 3),
        provider=ctx.config.research.default_provider,
        search_provider=ctx.config.research.default_search,
    )
    session = await ctx.research.start_research(
        task_id=task.id,
        research_config=research_config,
    )
    return {
        "started": True,
        "session_id": session.id,
        "query": arguments["query"],
    }


async def handle_get_research_status(ctx: ToolContext, arguments: dict) -> Any:
    session = await ctx.session.get_session(arguments["session_id"])
    if not session:
        return {"error": "Session not found"}
    rp = session.research_progress
    return {
        "lifecycle": session.lifecycle.value,
        "progress": rp.to_doc() if rp else None,
    }


async def handle_get_research_results(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.research:
        return {"error": "Research service not available"}
    task = await ctx.task.get_task(arguments["task_slug"])
    if not task:
        return {"error": f"Task not found: {arguments['task_slug']}"}
    results = await ctx.research.get_research_results(task.id)
    return [
        {
            "key": m.key,
            "content": m.content[:500],
            "created_at": m.created_at.isoformat(),
        }
        for m in results
    ]


async def handle_get_usage_summary(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.usage_repo:
        return {"error": "Usage tracking not available"}
    hours = arguments.get("hours", 6)
    recent = await ctx.usage_repo.aggregate_recent(hours=hours)
    totals = await ctx.usage_repo.aggregate_totals()
    return {"recent": recent, "totals": totals, "recent_hours": hours}


async def handle_get_usage_by_task(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.usage_repo:
        return {"error": "Usage tracking not available"}
    task = await ctx.task.get_task(arguments["task_slug"])
    if not task:
        return {"error": f"Task not found: {arguments['task_slug']}"}
    result = await ctx.usage_repo.aggregate_by_task(task.id)
    return result


async def handle_list_workspaces(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.workspace_repo:
        return {"error": "Workspace repo not available"}
    workspaces = await ctx.workspace_repo.list_all()
    return [
        {"id": ws.id, "path": ws.path, "name": ws.name}
        for ws in workspaces
    ]


async def handle_register_workspace(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.workspace_repo:
        return {"error": "Workspace repo not available"}
    from agentbenchplatform.models.workspace import Workspace
    ws = await ctx.workspace_repo.insert(Workspace(
        path=arguments["path"],
        name=arguments.get("name", ""),
    ))
    return {"registered": True, "id": ws.id, "path": ws.path}


async def handle_delete_workspace(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.workspace_repo:
        return {"error": "Workspace repo not available"}
    deleted = await ctx.workspace_repo.delete(arguments["workspace_id"])
    return {"deleted": deleted}


async def handle_list_conversations(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.history_repo:
        return {"error": "History repo not available"}
    convos = await ctx.history_repo.list_conversations()
    for c in convos:
        if "updated_at" in c and c["updated_at"] is not None:
            c["updated_at"] = c["updated_at"].isoformat()
    return convos


async def handle_clear_conversation(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.history_repo:
        return {"error": "History repo not available"}
    cleared = await ctx.history_repo.clear_conversation(
        arguments["channel"],
        arguments.get("sender_id", ""),
    )
    # Also clear in-memory cache
    if ctx.conversations is not None:
        key = f"{arguments['channel']}:{arguments.get('sender_id', '')}"
        ctx.conversations.pop(key, None)
    return {"cleared": cleared}


async def handle_estimate_duration(ctx: ToolContext, arguments: dict) -> Any:
    """Estimate session duration from historical data."""
    if not ctx.session_metric_repo:
        return {"error": "Session metric repo not available"}

    session_id = arguments.get("session_id")
    if session_id:
        session = await ctx.session.get_session(session_id)
        if not session:
            return {"error": "Session not found"}
        elapsed = (datetime.now(timezone.utc) - session.created_at).total_seconds()
        stats = await ctx.session_metric_repo.get_stats(
            agent=session.agent_backend,
            complexity=arguments.get("complexity"),
        )
        if stats["sample_count"] < 3:
            return {"insufficient_data": True, "elapsed_seconds": int(elapsed), "sample_count": stats["sample_count"]}
        remaining = max(0, stats["avg_seconds"] - elapsed)
        return {
            "elapsed_seconds": int(elapsed),
            "estimated_remaining_seconds": int(remaining),
            "avg_seconds": stats["avg_seconds"],
            "p90_seconds": stats["p90_seconds"],
            "sample_count": stats["sample_count"],
        }

    stats = await ctx.session_metric_repo.get_stats(
        agent=arguments.get("agent"),
        complexity=arguments.get("complexity"),
    )
    if stats["sample_count"] < 3:
        return {"insufficient_data": True, "sample_count": stats["sample_count"]}
    return stats


async def handle_list_playbooks(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.playbook_repo:
        return {"error": "Playbook repo not available"}
    playbooks = await ctx.playbook_repo.list_all()
    return [
        {
            "name": p.name,
            "description": p.description,
            "steps": len(p.steps),
            "workspace_path": p.workspace_path,
            "tags": list(p.tags),
        }
        for p in playbooks
    ]


async def handle_create_playbook(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.playbook_repo:
        return {"error": "Playbook repo not available"}
    from agentbenchplatform.models.playbook import Playbook, PlaybookStep

    steps = tuple(
        PlaybookStep(action=s["action"], params=s.get("params", {}))
        for s in arguments["steps"]
    )
    playbook = Playbook(
        name=arguments["name"],
        description=arguments.get("description", ""),
        steps=steps,
        workspace_path=arguments.get("workspace_path", ""),
    )
    saved = await ctx.playbook_repo.insert(playbook)
    return {"created": True, "name": saved.name}


async def handle_run_playbook(ctx: ToolContext, arguments: dict) -> Any:
    """Execute a playbook, creating tasks and sessions."""
    if not ctx.playbook_repo:
        return {"error": "Playbook repo not available"}

    playbook = await ctx.playbook_repo.find_by_name(arguments["playbook_name"])
    if not playbook:
        return {"error": f"Playbook not found: {arguments['playbook_name']}"}

    workspace_path = arguments.get("workspace_path") or playbook.workspace_path
    dry_run = arguments.get("dry_run", False)

    results: list[dict] = []
    task_slugs: dict[int, str] = {}  # step_index -> task_slug

    for i, step in enumerate(playbook.steps):
        if dry_run:
            results.append({"step": i, "action": step.action, "params": step.params, "dry_run": True})
            continue

        if step.action == "create_task":
            deps = ()
            if dep_step := step.params.get("depends_on_step"):
                dep_slug = task_slugs.get(dep_step)
                if dep_slug:
                    deps = (dep_slug,)
            try:
                task = await ctx.task.create_task(
                    title=step.params.get("title", f"Playbook step {i}"),
                    description=step.params.get("description", ""),
                    workspace_path=step.params.get("workspace_path", workspace_path),
                    complexity=step.params.get("complexity", ""),
                    depends_on=deps,
                )
                task_slugs[i] = task.slug
                results.append({"step": i, "action": "create_task", "slug": task.slug})
            except Exception as e:
                results.append({"step": i, "action": "create_task", "error": str(e)})

        elif step.action == "start_session":
            task_ref = step.params.get("task_ref")
            task_slug = task_slugs.get(task_ref) if task_ref is not None else None
            if not task_slug:
                results.append({"step": i, "action": "start_session", "error": "Task ref not found"})
                continue
            try:
                result = await ctx.execute_tool("start_coding_session", {
                    "task_slug": task_slug,
                    "agent": step.params.get("agent", ""),
                    "prompt": step.params.get("prompt", ""),
                })
                results.append({"step": i, "action": "start_session", **result})
            except Exception as e:
                results.append({"step": i, "action": "start_session", "error": str(e)})

        elif step.action == "review_session":
            task_ref = step.params.get("task_ref")
            task_slug = task_slugs.get(task_ref) if task_ref is not None else None
            results.append({
                "step": i, "action": "review_session",
                "note": "Review will run when session completes",
                "task_slug": task_slug,
                "test_command": step.params.get("test_command", ""),
            })

        elif step.action == "merge_session":
            task_ref = step.params.get("task_ref")
            task_slug = task_slugs.get(task_ref) if task_ref is not None else None
            results.append({
                "step": i, "action": "merge_session",
                "note": "Merge will run after review",
                "task_slug": task_slug,
            })

    return {"playbook": playbook.name, "steps_executed": len(results), "results": results}
