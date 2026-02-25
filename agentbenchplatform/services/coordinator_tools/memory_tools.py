"""Memory management tool handlers."""

from __future__ import annotations

from typing import Any

from agentbenchplatform.models.memory import MemoryQuery, MemoryScope
from agentbenchplatform.services.coordinator_tools.context import ToolContext


async def handle_search_memory(ctx: ToolContext, arguments: dict) -> Any:
    task_id = ""
    if task_slug := arguments.get("task_slug"):
        task = await ctx.task.get_task(task_slug)
        task_id = task.id if task else ""
    query = MemoryQuery(
        query_text=arguments["query"],
        task_id=task_id,
        limit=arguments.get("limit", 10),
    )
    results = await ctx.memory.search(query)
    return [
        {"key": m.key, "content": m.content[:500], "scope": m.scope.value, "id": m.id}
        for m in results
    ]


async def handle_store_memory(ctx: ToolContext, arguments: dict) -> Any:
    task_id = ""
    scope = MemoryScope.GLOBAL
    if task_slug := arguments.get("task_slug"):
        task = await ctx.task.get_task(task_slug)
        if task:
            task_id = task.id
            scope = MemoryScope.TASK
    session_id = arguments.get("session_id", "")
    if session_id:
        scope = MemoryScope.SESSION
    entry = await ctx.memory.store(
        key=arguments["key"],
        content=arguments["content"],
        scope=scope,
        task_id=task_id,
        session_id=session_id,
        content_type=arguments.get("content_type", "text"),
        metadata=arguments.get("metadata"),
    )
    return {"stored": True, "id": entry.id}


async def handle_list_memories(ctx: ToolContext, arguments: dict) -> Any:
    task_id = ""
    if task_slug := arguments.get("task_slug"):
        task = await ctx.task.get_task(task_slug)
        task_id = task.id if task else ""
    scope = MemoryScope(arguments["scope"]) if arguments.get("scope") else None
    memories = await ctx.memory.list_memories(task_id=task_id, scope=scope)
    limit = arguments.get("limit", 20)
    return [
        {
            "id": m.id,
            "key": m.key,
            "content": m.content[:500],
            "scope": m.scope.value,
            "task_id": m.task_id,
            "created_at": m.created_at.isoformat(),
        }
        for m in memories[:limit]
    ]


async def handle_delete_memory(ctx: ToolContext, arguments: dict) -> Any:
    deleted = await ctx.memory.delete_memory(arguments["memory_id"])
    return {"deleted": deleted}


async def handle_get_memory_by_key(ctx: ToolContext, arguments: dict) -> Any:
    task_id = ""
    if task_slug := arguments.get("task_slug"):
        task = await ctx.task.get_task(task_slug)
        task_id = task.id if task else ""
    entry = await ctx.memory.find_by_key(arguments["key"], task_id=task_id)
    if not entry:
        return {"error": f"No memory found with key: {arguments['key']}"}
    return {
        "id": entry.id,
        "key": entry.key,
        "content": entry.content,
        "scope": entry.scope.value,
        "task_id": entry.task_id,
        "session_id": entry.session_id,
        "content_type": entry.content_type,
        "created_at": entry.created_at.isoformat(),
    }


async def handle_update_memory(ctx: ToolContext, arguments: dict) -> Any:
    updated = await ctx.memory.update_memory(
        arguments["memory_id"], arguments["content"],
    )
    if not updated:
        return {"error": f"Memory not found: {arguments['memory_id']}"}
    return {"updated": True, "id": updated.id}


async def handle_list_memories_by_session(ctx: ToolContext, arguments: dict) -> Any:
    memories = await ctx.memory.list_by_session(arguments["session_id"])
    return [
        {
            "id": m.id,
            "key": m.key,
            "content": m.content[:500],
            "scope": m.scope.value,
            "created_at": m.created_at.isoformat(),
        }
        for m in memories
    ]
