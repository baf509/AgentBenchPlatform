"""CLI helpers for connecting to the RPC server."""

from __future__ import annotations

from agentbenchplatform.config import load_config


def get_socket_path() -> str:
    """Return the socket path from config or default."""
    config = load_config()
    return config.server.resolved_socket_path


def get_pid_path() -> str:
    """Return the PID file path from config or default."""
    config = load_config()
    return config.server.resolved_pid_file


async def get_remote_context():
    """Create and connect a RemoteContext. Raises if server not running."""
    from agentbenchplatform.remote_context import RemoteContext

    socket_path = get_socket_path()
    ctx = RemoteContext(socket_path)
    try:
        await ctx.initialize()
    except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
        raise SystemExit(
            "Server not running. Start with: agentbenchplatform server start"
        ) from e
    return ctx
