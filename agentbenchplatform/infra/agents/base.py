"""Agent backend protocol definition."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agentbenchplatform.models.agent import CommandSpec, StartParams


@runtime_checkable
class AgentBackend(Protocol):
    """Protocol for agent subprocess backends.

    Each backend knows how to produce CommandSpec for starting/resuming
    a coding agent, and how to identify running processes belonging to it.
    """

    def start_command(self, params: StartParams) -> CommandSpec:
        """Generate command to start a new agent session."""
        ...

    def resume_command(self, session_id: str, params: StartParams) -> CommandSpec:
        """Generate command to resume an existing agent session."""
        ...

    def matches_process(self, cmdline: str) -> bool:
        """Check if a process command line belongs to this agent backend."""
        ...

    def discover_sessions(self, cutoff: int | None = None) -> list[dict]:
        """Discover existing sessions for this agent type."""
        ...
