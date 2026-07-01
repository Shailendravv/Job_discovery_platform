"""
Multi-provider orchestrator.

Chains multiple LLM providers and falls through to the next on any failure.
At the end of the chain, OpenRouter's model-level fallback (FallbackManager)
will try its own fallback models internally before returning failure.

Usage:
    provider = MultiProvider(["groq", "cerebras", "sambanova", "nvidia", "openrouter"])
    result = await provider.generate_async(prompt)
    print(f"Used: {result.provider} / {result.model}")
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from app.services.llm.base import LLMProvider, LLMResult

from app.services.llm.ollama_provider import OllamaProvider
from app.services.llm.openrouter_provider import OpenRouterProvider
from app.services.llm.groq_provider import GroqProvider
from app.services.llm.cerebras_provider import CerebrasProvider
from app.services.llm.sambanova_provider import SambaNovaProvider
from app.services.llm.nvidia_provider import NvidiaProvider

log = logging.getLogger(__name__)


class MultiProvider(LLMProvider):
    """Orchestrates multiple providers with automatic fallback on failure."""

    def __init__(self, provider_names: list[str]) -> None:
        self._providers: list[LLMProvider] = []
        for name in provider_names:
            provider = self._resolve(name)
            if provider is not None:
                self._providers.append(provider)

        if not self._providers:
            raise ValueError(
                f"No valid providers resolved from names: {provider_names}"
            )

        log.info(
            "[llm:multi] initialized — chain=%s",
            [p.name for p in self._providers],
        )

    @property
    def name(self) -> str:
        return "+".join(p.name for p in self._providers)

    def _resolve(self, name: str) -> LLMProvider | None:
        """Resolve a provider name string to an LLMProvider instance."""
        name = name.strip().lower()

        try:
            if name == "ollama":
                return OllamaProvider()
            elif name == "openrouter":

                return OpenRouterProvider()
            elif name == "groq":

                return GroqProvider()
            elif name == "cerebras":

                return CerebrasProvider()
            elif name == "sambanova":

                return SambaNovaProvider()
            elif name == "nvidia":

                return NvidiaProvider()
            else:
                log.warning("[llm:multi] unknown provider=%s — skipping", name)
                return None
        except Exception as e:
            log.warning(
                "[llm:multi] failed to init provider=%s — %s — skipping",
                name,
                e,
            )
            return None

    async def generate_async(
        self,
        prompt: str,
        *,
        json_format: bool = False,
        timeout: int = 120,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> LLMResult:
        start = time.monotonic()
        last_result: LLMResult | None = None
        provider_count = len(self._providers)

        for idx, provider in enumerate(self._providers):
            log.info(
                "[llm:multi] attempting provider=%s (%d/%d)",
                provider.name,
                idx + 1,
                provider_count,
            )

            result = await provider.generate_async(
                prompt,
                json_format=json_format,
                timeout=timeout,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )

            if result.content and not result.failure_reason:
                elapsed = (time.monotonic() - start) * 1000
                result.fallback_attempts = idx
                log.info(
                    "[llm:multi] success — provider=%s model=%s "
                    "response_time=%.0fms attempts=%d",
                    result.provider,
                    result.model,
                    elapsed,
                    idx + 1,
                )
                return result

            # Failure — log and fall through to next provider
            log.warning(
                "[llm:multi] provider=%s failed — model=%s reason=%s — "
                "falling through to next provider",
                provider.name,
                result.model,
                result.failure_reason or "empty response",
            )
            last_result = result

        # All providers failed
        elapsed = (time.monotonic() - start) * 1000
        log.error(
            "[llm:multi] all %d providers failed",
            provider_count,
        )
        if last_result is None:
            last_result = LLMResult(
                content="",
                provider="multi",
                model="",
                failure_reason="No providers available",
            )
        last_result.fallback_attempts = provider_count - 1
        last_result.response_time_ms = elapsed
        return last_result
