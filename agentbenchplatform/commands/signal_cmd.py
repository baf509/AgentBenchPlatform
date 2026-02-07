"""CLI handlers for signal commands."""

from __future__ import annotations

import asyncio

import click

from agentbenchplatform.commands._helpers import get_remote_context


def _run(coro):
    return asyncio.run(coro)


@click.group("signal")
def signal_group():
    """Manage Signal messenger integration."""
    pass


@signal_group.command("start")
def signal_start():
    """Start the Signal daemon on the server."""

    async def _start():
        ctx = await get_remote_context()
        try:
            await ctx.signal_service.start()
            click.echo("Signal daemon started (on server)")
        finally:
            await ctx.close()

    _run(_start())


@signal_group.command("stop")
def signal_stop():
    """Stop the Signal daemon on the server."""

    async def _stop():
        ctx = await get_remote_context()
        try:
            await ctx.signal_service.stop()
            click.echo("Signal daemon stopped.")
        finally:
            await ctx.close()

    _run(_stop())


@signal_group.command("status")
def signal_status():
    """Show Signal daemon status."""

    async def _status():
        ctx = await get_remote_context()
        try:
            info = await ctx.signal_service.status()
            for key, value in info.items():
                click.echo(f"  {key}: {value}")
        finally:
            await ctx.close()

    _run(_status())


@signal_group.command("pair")
@click.argument("phone")
def signal_pair(phone: str):
    """Add a sender to the allowlist.

    For persistent allowlisting, use the config instead:
    abp config set signal.allowed_senders '["UUID-OR-PHONE"]'
    """

    async def _pair():
        ctx = await get_remote_context()
        try:
            await ctx.signal_service.pair_sender(phone)
            click.echo(f"Paired sender: {phone}")
        finally:
            await ctx.close()

    _run(_pair())
