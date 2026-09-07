"""
Claude (Anthropic API) LLM provider.

Calls the Anthropic Messages API using the official `anthropic` SDK.
Credentials resolve from the environment automatically — `ANTHROPIC_API_KEY`,
or an `ant auth login` profile — so the client is constructed with no
arguments (see anthropic README: prefer this over hardcoding a key).

Environment variables:
    LLM_PROVIDER=claude
    CLAUDE_MODEL=claude-haiku-4-5   (optional — this is already the default)
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from app.core.config import settings
from app.services.llm.base import LLMProvider, LLMResult, _clean_json_response

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"


class ClaudeProvider(LLMProvider):
    """Provider that calls Claude Haiku via the Anthropic Messages API."""

    @property
    def name(self) -> str:
        return "claude"

    def __init__(self) -> None:
        import anthropic

        self.model = settings.CLAUDE_MODEL or DEFAULT_MODEL
        # Zero-arg client: resolves ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN /
        # an `ant auth login` profile from the environment automatically.
        self._client = anthropic.AsyncAnthropic()
        log.info("[llm:claude] initialized — model=%s", self.model)

    async def generate_async(
        self,
        prompt: str,
        *,
        json_format: bool = False,
        timeout: int = 120,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> LLMResult:
        import anthropic

        start = time.monotonic()

        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        try:
            response = await self._client.with_options(timeout=timeout).messages.create(
                **kwargs
            )
            content = "".join(
                block.text for block in response.content if block.type == "text"
            )
            if json_format:
                content = _clean_json_response(content)

            elapsed = (time.monotonic() - start) * 1000
            return LLMResult(
                content=content,
                provider=self.name,
                model=self.model,
                response_time_ms=elapsed,
            )

        except anthropic.APIStatusError as e:
            elapsed = (time.monotonic() - start) * 1000
            failure_reason = f"HTTP {e.status_code}: {e.message}"
            log.warning("[llm:claude] generation failed: %s", failure_reason)
            return LLMResult(
                content="",
                provider=self.name,
                model=self.model,
                response_time_ms=elapsed,
                failure_reason=failure_reason,
            )
        except anthropic.APIConnectionError as e:
            elapsed = (time.monotonic() - start) * 1000
            failure_reason = f"connection error: {e}"
            log.warning("[llm:claude] generation failed: %s", failure_reason)
            return LLMResult(
                content="",
                provider=self.name,
                model=self.model,
                response_time_ms=elapsed,
                failure_reason=failure_reason,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            failure_reason = str(e)
            log.warning("[llm:claude] generation failed: %s", failure_reason)
            return LLMResult(
                content="",
                provider=self.name,
                model=self.model,
                response_time_ms=elapsed,
                failure_reason=failure_reason,
            )
