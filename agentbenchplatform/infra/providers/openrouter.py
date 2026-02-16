"""OpenRouter LLM provider using httpx."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from agentbenchplatform.models.provider import LLMConfig, LLMMessage, LLMResponse, ToolCall

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4"


class OpenRouterProvider:
    """LLM provider using the OpenRouter API (OpenAI-compatible)."""

    def __init__(self, api_key: str = "", model: str = "") -> None:
        self._api_key = api_key
        self._default_model = model or DEFAULT_MODEL
        self._client = httpx.AsyncClient(
            base_url=OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/agentbench",
            },
            timeout=120.0,
        )

    @staticmethod
    def _convert_message(msg: LLMMessage) -> dict:
        """Convert an LLMMessage to OpenAI-compatible format.

        Handles the tool_calls format difference: internal format uses flat
        {id, name, arguments: dict}, but OpenAI requires nested
        {id, type, function: {name, arguments: json_string}}.
        """
        d = msg.to_dict()

        if msg.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": json.dumps(tc.get("arguments", {})),
                    },
                }
                for tc in msg.tool_calls
            ]
            # OpenAI expects null content when there are tool_calls with no text
            if not msg.content:
                d["content"] = None

        # Strip 'name' from tool messages - not standard in OpenAI format
        if msg.role == "tool" and "name" in d:
            del d["name"]

        return d

    def _resolve_model(self, model: str) -> str:
        """Use the given model if it looks like an OpenRouter model, else default.

        OpenRouter models use 'provider/model' format (e.g. 'anthropic/claude-sonnet-4').
        Local model names like 'foo.gguf' aren't valid here.
        """
        if model and "/" in model:
            return model
        return self._default_model

    async def complete(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        """Generate a completion via OpenRouter."""
        config = config or LLMConfig()
        model = self._resolve_model(config.model)

        payload: dict = {
            "model": model,
            "messages": [self._convert_message(m) for m in messages],
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
        }
        if config.tools:
            payload["tools"] = [{"type": "function", "function": t} for t in config.tools]
        if config.stop_sequences:
            payload["stop"] = config.stop_sequences

        logger.debug("Sending request to OpenRouter with model: %s", model)
        response = await self._client.post("/chat/completions", json=payload)
        logger.debug("OpenRouter response status: %s", response.status_code)
        response.raise_for_status()
        data = response.json()
        logger.debug("OpenRouter response received, model: %s", data.get("model", "unknown"))

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
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", ""),
                        name=func.get("name", ""),
                        arguments=args,
                    )
                )

        # Map OpenAI-style usage keys to expected format
        raw_usage = data.get("usage", {})
        usage = {
            "input_tokens": raw_usage.get("prompt_tokens", 0),
            "output_tokens": raw_usage.get("completion_tokens", 0),
        }

        return LLMResponse(
            content=message.get("content", "") or "",
            model=data.get("model", model),
            finish_reason=choice.get("finish_reason", ""),
            tool_calls=tool_calls,
            usage=usage,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def stream(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> AsyncIterator[str]:
        """Stream a completion via OpenRouter."""
        config = config or LLMConfig()
        model = self._resolve_model(config.model)

        payload: dict = {
            "model": model,
            "messages": [self._convert_message(m) for m in messages],
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "stream": True,
        }
        if config.tools:
            payload["tools"] = [{"type": "function", "function": t} for t in config.tools]
        if config.stop_sequences:
            payload["stop"] = config.stop_sequences

        async with self._client.stream("POST", "/chat/completions", json=payload) as response:
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
