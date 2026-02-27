"""Async HTTP client for whisper.cpp server (speech-to-text)."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class WhisperClient:
    """Client for the whisper.cpp HTTP server."""

    def __init__(self, base_url: str = "http://localhost:8081") -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=120.0)

    async def transcribe(self, audio_path: Path) -> str:
        """Transcribe an audio file via the whisper.cpp server.

        Args:
            audio_path: Path to the audio file (any format ffmpeg supports).

        Returns:
            Transcribed text.
        """
        with open(audio_path, "rb") as f:
            response = await self._client.post(
                "/v1/audio/transcriptions",
                files={"file": (audio_path.name, f, "application/octet-stream")},
            )
        response.raise_for_status()
        data = response.json()
        return data.get("text", "").strip()

    async def health(self) -> bool:
        """Check if the whisper server is healthy."""
        try:
            response = await self._client.get("/health")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        await self._client.aclose()
