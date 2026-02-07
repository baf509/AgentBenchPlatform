"""Agent backend factory/registry."""

from __future__ import annotations

from agentbenchplatform.infra.agents.base import AgentBackend
from agentbenchplatform.infra.agents.claude_code import ClaudeCodeBackend
from agentbenchplatform.infra.agents.claude_local import ClaudeLocalBackend
from agentbenchplatform.infra.agents.opencode import OpenCodeBackend
from agentbenchplatform.models.agent import AgentBackendType

_BACKENDS: dict[AgentBackendType, type] = {
    AgentBackendType.CLAUDE_CODE: ClaudeCodeBackend,
    AgentBackendType.OPENCODE: OpenCodeBackend,
    AgentBackendType.CLAUDE_LOCAL: ClaudeLocalBackend,
}


def get_backend(
    backend_type: AgentBackendType | str, **kwargs
) -> AgentBackend:
    """Get an agent backend instance by type.

    Extra kwargs are forwarded to backends that accept them
    (e.g. ``base_url`` for ClaudeLocalBackend).
    """
    if isinstance(backend_type, str):
        backend_type = AgentBackendType(backend_type)

    cls = _BACKENDS.get(backend_type)
    if cls is None:
        raise ValueError(f"Unknown agent backend type: {backend_type}")

    if backend_type == AgentBackendType.CLAUDE_LOCAL and "base_url" in kwargs:
        return cls(base_url=kwargs["base_url"])
    return cls()
