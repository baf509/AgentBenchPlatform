"""llama.cpp LLM provider using httpx (OpenAI-compatible endpoint)."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from agentbenchplatform.models.provider import LLMConfig, LLMMessage, LLMResponse, ToolCall

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8080"


class LlamaCppProvider:
    """LLM provider for local llama.cpp server (OpenAI-compatible API).

    Also provides embedding generation via /v1/embeddings.
    """

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=300.0,
        )

    async def complete(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        """Generate a completion via local llama.cpp server."""
        config = config or LLMConfig()

        payload: dict = {
            "messages": [m.to_dict() for m in messages],
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
        }
        if config.model:
            payload["model"] = config.model
        if config.tools:
            payload["tools"] = [
                {"type": "function", "function": t} for t in config.tools
            ]
        if config.stop_sequences:
            payload["stop"] = config.stop_sequences

        response = await self._client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        message = choice["message"]

        tool_calls = []
        if raw_calls := message.get("tool_calls"):
            for tc in raw_calls:
                func = tc.get("function", {})
                args = func.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=args,
                ))

        # Map OpenAI-style usage keys to expected format
        raw_usage = data.get("usage", {})
        usage = {
            "input_tokens": raw_usage.get("prompt_tokens", 0),
            "output_tokens": raw_usage.get("completion_tokens", 0),
        }

        return LLMResponse(
            content=message.get("content", "") or "",
            model=data.get("model", ""),
            finish_reason=choice.get("finish_reason", ""),
            tool_calls=tool_calls,
            usage=usage,
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> AsyncIterator[str]:
        """Stream a completion via local llama.cpp server."""
        config = config or LLMConfig()

        payload: dict = {
            "messages": [m.to_dict() for m in messages],
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "stream": True,
        }
        if config.model:
            payload["model"] = config.model

        async with self._client.stream(
            "POST", "/v1/chat/completions", json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        if content := delta.get("content"):
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings via /v1/embeddings endpoint."""
        payload = {"input": texts}
        response = await self._client.post("/v1/embeddings", json=payload)
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in data["data"]]

    async def health_check(self) -> bool:
        """Check if the llama.cpp server is reachable."""
        try:
            response = await self._client.get("/health")
            return response.status_code == 200
        except httpx.ConnectError:
            return False
