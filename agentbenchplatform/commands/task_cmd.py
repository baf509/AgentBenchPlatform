"""CLI handlers for task commands."""

from __future__ import annotations

import asyncio

import click

from agentbenchplatform.commands._helpers import get_remote_context


def _run(coro):
    return asyncio.run(coro)


@click.group("task")
def task_group():
    """Manage tasks."""
    pass


@task_group.command("create")
@click.argument("title")
@click.option("--description", "-d", default="", help="Task description")
@click.option("--workspace", "-w", default="", help="Workspace path (git repo directory)")
@click.option("--tags", "-t", multiple=True, help="Tags for the task")
@click.option(
    "--complexity",
    type=click.Choice(["junior", "mid", "senior"], case_sensitive=False),
    default="",
    help="Task complexity tier for agent routing",
)
def task_create(title: str, description: str, workspace: str, tags: tuple[str, ...], complexity: str):
    """Create a new task."""

    async def _create():
        ctx = await get_remote_context()
        try:
            # Resolve workspace path
            workspace_path = workspace
            if workspace_path:
                from pathlib import Path

                resolved = Path(workspace_path).expanduser().resolve()
                if not resolved.is_dir():
                    click.echo(f"Workspace path is not a directory: {resolved}", err=True)
                    return
                workspace_path = str(resolved)

            task = await ctx.task_service.create_task(
                title=title, description=description, tags=tags,
                complexity=complexity, workspace_path=workspace_path,
            )
            click.echo(f"Created task: {task.slug} ({task.title})")
            if task.id:
                click.echo(f"  ID: {task.id}")
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
        finally:
            await ctx.close()

    _run(_create())


@task_group.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include deleted tasks")
@click.option("--archived", is_flag=True, help="Show only archived tasks")
def task_list(show_all: bool, archived: bool):
    """List tasks."""

    async def _list():
        ctx = await get_remote_context()
        try:
            tasks = await ctx.task_service.list_tasks(
                show_all=show_all, archived=archived
            )
            if not tasks:
                click.echo("No tasks found.")
                return
            for t in tasks:
                status = t.status.value
                tags = ", ".join(t.tags) if t.tags else ""
                tag_str = f" [{tags}]" if tags else ""
                click.echo(f"  {t.slug} ({status}){tag_str} - {t.title}")
        finally:
            await ctx.close()

    _run(_list())


@task_group.command("show")
@click.argument("slug")
def task_show(slug: str):
    """Show task details."""

    async def _show():
        ctx = await get_remote_context()
        try:
            task = await ctx.task_service.get_task(slug)
            if not task:
                click.echo(f"Task not found: {slug}", err=True)
                return
            click.echo(f"Task: {task.title}")
            click.echo(f"  Slug: {task.slug}")
            click.echo(f"  Status: {task.status.value}")
            click.echo(f"  ID: {task.id}")
            if task.description:
                click.echo(f"  Description: {task.description}")
            if task.workspace_path:
                click.echo(f"  Workspace: {task.workspace_path}")
            if task.tags:
                click.echo(f"  Tags: {', '.join(task.tags)}")
            click.echo(f"  Created: {task.created_at.isoformat()}")
        finally:
            await ctx.close()

    _run(_show())


@task_group.command("archive")
@click.argument("slug")
def task_archive(slug: str):
    """Archive a task."""

    async def _archive():
        ctx = await get_remote_context()
        try:
            task = await ctx.task_service.archive_task(slug)
            if task:
                click.echo(f"Archived: {task.slug}")
            else:
                click.echo(f"Task not found: {slug}", err=True)
        finally:
            await ctx.close()

    _run(_archive())


@task_group.command("delete")
@click.argument("slug")
@click.confirmation_option(prompt="Are you sure you want to delete this task?")
def task_delete(slug: str):
    """Delete a task (soft delete)."""

    async def _delete():
        ctx = await get_remote_context()
        try:
            task = await ctx.task_service.delete_task(slug)
            if task:
                click.echo(f"Deleted: {task.slug}")
            else:
                click.echo(f"Task not found: {slug}", err=True)
        finally:
            await ctx.close()

    _run(_delete())
