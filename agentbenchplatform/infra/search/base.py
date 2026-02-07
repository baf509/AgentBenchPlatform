"""Search provider protocol definition."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agentbenchplatform.models.research import SearchResult


@runtime_checkable
class SearchProvider(Protocol):
    """Protocol for web search providers."""

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Execute a web search and return results."""
        ...
