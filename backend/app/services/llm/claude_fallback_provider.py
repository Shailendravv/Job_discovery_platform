"""
Primary provider -> Ollama fallback chain.

Generic two-step provider: try the configured primary first; on any
failure (network error, non-2xx response, rate limit, missing
credentials, missing CLI binary), fall through to the local Ollama
instance. Two concrete chains are exposed — Claude via the Anthropic API,
and Claude via the local Claude Code CLI — see app/services/llm/factory.py.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from app.services.llm.base import LLMProvider, LLMResult
from app.services.llm.claude_provider import ClaudeProvider
from app.services.llm.claude_code_provider import ClaudeCodeProvider
from app.services.llm.ollama_provider import OllamaProvider

log = logging.getLogger(__name__)


class _PrimaryWithOllamaFallback(LLMProvider):
    """A primary provider, falling back to local Ollama on failure.

    Subclasses set `_primary_cls` to the concrete primary provider class.
    """

    _primary_cls: type[LLMProvider]

    def __init__(self) -> None:
        self._primary: LLMProvider | None
        try:
            self._primary = self._primary_cls()
        except Exception as e:
            # e.g. no ANTHROPIC_API_KEY / no `ant auth login` profile, or
            # (for the Claude Code chain) no `claude` binary on PATH — go
            # straight to Ollama rather than failing to start.
            log.warning(
                "[llm:%s+ollama] primary provider unavailable at init (%s) — "
                "will use Ollama only",
                self._primary_cls.__name__,
                e,
            )
            self._primary = None
        self._ollama = OllamaProvider()

    @property
    def name(self) -> str:
        if self._primary is None:
            return self._ollama.name
        return f"{self._primary.name}->{self._ollama.name}"

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

        if self._primary is not None:
            result = await self._primary.generate_async(
                prompt,
                json_format=json_format,
                timeout=timeout,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
            if result.content and not result.failure_reason:
                return result
            log.warning(
                "[llm:%s+ollama] primary failed (%s) — falling through to ollama",
                self._primary.name,
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
        result.fallback_attempts = 1 if self._primary is not None else 0
        result.response_time_ms = elapsed
        return result


class ClaudeWithOllamaFallback(_PrimaryWithOllamaFallback):
    """Claude Haiku via the Anthropic API, falling back to local Ollama."""

    _primary_cls = ClaudeProvider


class ClaudeCodeWithOllamaFallback(_PrimaryWithOllamaFallback):
    """Claude Haiku via the local Claude Code CLI, falling back to local Ollama."""

    _primary_cls = ClaudeCodeProvider
