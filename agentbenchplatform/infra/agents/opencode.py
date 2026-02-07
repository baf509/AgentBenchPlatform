"""OpenCode subprocess backend."""

from __future__ import annotations

import logging

from agentbenchplatform.models.agent import CommandSpec, StartParams

logger = logging.getLogger(__name__)


class OpenCodeBackend:
    """Backend for OpenCode CLI agent.

    Generates commands like:
        opencode [--session UUID] [--model MODEL] [--prompt "..."]
    """

    def start_command(self, params: StartParams) -> CommandSpec:
        """Generate command to start a new OpenCode session."""
        args: list[str] = []

        if params.session_id:
            args.extend(["--session", params.session_id])

        if params.model:
            args.extend(["--model", params.model])

        if params.prompt:
            args.extend(["--prompt", params.prompt])

        env = dict(params.env_vars) if params.env_vars else None

        return CommandSpec(
            program="opencode",
            args=tuple(args),
            env=env,
            cwd=params.workspace_path or None,
        )

    def resume_command(self, session_id: str, params: StartParams) -> CommandSpec:
        """Generate command to resume an OpenCode session."""
        args = ["--session", session_id]

        if params.model:
            args.extend(["--model", params.model])

        env = dict(params.env_vars) if params.env_vars else None

        return CommandSpec(
            program="opencode",
            args=tuple(args),
            env=env,
            cwd=params.workspace_path or None,
        )

    def matches_process(self, cmdline: str) -> bool:
        """Check if a command line is an OpenCode process."""
        return "opencode" in cmdline

    def discover_sessions(self, cutoff: int | None = None) -> list[dict]:
        """Discover existing OpenCode sessions.

        Note: This is a stub implementation. Full session discovery would require:
        - Reading OpenCode's session storage
        - Parsing session metadata
        - Filtering by cutoff timestamp if provided

        Returns:
            Empty list. Session discovery not yet implemented.
        """
        logger.debug("Session discovery not implemented for OpenCode backend")
        return []
