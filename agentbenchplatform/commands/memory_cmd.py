"""CLI handlers for memory commands."""

from __future__ import annotations

import asyncio

import click

from agentbenchplatform.commands._helpers import get_remote_context
from agentbenchplatform.models.memory import MemoryQuery, MemoryScope


def _run(coro):
    return asyncio.run(coro)


@click.group("memory")
def memory_group():
    """Manage shared memories."""
    pass


@memory_group.command("store")
@click.option("--task", "-t", "task_slug", required=True, help="Task slug")
@click.option("--key", "-k", required=True, help="Memory key")
@click.option("--content", "-c", required=True, help="Memory content")
@click.option("--scope", "-s", default="task", help="Scope (task, session, global)")
def memory_store(task_slug: str, key: str, content: str, scope: str):
    """Store a memory entry."""

    async def _store():
        ctx = await get_remote_context()
        try:
            task = await ctx.task_service.get_task(task_slug)
            if not task:
                click.echo(f"Task not found: {task_slug}", err=True)
                return
            mem_scope = MemoryScope(scope)
            entry = await ctx.memory_service.store(
                key=key,
                content=content,
                scope=mem_scope,
                task_id=task.id,
            )
            click.echo(f"Stored memory: {entry.key} (id={entry.id})")
            if entry.embedding:
                click.echo(f"  Embedding: {len(entry.embedding)} dimensions")
            else:
                click.echo("  Embedding: none (embedding service unavailable)")
        finally:
            await ctx.close()

    _run(_store())


@memory_group.command("search")
@click.option("--query", "-q", required=True, help="Search query text")
@click.option("--task", "-t", "task_slug", default="", help="Limit to task")
@click.option("--limit", "-l", default=10, help="Max results")
def memory_search(query: str, task_slug: str, limit: int):
    """Search memories using vector similarity."""

    async def _search():
        ctx = await get_remote_context()
        try:
            task_id = ""
            if task_slug:
                task = await ctx.task_service.get_task(task_slug)
                if not task:
                    click.echo(f"Task not found: {task_slug}", err=True)
                    return
                task_id = task.id

            mq = MemoryQuery(query_text=query, task_id=task_id, limit=limit)
            results = await ctx.memory_service.search(mq)
            if not results:
                click.echo("No results found.")
                return
            for m in results:
                click.echo(f"  [{m.key}] ({m.scope.value}) {m.content[:100]}")
        finally:
            await ctx.close()

    _run(_search())


@memory_group.command("list")
@click.option("--task", "-t", "task_slug", default="", help="Filter by task")
def memory_list(task_slug: str):
    """List memory entries."""

    async def _list():
        ctx = await get_remote_context()
        try:
            task_id = ""
            if task_slug:
                task = await ctx.task_service.get_task(task_slug)
                if not task:
                    click.echo(f"Task not found: {task_slug}", err=True)
                    return
                task_id = task.id

            memories = await ctx.memory_service.list_memories(task_id=task_id)
            if not memories:
                click.echo("No memories found.")
                return
            for m in memories:
                has_emb = "+" if m.embedding else "-"
                click.echo(
                    f"  [{m.key}] ({m.scope.value}) [{has_emb}emb] "
                    f"{m.content[:80]}"
                )
        finally:
            await ctx.close()

    _run(_list())


@memory_group.command("delete")
@click.argument("memory_id")
@click.confirmation_option(prompt="Are you sure?")
def memory_delete(memory_id: str):
    """Delete a memory entry."""

    async def _delete():
        ctx = await get_remote_context()
        try:
            deleted = await ctx.memory_service.delete_memory(memory_id)
            if deleted:
                click.echo(f"Deleted memory: {memory_id}")
            else:
                click.echo(f"Memory not found: {memory_id}", err=True)
        finally:
            await ctx.close()

    _run(_delete())
