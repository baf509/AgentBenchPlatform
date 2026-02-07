"""CLI handlers for coordinator commands."""

from __future__ import annotations

import asyncio

import click

from agentbenchplatform.commands._helpers import get_remote_context


def _run(coro):
    return asyncio.run(coro)


@click.group("coordinator")
def coordinator_group():
    """Interact with the coordinator agent."""
    pass


@coordinator_group.command("chat")
def coordinator_chat():
    """Interactive chat with the coordinator agent."""

    def _cli_progress(text: str) -> None:
        if text.startswith("[tool]"):
            click.echo(click.style(f"  >> {text[7:]}", dim=True))
        else:
            click.echo(click.style(f"  {text}", dim=True))

    async def _chat():
        ctx = await get_remote_context()
        try:
            click.echo("Coordinator chat (type 'quit' to exit)")
            click.echo("=" * 50)
            while True:
                try:
                    user_input = click.prompt("You", prompt_suffix="> ")
                except (EOFError, KeyboardInterrupt):
                    break

                if user_input.lower() in ("quit", "exit", "q"):
                    break

                response = await ctx.coordinator_service.handle_message(
                    user_message=user_input,
                    channel="cli",
                    on_progress=_cli_progress,
                )
                click.echo(f"\nCoordinator: {response}\n")
        finally:
            await ctx.close()

    _run(_chat())


@coordinator_group.command("ask")
@click.argument("question")
def coordinator_ask(question: str):
    """One-shot question to the coordinator."""

    async def _ask():
        ctx = await get_remote_context()
        try:
            response = await ctx.coordinator_service.ask(question)
            click.echo(response)
        finally:
            await ctx.close()

    _run(_ask())
