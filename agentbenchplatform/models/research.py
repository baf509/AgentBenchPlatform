"""Research domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class ResearchConfig:
    """Configuration for a research run."""

    query: str
    breadth: int = 4
    depth: int = 3
    provider: str = "anthropic"
    model: str = ""
    search_provider: str = "brave"

    def __post_init__(self) -> None:
        if not self.query:
            raise ValueError("Research query cannot be empty")
        if self.breadth < 1:
            raise ValueError("Research breadth must be >= 1")
        if self.depth < 1:
            raise ValueError("Research depth must be >= 1")


@dataclass(frozen=True)
class Learning:
    """Atomic fact extracted during research."""

    content: str
    source_url: str = ""
    confidence: float = 1.0
    depth_found: int = 0

    def __post_init__(self) -> None:
        if not self.content:
            raise ValueError("Learning content cannot be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")


@dataclass(frozen=True)
class SearchResult:
    """A single search result from a search provider."""

    title: str
    url: str
    content: str
    score: float = 0.0


@dataclass(frozen=True)
class ResearchReport:
    """Final compiled research report."""

    query: str
    report_text: str
    learnings: tuple[Learning, ...] = ()
    sources: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
