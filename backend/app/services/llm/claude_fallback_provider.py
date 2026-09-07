"""
Claude -> Ollama fallback chain.

Fixed two-step provider: try Claude (Haiku) first; on any failure
(network error, non-2xx response, rate limit, missing credentials), fall
through to the local Ollama instance. This is the whole LLM chain on this
branch — see AGENTS.md and app/services/llm/factory.py.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from app.services.llm.base import LLMProvider, LLMResult
from app.services.llm.claude_provider import ClaudeProvider
from app.services.llm.ollama_provider import OllamaProvider

log = logging.getLogger(__name__)


class ClaudeWithOllamaFallback(LLMProvider):
    """Claude Haiku, falling back to local Ollama on failure."""

    def __init__(self) -> None:
        self._claude: LLMProvider | None
        try:
            self._claude = ClaudeProvider()
        except Exception as e:
            # No ANTHROPIC_API_KEY / no `ant auth login` profile — go
            # straight to Ollama rather than failing to start.
            log.warning(
                "[llm:claude+ollama] Claude provider unavailable at init (%s) — "
                "will use Ollama only",
                e,
            )
            self._claude = None
        self._ollama = OllamaProvider()

    @property
    def name(self) -> str:
        if self._claude is None:
            return self._ollama.name
        return f"{self._claude.name}->{self._ollama.name}"

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

        if self._claude is not None:
            result = await self._claude.generate_async(
                prompt,
                json_format=json_format,
                timeout=timeout,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
            if result.content and not result.failure_reason:
                return result
            log.warning(
                "[llm:claude+ollama] claude failed (%s) — falling through to ollama",
                result.failure_reason or "empty response",
            )

        result = await self._ollama.generate_async(
            prompt,
            json_format=json_format,
            timeout=timeout,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )
        elapsed = (time.monotonic() - start) * 1000
        result.fallback_attempts = 1 if self._claude is not None else 0
        result.response_time_ms = elapsed
        return result
