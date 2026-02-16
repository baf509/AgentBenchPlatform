"""OpenCode + local llama.cpp subprocess backend."""

from __future__ import annotations

import logging

from agentbenchplatform.models.agent import CommandSpec, StartParams

logger = logging.getLogger(__name__)


class OpenCodeLocalBackend:
    """Backend for OpenCode CLI pointed at a local llama.cpp server.

    Relies on the user's global ``~/.config/opencode/opencode.json`` having a
    llama.cpp provider defined.  The ``--model`` flag selects the
    ``provider_id/model_id`` combination (e.g. ``llama.cpp/step3p5-flash``).

    No env-var hacks — OpenCode handles the provider connection natively.
    """

    def __init__(self, model: str = "") -> None:
        self._model = model or "llama.cpp/step3p5-flash"

    def start_command(self, params: StartParams) -> CommandSpec:
        """Generate command to start OpenCode against local llama.cpp."""
        args: list[str] = []

        if params.session_id:
            args.extend(["--session", params.session_id])

        model = params.model or self._model
        args.extend(["--model", model])

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
        """Generate command to resume an OpenCode session on local llama.cpp."""
        args = ["--session", session_id]

        model = params.model or self._model
        args.extend(["--model", model])

        env = dict(params.env_vars) if params.env_vars else None

        return CommandSpec(
            program="opencode",
            args=tuple(args),
            env=env,
            cwd=params.workspace_path or None,
        )

    def matches_process(self, cmdline: str) -> bool:
        """Check if a command line is an OpenCode local process."""
        return "opencode" in cmdline and self._model in cmdline

    def discover_sessions(self, cutoff: int | None = None) -> list[dict]:
        """Discover existing OpenCode local sessions.

        Returns:
            Empty list. Session discovery not yet implemented.
        """
        logger.debug("Session discovery not implemented for OpenCodeLocal backend")
        return []
