"""
Abstract LLM provider interface.

All LLM providers (Ollama, OpenRouter, etc.) implement this interface.
The rest of the application calls `get_llm_provider().generate(...)` and
never knows which provider is actually running.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional

log = logging.getLogger(__name__)


class LLMResult:
    """Structured result from an LLM call."""

    def __init__(
        self,
        content: str,
        provider: str = "",
        model: str = "",
        fallback_attempts: int = 0,
        response_time_ms: float = 0.0,
        failure_reason: str = "",
    ):
        self.content = content
        self.provider = provider
        self.model = model
        self.fallback_attempts = fallback_attempts
        self.response_time_ms = response_time_ms
        self.failure_reason = failure_reason


class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name (e.g. 'ollama', 'openrouter')."""
        ...

    @abstractmethod
    async def generate_async(
        self,
        prompt: str,
        *,
        json_format: bool = False,
        timeout: int = 120,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> LLMResult:
        """Send a prompt to the LLM and return the result.

        Args:
            prompt: The user message / prompt text.
            json_format: If True, request structured JSON output.
            timeout: Maximum seconds to wait for a response.
            max_tokens: Maximum tokens in the response.
            system_prompt: Optional system-level instruction.

        Returns:
            LLMResult with the generated content and metadata.
        """
        ...

    def generate(
        self,
        prompt: str,
        *,
        json_format: bool = False,
        timeout: int = 120,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> LLMResult:
        """Synchronous wrapper around generate_async."""
        return asyncio.run(
            self.generate_async(
                prompt,
                json_format=json_format,
                timeout=timeout,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
        )


def _clean_json_response(raw: str) -> str:
    """Strip markdown fences, think blocks, and leading/trailing whitespace."""
    import re

    cleaned = raw.strip()
    # Strip <think>...</think> blocks
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()
    # Strip ```json ... ``` fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()
