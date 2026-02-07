"""Agent tier routing based on task signals."""

from __future__ import annotations

import re

_JUNIOR_KEYWORDS = re.compile(
    r"\b(fix typo|rename|add comment|format|lint|boilerplate|"
    r"simple|trivial|straightforward)\b",
    re.IGNORECASE,
)

_COMPLEXITY_TO_AGENT = {
    "junior": "claude_local",
    "mid": "opencode",
    "senior": "claude_code",
}

_TAG_JUNIOR = frozenset({"trivial", "boilerplate", "simple"})
_TAG_SENIOR = frozenset({"complex", "architecture", "refactor"})


def recommend_agent(
    prompt: str = "",
    tags: tuple[str, ...] = (),
    complexity: str = "",
) -> str:
    """Return recommended agent backend based on available signals.

    Returns an empty string when no signal is strong enough to decide,
    letting the caller fall through to the config default.
    """
    # Explicit complexity wins
    if complexity and complexity in _COMPLEXITY_TO_AGENT:
        return _COMPLEXITY_TO_AGENT[complexity]

    # Tag-based hints
    tag_set = frozenset(t.lower() for t in tags)
    if tag_set & _TAG_JUNIOR:
        return "claude_local"
    if tag_set & _TAG_SENIOR:
        return "claude_code"

    # Short prompt with simple-task keywords
    if prompt and len(prompt) < 100 and _JUNIOR_KEYWORDS.search(prompt):
        return "claude_local"

    return ""
