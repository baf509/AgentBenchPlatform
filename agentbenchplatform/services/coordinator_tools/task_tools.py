"""Task management tool handlers."""

from __future__ import annotations

from typing import Any

from agentbenchplatform.services.coordinator_tools.context import ToolContext


async def handle_list_tasks(ctx: ToolContext, arguments: dict) -> Any:
    tasks = await ctx.task.list_tasks(
        show_all=arguments.get("show_all", False)
    )
    return [
        {
            "slug": t.slug,
            "title": t.title,
            "status": t.status.value,
            "description": t.description[:100] if t.description else "",
            "workspace_path": t.workspace_path,
            "tags": list(t.tags),
            "complexity": t.complexity,
            "depends_on": list(t.depends_on),
        }
        for t in tasks
    ]


async def handle_create_task(ctx: ToolContext, arguments: dict) -> Any:
    task = await ctx.task.create_task(
        title=arguments["title"],
        description=arguments.get("description", ""),
        workspace_path=arguments.get("workspace_path", ""),
        tags=tuple(arguments.get("tags", [])),
        complexity=arguments.get("complexity", ""),
    )
    return {"slug": task.slug, "id": task.id}


async def handle_delete_task(ctx: ToolContext, arguments: dict) -> Any:
    task = await ctx.task.delete_task(arguments["task_slug"])
    if not task:
        return {"error": f"Task not found: {arguments['task_slug']}"}
    return {"deleted": True, "slug": task.slug}


async def handle_get_task_detail(ctx: ToolContext, arguments: dict) -> Any:
    task = await ctx.task.get_task(arguments["task_slug"])
    if not task:
        return {"error": f"Task not found: {arguments['task_slug']}"}
    return {
        "slug": task.slug,
        "title": task.title,
        "status": task.status.value,
        "description": task.description,
        "workspace_path": task.workspace_path,
        "tags": list(task.tags),
        "complexity": task.complexity,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "id": task.id,
    }


async def handle_update_task(ctx: ToolContext, arguments: dict) -> Any:
    task = await ctx.task.update_task(
        slug=arguments["task_slug"],
        description=arguments.get("description"),
        workspace_path=arguments.get("workspace_path"),
        tags=tuple(arguments["tags"]) if "tags" in arguments else None,
        complexity=arguments.get("complexity"),
    )
    if not task:
        return {"error": f"Task not found: {arguments['task_slug']}"}
    return {"updated": True, "slug": task.slug}


async def handle_archive_task(ctx: ToolContext, arguments: dict) -> Any:
    task = await ctx.task.archive_task(arguments["task_slug"])
    if not task:
        return {"error": f"Task not found: {arguments['task_slug']}"}
    return {"archived": True, "slug": task.slug}


async def handle_add_dependency(ctx: ToolContext, arguments: dict) -> Any:
    task = await ctx.task.add_dependency(
        arguments["task_slug"], arguments["depends_on_slug"],
    )
    return {"added": True, "slug": task.slug, "depends_on": list(task.depends_on)}


async def handle_remove_dependency(ctx: ToolContext, arguments: dict) -> Any:
    task = await ctx.task.remove_dependency(
        arguments["task_slug"], arguments["depends_on_slug"],
    )
    return {"removed": True, "slug": task.slug, "depends_on": list(task.depends_on)}


async def handle_get_task_dependencies(ctx: ToolContext, arguments: dict) -> Any:
    deps = await ctx.task.get_task_dependencies(arguments["task_slug"])
    return deps


async def handle_get_ready_tasks(ctx: ToolContext, arguments: dict) -> Any:
    tasks = await ctx.task.get_ready_tasks()
    return [
        {
            "slug": t.slug,
            "title": t.title,
            "status": t.status.value,
            "depends_on": list(t.depends_on),
            "complexity": t.complexity,
        }
        for t in tasks
    ]
