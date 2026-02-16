"""CLI handlers for research commands."""

from __future__ import annotations

import asyncio

import click

from agentbenchplatform.commands._helpers import get_remote_context


def _run(coro):
    return asyncio.run(coro)


@click.group("research")
def research_group():
    """Manage research agents."""
    pass


@research_group.command("start")
@click.argument("task_slug")
@click.option("--query", "-q", required=True, help="Research query")
@click.option("--breadth", "-b", default=4, help="Search breadth (default 4)")
@click.option("--depth", "-d", default=3, help="Search depth (default 3)")
@click.option("--provider", "-p", default="", help="LLM provider")
@click.option("--model", "-m", default="", help="Model to use")
def research_start(
    task_slug: str, query: str, breadth: int, depth: int,
    provider: str, model: str,
):
    """Start a research agent for a task.

    Note: Research service runs on the server. This command triggers it via RPC.
    """

    async def _start():
        ctx = await get_remote_context()
        try:
            task = await ctx.task_service.get_task(task_slug)
            if not task:
                click.echo(f"Task not found: {task_slug}", err=True)
                return

            click.echo(f"Starting research for task: {task_slug}")
            click.echo(f"  Query: {query}")
            click.echo(f"  Breadth: {breadth}, Depth: {depth}")
            click.echo("Note: Research runs on the server.")

            response = await ctx.coordinator_service.ask(
                f"Start a research session for task '{task_slug}' with query: {query}"
            )
            click.echo(f"\n{response}")
        finally:
            await ctx.close()

    _run(_start())


@research_group.command("status")
@click.argument("session_id")
def research_status(session_id: str):
    """Check research progress."""

    async def _status():
        ctx = await get_remote_context()
        try:
            session = await ctx.session_service.get_session(session_id)
            if not session:
                click.echo(f"Session not found: {session_id}", err=True)
                return
            click.echo(f"Research session: {session.id}")
            click.echo(f"  Status: {session.lifecycle.value}")
            if session.research_progress:
                rp = session.research_progress
                click.echo(
                    f"  Depth: {rp.current_depth}/{rp.max_depth}"
                )
                click.echo(f"  Queries completed: {rp.queries_completed}")
                click.echo(f"  Learnings: {rp.learnings_count}")
        finally:
            await ctx.close()

    _run(_status())


@research_group.command("results")
@click.argument("task_slug")
def research_results(task_slug: str):
    """Show research results for a task."""

    async def _results():
        ctx = await get_remote_context()
        try:
            task = await ctx.task_service.get_task(task_slug)
            if not task:
                click.echo(f"Task not found: {task_slug}", err=True)
                return

            from agentbenchplatform.models.memory import MemoryQuery

            mq = MemoryQuery(query_text="research-report", task_id=task.id, limit=20)
            results = await ctx.memory_service.search(mq)
            if not results:
                click.echo("No research results found.")
                return

            report = None
            learnings = []
            for r in results:
                if r.key == "research-report":
                    report = r
                else:
                    learnings.append(r)

            if report:
                click.echo("=== Research Report ===")
                click.echo(report.content)
                click.echo()

            if learnings:
                click.echo(f"=== Learnings ({len(learnings)}) ===")
                for lr in learnings:
                    click.echo(f"  - {lr.content[:150]}")
        finally:
            await ctx.close()

    _run(_results())
