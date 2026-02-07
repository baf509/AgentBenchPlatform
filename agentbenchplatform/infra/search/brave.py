"""Brave Search provider."""

from __future__ import annotations

import logging

import httpx

from agentbenchplatform.models.research import SearchResult

logger = logging.getLogger(__name__)

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchProvider:
    """Web search provider using the Brave Search API."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=BRAVE_API_URL,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
            timeout=30.0,
        )

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Execute a search via Brave Search API."""
        params = {
            "q": query,
            "count": min(max_results, 20),  # Brave max is 20 per request
            "extra_snippets": True,
        }

        try:
            response = await self._client.get("", params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            logger.error("Brave search failed: %s", e)
            return []

        results = []
        web = data.get("web", {})
        for item in web.get("results", []):
            # Combine description with extra snippets for richer content
            description = item.get("description", "")
            extra = item.get("extra_snippets", [])
            if extra:
                description = description + "\n" + "\n".join(extra)

            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                content=description,
                score=0.0,
            ))

        return results[:max_results]
