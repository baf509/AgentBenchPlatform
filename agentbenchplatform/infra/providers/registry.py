"""LLM provider factory/registry."""

from __future__ import annotations

import logging

import httpx

from agentbenchplatform.config import AppConfig
from agentbenchplatform.infra.providers.anthropic import AnthropicProvider
from agentbenchplatform.infra.providers.base import LLMProvider
from agentbenchplatform.infra.providers.fallback import FallbackProvider
from agentbenchplatform.infra.providers.llamacpp import LlamaCppProvider
from agentbenchplatform.infra.providers.openrouter import OpenRouterProvider
from agentbenchplatform.models.provider import ProviderType

logger = logging.getLogger(__name__)


def _check_llamacpp_available(base_url: str) -> bool:
    """Check if llama.cpp server is reachable (synchronous)."""
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(f"{base_url.rstrip('/')}/health")
            return response.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


def _build_provider(provider_type: ProviderType, config: AppConfig) -> LLMProvider:
    """Build a single provider instance."""
    if provider_type == ProviderType.ANTHROPIC:
        prov_config = config.providers.get("anthropic")
        return AnthropicProvider(
            api_key=prov_config.api_key if prov_config else "",
            model=prov_config.default_model if prov_config else "",
        )
    elif provider_type == ProviderType.OPENROUTER:
        prov_config = config.providers.get("openrouter")
        return OpenRouterProvider(
            api_key=prov_config.api_key if prov_config else "",
            model=prov_config.default_model if prov_config else "",
        )
    elif provider_type == ProviderType.LLAMACPP:
        prov_config = config.providers.get("llamacpp")
        return LlamaCppProvider(
            base_url=prov_config.base_url if prov_config else "http://localhost:8012",
        )
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")


def get_provider(provider_type: ProviderType | str, config: AppConfig) -> LLMProvider:
    """Get an LLM provider instance by type, configured from AppConfig."""
    if isinstance(provider_type, str):
        provider_type = ProviderType(provider_type)
    return _build_provider(provider_type, config)


def get_provider_with_fallback(config: AppConfig, primary: str = "") -> LLMProvider:
    """Build a provider with automatic fallback through all configured providers.

    Tries the primary provider first, then falls back through any other
    providers that have API keys configured. Skips providers without keys.

    Args:
        config: App configuration.
        primary: Primary provider name (e.g. "openrouter"). If empty,
                 uses coordinator.provider from config.

    Returns:
        A FallbackProvider wrapping all available providers, or a single
        provider if only one is available.
    """
    primary = primary or config.coordinator.provider

    # Determine order: primary first, then the rest
    all_types = [ProviderType.ANTHROPIC, ProviderType.OPENROUTER, ProviderType.LLAMACPP]
    try:
        primary_type = ProviderType(primary)
    except ValueError:
        primary_type = ProviderType.ANTHROPIC

    ordered = [primary_type] + [t for t in all_types if t != primary_type]

    # Build providers, skipping ones without credentials
    providers = []
    names = []
    for ptype in ordered:
        prov_config = config.providers.get(ptype.value)
        if ptype == ProviderType.LLAMACPP:
            # llama.cpp doesn't need an API key, but check if it's running
            base_url = prov_config.base_url if prov_config else "http://localhost:8012"
            if _check_llamacpp_available(base_url):
                providers.append(_build_provider(ptype, config))
                names.append(ptype.value)
            else:
                logger.debug("Skipping %s: server not reachable at %s", ptype.value, base_url)
        elif prov_config and (prov_config.api_key or prov_config.api_key_env):
            # Has key configured (resolved or via env var name)
            providers.append(_build_provider(ptype, config))
            names.append(ptype.value)
        else:
            logger.debug("Skipping %s: no API key configured", ptype.value)

    if not providers:
        raise RuntimeError("No LLM providers configured. Set at least one API key.")

    if len(providers) == 1:
        return providers[0]

    logger.info("Fallback chain: %s", " -> ".join(names))
    return FallbackProvider(providers, names)
