"""Click CLI definitions - main entry point."""

from __future__ import annotations

import asyncio
import logging
import sys

import click

from agentbenchplatform.commands.config_cmd import config_group
from agentbenchplatform.commands.coordinator_cmd import coordinator_group
from agentbenchplatform.commands.dashboard_cmd import dashboard_command
from agentbenchplatform.commands.memory_cmd import memory_group
from agentbenchplatform.commands.research_cmd import research_group
from agentbenchplatform.commands.server_cmd import server_group
from agentbenchplatform.commands.session_cmd import session_group
from agentbenchplatform.commands.signal_cmd import signal_group
from agentbenchplatform.commands.task_cmd import task_group


def _run(coro):
    """Run an async function from sync context."""
    return asyncio.run(coro)


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx, debug: bool) -> None:
    """agentbenchplatform - Agent workbench with persistent server."""
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug


cli.add_command(task_group, "task")
cli.add_command(session_group, "session")
cli.add_command(research_group, "research")
cli.add_command(memory_group, "memory")
cli.add_command(coordinator_group, "coordinator")
cli.add_command(config_group, "config")
cli.add_command(signal_group, "signal")
cli.add_command(server_group, "server")
cli.add_command(dashboard_command, "dashboard")


if __name__ == "__main__":
    cli()
