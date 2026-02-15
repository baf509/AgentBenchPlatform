"""Coordinator decision domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class ToolCallRecord:
    """Record of a single tool call within a coordinator turn."""

    name: str
    arguments: dict = field(default_factory=dict)
    result_summary: str = ""
    duration_ms: int = 0

    def to_doc(self) -> dict:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "result_summary": self.result_summary,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_doc(cls, doc: dict) -> ToolCallRecord:
        return cls(
            name=doc["name"],
            arguments=doc.get("arguments", {}),
            result_summary=doc.get("result_summary", ""),
            duration_ms=doc.get("duration_ms", 0),
        )


@dataclass(frozen=True)
class CoordinatorDecision:
    """Record of a complete coordinator interaction turn."""

    conversation_key: str
    turn_number: int
    user_input: str
    tools_called: tuple[ToolCallRecord, ...] = ()
    reasoning_excerpt: str = ""
    final_response: str = ""
    tokens: dict = field(default_factory=dict)
    model: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str | None = None

    def to_doc(self) -> dict:
        doc: dict = {
            "conversation_key": self.conversation_key,
            "turn_number": self.turn_number,
            "user_input": self.user_input,
            "tools_called": [tc.to_doc() for tc in self.tools_called],
            "reasoning_excerpt": self.reasoning_excerpt,
            "final_response": self.final_response,
            "tokens": self.tokens,
            "model": self.model,
            "timestamp": self.timestamp,
        }
        if self.id:
            doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> CoordinatorDecision:
        return cls(
            id=str(doc["_id"]),
            conversation_key=doc["conversation_key"],
            turn_number=doc.get("turn_number", 0),
            user_input=doc.get("user_input", ""),
            tools_called=tuple(
                ToolCallRecord.from_doc(tc)
                for tc in doc.get("tools_called", [])
            ),
            reasoning_excerpt=doc.get("reasoning_excerpt", ""),
            final_response=doc.get("final_response", ""),
            tokens=doc.get("tokens", {}),
            model=doc.get("model", ""),
            timestamp=doc.get("timestamp", datetime.now(timezone.utc)),
        )
