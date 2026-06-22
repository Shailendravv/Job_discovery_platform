"""
LLM provider factory.

The application must never directly instantiate Ollama or OpenRouter providers.
Instead, call `get_llm_provider()` which returns the correct implementation
based on the `LLM_PROVIDER` environment variable.

Usage:
    from app.services.llm import get_llm_provider

    provider = get_llm_provider()
    result = provider.generate(prompt, json_format=True)
    print(result.content)
"""

from __future__ import annotations

import logging

from app.core.config import settings

log = logging.getLogger(__name__)

# Module-level cache so we only create the provider once
_provider_cache: dict[str, "LLMProvider"] = {}


def get_llm_provider(force_refresh: bool = False) -> "LLMProvider":
    """Return the configured LLM provider singleton.

    Args:
        force_refresh: If True, discard cached provider and create a new one.

    Returns:
        An LLMProvider instance (OllamaProvider or OpenRouterProvider).

    Raises:
        ValueError: If LLM_PROVIDER is set to an unknown value.
    """
    from app.services.llm.base import LLMProvider

    provider_name = settings.LLM_PROVIDER.lower().strip()

    # Return cached provider if available
    if not force_refresh and provider_name in _provider_cache:
        return _provider_cache[provider_name]

    if provider_name == "ollama":
        from app.services.llm.ollama_provider import OllamaProvider

        provider: LLMProvider = OllamaProvider()

    elif provider_name == "openrouter":
        from app.services.llm.openrouter_provider import OpenRouterProvider

        provider = OpenRouterProvider()

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {settings.LLM_PROVIDER!r}. "
            "Supported values: 'ollama', 'openrouter'."
        )

    _provider_cache[provider_name] = provider
    log.info("[llm:factory] provider=%s", provider.name)
    return provider
