"""
LLM provider factory.

The application must never directly instantiate providers.
Instead, call `get_llm_provider()` which returns the correct implementation
based on the `LLM_PROVIDER` environment variable.

Fixed two-step chain: Claude (Haiku) is the primary provider; on any
failure it falls through to a local Ollama instance. No other providers
are supported on this branch — see AGENTS.md.

Usage:
    from app.services.llm import get_llm_provider

    provider = get_llm_provider()  # LLM_PROVIDER env var — "claude" by default
    result = provider.generate(prompt, json_format=True)
"""

from __future__ import annotations

import logging

from app.core.config import settings

from app.services.llm.base import LLMProvider
from app.services.llm.claude_fallback_provider import (
    ClaudeWithOllamaFallback,
    ClaudeCodeWithOllamaFallback,
)
from app.services.llm.claude_provider import ClaudeProvider
from app.services.llm.claude_code_provider import ClaudeCodeProvider
from app.services.llm.ollama_provider import OllamaProvider

log = logging.getLogger(__name__)

# Module-level cache so we only create the provider once
_provider_cache: dict[str, "LLMProvider"] = {}


def get_llm_provider(
    provider: str | None = None,
    force_refresh: bool = False,
) -> "LLMProvider":
    """Return an LLM provider instance.

    Args:
        provider: Provider name — "claude-code" (Claude Haiku via the local
                  Claude Code CLI, falling back to Ollama; the default),
                  "claude-code-only" (Claude Code CLI, no fallback),
                  "claude" (Claude Haiku via the metered Anthropic API,
                  falling back to Ollama), "claude-only" (Anthropic API, no
                  fallback), or "ollama" (Ollama only, no fallback). If
                  None, reads from settings.LLM_PROVIDER.
        force_refresh: If True, discard cached provider and create a new one.

    Returns:
        An LLMProvider instance.

    Raises:
        ValueError: If the provider name is unknown.
    """

    provider_name = (provider or settings.LLM_PROVIDER).lower().strip()

    if not force_refresh and provider_name in _provider_cache:
        return _provider_cache[provider_name]

    if provider_name == "claude-code":
        provider_instance: LLMProvider = ClaudeCodeWithOllamaFallback()
    elif provider_name == "claude-code-only":
        provider_instance = ClaudeCodeProvider()
    elif provider_name == "claude":
        provider_instance = ClaudeWithOllamaFallback()
    elif provider_name == "claude-only":
        provider_instance = ClaudeProvider()
    elif provider_name == "ollama":
        provider_instance = OllamaProvider()
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider_name!r}. "
            "Supported values: 'claude-code' (Haiku via the Claude Code "
            "CLI, falls back to Ollama), 'claude-code-only', "
            "'claude' (Haiku via the Anthropic API, falls back to Ollama), "
            "'claude-only', 'ollama'."
        )

    _provider_cache[provider_name] = provider_instance
    log.info("[llm:factory] provider=%s", provider_instance.name)
    return provider_instance
