"""Anthropic LLM provider using the anthropic SDK."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import anthropic

from agentbenchplatform.models.provider import LLMConfig, LLMMessage, LLMResponse, ToolCall

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-20250514"


class AnthropicProvider:
    """LLM provider using the Anthropic API."""

    def __init__(self, api_key: str = "", model: str = "") -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key or None)
        self._default_model = model or DEFAULT_MODEL

    def _convert_messages(
        self, messages: list[LLMMessage]
    ) -> tuple[str | None, list[dict]]:
        """Convert LLMMessages to Anthropic format, extracting system prompt."""
        system_prompt = None
        converted = []

        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content
            elif msg.role == "tool":
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": msg.content,
                }
                # Merge consecutive tool results into a single user message
                # to satisfy Anthropic's alternating-roles requirement
                if (
                    converted
                    and converted[-1]["role"] == "user"
                    and isinstance(converted[-1]["content"], list)
                    and converted[-1]["content"]
                    and converted[-1]["content"][0].get("type") == "tool_result"
                ):
                    converted[-1]["content"].append(tool_result)
                else:
                    converted.append({
                        "role": "user",
                        "content": [tool_result],
                    })
            else:
                content = msg.content
                if msg.tool_calls:
                    # Assistant message with tool calls
                    content_blocks: list[dict] = []
                    if msg.content:
                        content_blocks.append({"type": "text", "text": msg.content})
                    for tc in msg.tool_calls:
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["name"],
                            "input": tc.get("arguments", {}),
                        })
                    converted.append({"role": msg.role, "content": content_blocks})
                else:
                    converted.append({"role": msg.role, "content": content})

        return system_prompt, converted

    def _convert_tools(self, tools: list[dict] | None) -> list[dict] | None:
        """Convert tool definitions to Anthropic format."""
        if not tools:
            return None

        anthropic_tools = []
        for tool in tools:
            anthropic_tools.append({
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool.get("parameters", tool.get("input_schema", {})),
            })
        return anthropic_tools

    async def complete(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        """Generate a completion using the Anthropic API."""
        config = config or LLMConfig()
        model = config.model or self._default_model
        system_prompt, converted = self._convert_messages(messages)
        tools = self._convert_tools(config.tools)

        kwargs: dict = {
            "model": model,
            "max_tokens": config.max_tokens,
            "messages": converted,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = tools
        if config.temperature is not None:
            kwargs["temperature"] = config.temperature
        if config.stop_sequences:
            kwargs["stop_sequences"] = config.stop_sequences

        response = await self._client.messages.create(**kwargs)

        # Parse response
        content_text = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=dict(block.input) if block.input else {},
                ))

        return LLMResponse(
            content=content_text,
            model=response.model,
            finish_reason=response.stop_reason or "",
            tool_calls=tool_calls,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> AsyncIterator[str]:
        """Stream a completion from the Anthropic API."""
        config = config or LLMConfig()
        model = config.model or self._default_model
        system_prompt, converted = self._convert_messages(messages)

        kwargs: dict = {
            "model": model,
            "max_tokens": config.max_tokens,
            "messages": converted,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if config.temperature is not None:
            kwargs["temperature"] = config.temperature

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text
