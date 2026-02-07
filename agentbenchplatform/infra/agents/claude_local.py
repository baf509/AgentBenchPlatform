"""Claude Code + local llama.cpp subprocess backend."""

from __future__ import annotations

import logging
import os

from agentbenchplatform.models.agent import CommandSpec, StartParams

logger = logging.getLogger(__name__)

# Default model served by the local llama.cpp instance
# Use an Anthropic model alias that Claude Code recognizes to pass validation.
# The actual model loaded in llama.cpp will handle the request.
DEFAULT_MODEL = "claude-sonnet-4-20250514"


class ClaudeLocalBackend:
    """Backend for Claude Code CLI pointed at a local llama.cpp server.

    Launches the standard ``claude`` CLI with environment variables that
    redirect it to the local llama.cpp OpenAI-compatible endpoint::

        ANTHROPIC_BASE_URL=http://localhost:8080
        ANTHROPIC_AUTH_TOKEN=local
        ANTHROPIC_API_KEY=

    The model flag is set to the alias of the model loaded in llama-server.
    """

    def __init__(self, base_url: str = "") -> None:
        self._base_url = base_url or os.environ.get(
            "LLAMACPP_BASE_URL", "http://corsair-ai.tailb286a5.ts.net:8080"
        )

    def _build_env(self, params: StartParams) -> dict[str, str]:
        """Build env dict that points Claude Code at the local server."""
        env: dict[str, str] = {}
        if params.env_vars:
            env.update(params.env_vars)
        env["ANTHROPIC_BASE_URL"] = self._base_url
        env["ANTHROPIC_AUTH_TOKEN"] = "local"
        env["ANTHROPIC_API_KEY"] = ""
        return env

    def start_command(self, params: StartParams) -> CommandSpec:
        """Generate command to start Claude Code against local llama.cpp."""
        args: list[str] = ["--permission-mode", "bypassPermissions"]

        if params.session_id:
            args.extend(["--session-id", params.session_id])

        model = params.model or DEFAULT_MODEL
        args.extend(["--model", model])

        if params.prompt:
            args.append(params.prompt)

        return CommandSpec(
            program="claude",
            args=tuple(args),
            env=self._build_env(params),
            cwd=params.workspace_path or None,
        )

    def resume_command(self, session_id: str, params: StartParams) -> CommandSpec:
        """Generate command to resume a Claude Code session on local llama.cpp."""
        args = ["--permission-mode", "bypassPermissions", "--resume", session_id]

        model = params.model or DEFAULT_MODEL
        args.extend(["--model", model])

        return CommandSpec(
            program="claude",
            args=tuple(args),
            env=self._build_env(params),
            cwd=params.workspace_path or None,
        )

    def matches_process(self, cmdline: str) -> bool:
        """Check if a command line is a Claude Code local process."""
        return "claude" in cmdline and "ANTHROPIC_BASE_URL" in cmdline

    def discover_sessions(self, cutoff: int | None = None) -> list[dict]:
        """Discover existing local Claude Code sessions.

        Note: This is a stub implementation. Full session discovery would require:
        - Reading Claude Code's session storage (~/.claude/sessions)
        - Identifying sessions that used ANTHROPIC_BASE_URL override
        - Parsing session metadata
        - Filtering by cutoff timestamp if provided

        Returns:
            Empty list. Session discovery not yet implemented.
        """
        logger.debug("Session discovery not implemented for ClaudeLocal backend")
        return []
