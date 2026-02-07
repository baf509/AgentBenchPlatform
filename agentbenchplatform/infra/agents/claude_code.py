"""Claude Code subprocess backend."""

from __future__ import annotations

import logging

from agentbenchplatform.models.agent import CommandSpec, StartParams

logger = logging.getLogger(__name__)


class ClaudeCodeBackend:
    """Backend for Claude Code CLI agent.

    Generates commands like:
        claude [--session-id UUID] [prompt]
        claude --resume UUID
    """

    def start_command(self, params: StartParams) -> CommandSpec:
        """Generate command to start a new Claude Code session."""
        args: list[str] = ["--permission-mode", "bypassPermissions"]

        if params.session_id:
            args.extend(["--session-id", params.session_id])

        if params.model:
            args.extend(["--model", params.model])

        if params.prompt:
            args.append(params.prompt)

        env = dict(params.env_vars) if params.env_vars else None

        return CommandSpec(
            program="claude",
            args=tuple(args),
            env=env,
            cwd=params.workspace_path or None,
        )

    def resume_command(self, session_id: str, params: StartParams) -> CommandSpec:
        """Generate command to resume a Claude Code session."""
        args = ["--permission-mode", "bypassPermissions", "--resume", session_id]

        if params.model:
            args.extend(["--model", params.model])

        env = dict(params.env_vars) if params.env_vars else None

        return CommandSpec(
            program="claude",
            args=tuple(args),
            env=env,
            cwd=params.workspace_path or None,
        )

    def matches_process(self, cmdline: str) -> bool:
        """Check if a command line is a Claude Code process."""
        return "claude" in cmdline and "claude-code" not in cmdline.lower()

    def discover_sessions(self, cutoff: int | None = None) -> list[dict]:
        """Discover existing Claude Code sessions.

        Claude Code stores sessions locally; discovery scans for running
        processes matching the claude CLI pattern.

        Note: This is a stub implementation. Full session discovery would require:
        - Reading Claude Code's session storage (~/.claude/sessions)
        - Parsing session metadata and history
        - Filtering by cutoff timestamp if provided

        Returns:
            Empty list. Session discovery not yet implemented.
        """
        logger.debug("Session discovery not implemented for Claude Code backend")
        return []
