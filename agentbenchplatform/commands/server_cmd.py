"""CLI handlers for server commands: start, stop, status."""

from __future__ import annotations

import asyncio
import os
import signal
import sys

import click

from agentbenchplatform.commands._helpers import get_pid_path, get_socket_path


def _run(coro):
    return asyncio.run(coro)


@click.group("server")
def server_group():
    """Manage the background server."""
    pass


@server_group.command("start")
@click.option("--foreground", is_flag=True, help="Run in foreground (for systemd)")
def server_start(foreground: bool):
    """Start the AgentBenchPlatform server."""

    async def _start():
        from agentbenchplatform.context import AppContext
        from agentbenchplatform.infra.rpc.server import RpcServer

        socket_path = get_socket_path()
        pid_path = get_pid_path()

        # Write PID file
        with open(pid_path, "w") as f:
            f.write(str(os.getpid()))

        ctx = AppContext()
        try:
            click.echo(f"Initializing server (pid={os.getpid()})...")
            await ctx.initialize()
            click.echo("MongoDB connected")

            # Start RPC server
            rpc_server = RpcServer(ctx, socket_path)
            await rpc_server.start()
            click.echo(f"RPC server listening on {socket_path}")

            # Start Signal service if configured
            if ctx.config.signal.enabled and ctx.config.signal.auto_start:
                try:
                    await ctx.signal_service.start()
                    click.echo("Signal daemon started")
                except Exception as e:
                    click.echo(f"Signal auto-start failed: {e}", err=True)

            click.echo("Server ready")

            # Wait for shutdown signal
            stop_event = asyncio.Event()

            def _handle_signal(signum, frame):
                click.echo(f"\nReceived signal {signum}, shutting down...")
                stop_event.set()

            signal.signal(signal.SIGTERM, _handle_signal)
            signal.signal(signal.SIGINT, _handle_signal)

            await stop_event.wait()

            # Graceful shutdown
            click.echo("Stopping RPC server...")
            await rpc_server.stop()

            if ctx.config.signal.enabled:
                try:
                    await ctx.signal_service.stop()
                    click.echo("Signal daemon stopped")
                except Exception:
                    pass

        finally:
            await ctx.close()
            # Clean up PID file
            try:
                os.unlink(pid_path)
            except FileNotFoundError:
                pass
            click.echo("Server stopped")

    if not foreground:
        click.echo("Use --foreground for direct execution, or run via systemd:")
        click.echo("  systemctl --user start agentbenchplatform")
        click.echo("\nStarting in foreground mode...")

    _run(_start())


@server_group.command("stop")
def server_stop():
    """Stop the running server."""
    pid_path = get_pid_path()

    try:
        with open(pid_path) as f:
            pid = int(f.read().strip())
    except FileNotFoundError:
        click.echo("Server not running (no PID file found)")
        return
    except ValueError:
        click.echo("Invalid PID file", err=True)
        return

    try:
        os.kill(pid, signal.SIGTERM)
        click.echo(f"Sent SIGTERM to server (pid={pid})")
    except ProcessLookupError:
        click.echo("Server process not found (stale PID file)")
        try:
            os.unlink(pid_path)
        except FileNotFoundError:
            pass


@server_group.command("status")
def server_status():
    """Check if the server is running."""

    async def _status():
        from agentbenchplatform.infra.rpc.client import RpcClient

        socket_path = get_socket_path()
        client = RpcClient(socket_path)
        try:
            await client.connect()
            result = await client.call("server.status")
            click.echo("Server: running")
            if isinstance(result, dict):
                for key, value in result.items():
                    click.echo(f"  {key}: {value}")
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            click.echo("Server: not running")

            # Check for stale PID file
            pid_path = get_pid_path()
            try:
                with open(pid_path) as f:
                    pid = int(f.read().strip())
                try:
                    os.kill(pid, 0)
                    click.echo(f"  PID {pid} exists but not accepting connections")
                except ProcessLookupError:
                    click.echo(f"  Stale PID file found (pid={pid})")
            except (FileNotFoundError, ValueError):
                pass
        finally:
            await client.close()

    _run(_status())
