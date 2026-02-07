"""Fallback LLM provider that tries multiple providers in order."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from agentbenchplatform.models.provider import LLMConfig, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)


class FallbackProvider:
    """Wraps multiple LLM providers, trying each in order until one succeeds.

    Usage:
        provider = FallbackProvider([anthropic_provider, openrouter_provider, llamacpp_provider])
        response = await provider.complete(messages)  # tries anthropic first, then openrouter, etc.
    """

    def __init__(self, providers: list, names: list[str] | None = None) -> None:
        if not providers:
            raise ValueError("FallbackProvider requires at least one provider")
        self._providers = providers
        self._names = names or [f"provider-{i}" for i in range(len(providers))]

    async def complete(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        """Try each provider in order. Return the first successful response."""
        last_error: Exception | None = None

        for provider, name in zip(self._providers, self._names):
            try:
                response = await provider.complete(messages, config)
                return response
            except Exception as e:
                last_error = e
                logger.warning("Provider '%s' failed: %s. Trying next...", name, e)

        raise RuntimeError(
            f"All {len(self._providers)} providers failed. Last error: {last_error}"
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> AsyncIterator[str]:
        """Try each provider in order for streaming."""
        last_error: Exception | None = None

        for provider, name in zip(self._providers, self._names):
            try:
                async for chunk in provider.stream(messages, config):
                    yield chunk
                return
            except Exception as e:
                last_error = e
                logger.warning("Provider '%s' stream failed: %s. Trying next...", name, e)

        raise RuntimeError(
            f"All {len(self._providers)} providers failed. Last error: {last_error}"
        )
