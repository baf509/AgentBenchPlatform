"""LLM provider domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ProviderType(str, Enum):
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"
    LLAMACPP = "llamacpp"


@dataclass(frozen=True)
class LLMMessage:
    """A single message in a conversation."""

    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_call_id: str = ""
    tool_calls: list[dict] | None = None
    name: str = ""

    def to_dict(self) -> dict:
        d: dict = {"role": self.role, "content": self.content}
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.name:
            d["name"] = self.name
        return d


@dataclass(frozen=True)
class LLMConfig:
    """Configuration for an LLM completion request."""

    model: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    tools: list[dict] | None = None
    stop_sequences: list[str] | None = None
    provider_order: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolCall:
    """A tool call from the LLM."""

    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    """Response from an LLM provider."""

    content: str
    model: str = ""
    finish_reason: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0
