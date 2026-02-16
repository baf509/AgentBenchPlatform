"""CLI handlers for session commands."""

from __future__ import annotations

import asyncio
import subprocess

import click

from agentbenchplatform.commands._helpers import get_remote_context


def _run(coro):
    return asyncio.run(coro)


@click.group("session")
def session_group():
    """Manage agent sessions."""
    pass


@session_group.command("start")
@click.argument("task_slug")
@click.option("--agent", "-a", default="", help="Agent backend (claude_code, opencode, opencode_local)")
@click.option("--prompt", "-p", default="", help="Initial prompt for the agent")
@click.option("--model", "-m", default="", help="Model to use")
def session_start(task_slug: str, agent: str, prompt: str, model: str):
    """Start a new coding agent session for a task."""

    async def _start():
        ctx = await get_remote_context()
        try:
            task = await ctx.task_service.get_task(task_slug)
            if not task:
                click.echo(f"Task not found: {task_slug}", err=True)
                return

            session = await ctx.session_service.start_coding_session(
                task_id=task.id,
                agent_type=agent,
                prompt=prompt,
                model=model,
                workspace_path=task.workspace_path,
            )
            click.echo(f"Started session: {session.id}")
            click.echo(f"  Agent: {session.agent_backend}")
            click.echo(f"  Status: {session.lifecycle.value}")
            att = session.attachment
            if att.tmux_session:
                click.echo(f"  tmux: {att.tmux_session}:{att.tmux_window}")
                click.echo(f"  Attach: tmux attach -t {att.tmux_session}")
            if att.pid:
                click.echo(f"  PID: {att.pid}")
        finally:
            await ctx.close()

    _run(_start())


@session_group.command("list")
@click.option("--task", "-t", "task_slug", default="", help="Filter by task slug")
def session_list(task_slug: str):
    """List sessions."""

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

            sessions = await ctx.session_service.list_sessions(task_id=task_id)
            if not sessions:
                click.echo("No sessions found.")
                return
            for s in sessions:
                lc = s.lifecycle.value
                kind = s.kind.value
                click.echo(f"  {s.id} ({kind}) [{lc}] - {s.display_name}")
        finally:
            await ctx.close()

    _run(_list())


@session_group.command("status")
@click.argument("session_id")
def session_status(session_id: str):
    """Show session status."""

    async def _status():
        ctx = await get_remote_context()
        try:
            session = await ctx.session_service.get_session(session_id)
            if not session:
                click.echo(f"Session not found: {session_id}", err=True)
                return
            click.echo(f"Session: {session.id}")
            click.echo(f"  Display: {session.display_name}")
            click.echo(f"  Kind: {session.kind.value}")
            click.echo(f"  Lifecycle: {session.lifecycle.value}")
            click.echo(f"  Agent: {session.agent_backend}")
            att = session.attachment
            if att.pid:
                alive = await ctx.session_service.check_session_liveness(session_id)
                click.echo(f"  PID: {att.pid} ({'alive' if alive else 'dead'})")
            if session.worktree_path:
                click.echo(f"  Worktree: {session.worktree_path}")
            if att.tmux_session:
                click.echo(f"  tmux: {att.tmux_session}:{att.tmux_window}")
            if session.research_progress:
                rp = session.research_progress
                click.echo(
                    f"  Research: depth {rp.current_depth}/{rp.max_depth}, "
                    f"{rp.queries_completed} queries, {rp.learnings_count} learnings"
                )
        finally:
            await ctx.close()

    _run(_status())


@session_group.command("attach")
@click.argument("session_id")
def session_attach(session_id: str):
    """Attach to a session's tmux pane."""

    async def _get_tmux_target():
        ctx = await get_remote_context()
        try:
            session = await ctx.session_service.get_session(session_id)
            if not session:
                click.echo(f"Session not found: {session_id}", err=True)
                return None
            att = session.attachment
            if not att.tmux_session:
                click.echo("Session has no tmux attachment", err=True)
                return None
            return f"{att.tmux_session}:{att.tmux_window}"
        finally:
            await ctx.close()

    target = _run(_get_tmux_target())
    if target:
        subprocess.run(["tmux", "attach", "-t", target])


@session_group.command("pause")
@click.argument("session_id")
def session_pause(session_id: str):
    """Pause a running session."""

    async def _pause():
        ctx = await get_remote_context()
        try:
            session = await ctx.session_service.pause_session(session_id)
            if session:
                click.echo(f"Paused: {session.id} ({session.lifecycle.value})")
            else:
                click.echo("Failed to pause session", err=True)
        finally:
            await ctx.close()

    _run(_pause())


@session_group.command("resume")
@click.argument("session_id")
def session_resume(session_id: str):
    """Resume a paused session."""

    async def _resume():
        ctx = await get_remote_context()
        try:
            session = await ctx.session_service.resume_session(session_id)
            if session:
                click.echo(f"Resumed: {session.id} ({session.lifecycle.value})")
            else:
                click.echo("Failed to resume session", err=True)
        finally:
            await ctx.close()

    _run(_resume())


@session_group.command("stop")
@click.argument("session_id")
def session_stop(session_id: str):
    """Stop a running session."""

    async def _stop():
        ctx = await get_remote_context()
        try:
            session = await ctx.session_service.stop_session(session_id)
            if session:
                click.echo(f"Stopped: {session.id} ({session.lifecycle.value})")
            else:
                click.echo(f"Session not found: {session_id}", err=True)
        finally:
            await ctx.close()

    _run(_stop())


@session_group.command("archive")
@click.argument("session_id")
def session_archive(session_id: str):
    """Archive a session."""

    async def _archive():
        ctx = await get_remote_context()
        try:
            session = await ctx.session_service.archive_session(session_id)
            if session:
                click.echo(f"Archived: {session.id}")
            else:
                click.echo(f"Session not found: {session_id}", err=True)
        finally:
            await ctx.close()

    _run(_archive())
