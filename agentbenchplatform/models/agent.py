"""Agent backend domain models."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum


class AgentBackendType(str, Enum):
    CLAUDE_CODE = "claude_code"
    OPENCODE = "opencode"
    CLAUDE_LOCAL = "claude_local"


@dataclass(frozen=True)
class CommandSpec:
    """Specification for launching an agent subprocess."""

    program: str
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    cwd: str | None = None

    @property
    def full_command(self) -> str:
        """Return the full command string for shell execution."""
        parts = [self.program, *self.args]
        return " ".join(shlex.quote(p) for p in parts)


@dataclass(frozen=True)
class StartParams:
    """Parameters for starting or resuming an agent session."""

    prompt: str = ""
    model: str = ""
    workspace_path: str = ""
    session_id: str = ""
    env_vars: dict[str, str] | None = None


@dataclass(frozen=True)
class AgentConfig:
    """Configuration for an agent backend."""

    backend_type: AgentBackendType
    default_model: str = ""
    extra_args: tuple[str, ...] = ()
