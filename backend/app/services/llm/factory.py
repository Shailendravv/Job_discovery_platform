"""
LLM provider factory.

The application must never directly instantiate providers.
Instead, call `get_llm_provider()` which returns the correct implementation
based on the `LLM_PROVIDER` environment variable.

Usage:
    from app.services.llm import get_llm_provider

    # Uses LLM_PROVIDER env var (supports "multi" for chain fallback)
    provider = get_llm_provider()
    result = provider.generate(prompt, json_format=True)

    # Or specify a provider explicitly
    provider = get_llm_provider("ollama")
    provider = get_llm_provider("groq")
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings

from app.services.llm.base import LLMProvider
from app.services.llm.multi_provider import MultiProvider
from app.services.llm.ollama_provider import OllamaProvider
from app.services.llm.openrouter_provider import OpenRouterProvider
from app.services.llm.groq_provider import GroqProvider
from app.services.llm.cerebras_provider import CerebrasProvider
from app.services.llm.sambanova_provider import SambaNovaProvider
from app.services.llm.nvidia_provider import NvidiaProvider

log = logging.getLogger(__name__)

# Module-level cache so we only create the provider once
_provider_cache: dict[str, "LLMProvider"] = {}


def get_llm_provider(
    provider: str | None = None,
    force_refresh: bool = False,
) -> "LLMProvider":
    """Return an LLM provider instance.

    Args:
        provider: Provider name (e.g. "ollama", "openrouter", "groq", "multi").
                  If None, reads from settings.LLM_PROVIDER.
        force_refresh: If True, discard cached provider and create a new one.

    Returns:
        An LLMProvider instance.

    Raises:
        ValueError: If the provider name is unknown.
    """

    provider_name = (provider or settings.LLM_PROVIDER).lower().strip()

    cache_key = provider_name
    if not force_refresh and cache_key in _provider_cache:
        return _provider_cache[cache_key]

    if provider_name == "multi":

        chain = [p.strip() for p in settings.LLM_PROVIDER_CHAIN.split(",") if p.strip()]
        provider_instance: LLMProvider = MultiProvider(chain)
        cache_key = f"multi:{','.join(chain)}"

    elif provider_name == "ollama":

        provider_instance = OllamaProvider()

    elif provider_name == "openrouter":

        provider_instance = OpenRouterProvider()

    elif provider_name == "groq":

        provider_instance = GroqProvider()

    elif provider_name == "cerebras":

        provider_instance = CerebrasProvider()

    elif provider_name == "sambanova":

        provider_instance = SambaNovaProvider()

    elif provider_name == "nvidia":

        provider_instance = NvidiaProvider()

    else:
        raise ValueError(
            f"Unknown LLM provider: {provider_name!r}. "
            "Supported values: 'multi', 'ollama', 'openrouter', "
            "'groq', 'cerebras', 'sambanova', 'nvidia'."
        )

    _provider_cache[cache_key] = provider_instance
    log.info("[llm:factory] provider=%s", provider_instance.name)
    return provider_instance
