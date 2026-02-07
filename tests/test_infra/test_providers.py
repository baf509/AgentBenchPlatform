"""Tests for provider registry."""

import pytest

from agentbenchplatform.config import AppConfig, ProviderConfig
from agentbenchplatform.infra.providers.anthropic import AnthropicProvider
from agentbenchplatform.infra.providers.llamacpp import LlamaCppProvider
from agentbenchplatform.infra.providers.openrouter import OpenRouterProvider
from agentbenchplatform.infra.providers.registry import get_provider
from agentbenchplatform.models.provider import ProviderType


class TestProviderRegistry:
    def _make_config(self) -> AppConfig:
        return AppConfig(
            providers={
                "anthropic": ProviderConfig(api_key="test-key", default_model="test-model"),
                "openrouter": ProviderConfig(api_key="or-key", default_model="or-model"),
                "llamacpp": ProviderConfig(base_url="http://localhost:9999"),
            }
        )

    def test_get_anthropic(self):
        provider = get_provider(ProviderType.ANTHROPIC, self._make_config())
        assert isinstance(provider, AnthropicProvider)

    def test_get_openrouter(self):
        provider = get_provider(ProviderType.OPENROUTER, self._make_config())
        assert isinstance(provider, OpenRouterProvider)

    def test_get_llamacpp(self):
        provider = get_provider(ProviderType.LLAMACPP, self._make_config())
        assert isinstance(provider, LlamaCppProvider)

    def test_get_by_string(self):
        provider = get_provider("anthropic", self._make_config())
        assert isinstance(provider, AnthropicProvider)

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            get_provider("nonexistent", self._make_config())
