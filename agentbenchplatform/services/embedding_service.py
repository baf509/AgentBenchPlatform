"""Embedding service: generates embeddings via llama.cpp."""

from __future__ import annotations

import logging

import httpx

from agentbenchplatform.config import EmbeddingsConfig

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Generates text embeddings via llama.cpp /v1/embeddings endpoint."""

    def __init__(self, config: EmbeddingsConfig) -> None:
        self._base_url = config.base_url.rstrip("/")
        self._dimensions = config.dimensions
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=60.0,
        )
        self._available: bool | None = None

    async def embed(self, text: str) -> list[float] | None:
        """Generate embedding for a single text.

        Returns None if embedding service is unavailable.
        """
        result = await self.embed_batch([text])
        return result[0] if result else None

    async def embed_batch(self, texts: list[str]) -> list[list[float]] | None:
        """Generate embeddings for multiple texts.

        Returns None if embedding service is unavailable.
        """
        if self._available is False:
            return None

        try:
            response = await self._client.post(
                "/v1/embeddings",
                json={"input": texts},
            )
            response.raise_for_status()
            data = response.json()
            self._available = True
            return [item["embedding"] for item in data["data"]]
        except httpx.ConnectError:
            if self._available is not False:
                logger.warning(
                    "Embedding service unavailable at %s. "
                    "Memories will be stored without embeddings.",
                    self._base_url,
                )
            self._available = False
            return None
        except httpx.HTTPError as e:
            logger.error("Embedding request failed: %s", e)
            return None

    async def health_check(self) -> bool:
        """Check if the embedding service is reachable."""
        try:
            response = await self._client.get("/health")
            self._available = response.status_code == 200
            return self._available
        except httpx.ConnectError:
            self._available = False
            return False
