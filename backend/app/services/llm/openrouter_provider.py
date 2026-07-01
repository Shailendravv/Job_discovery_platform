"""
OpenRouter LLM provider.

Calls the OpenRouter API to access multiple models. Supports automatic
model fallback via FallbackManager when the primary model fails.

Environment variables:
    LLM_PROVIDER=openrouter
    OPENROUTER_API_KEY=sk-or-v1-...
    OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
    OPENROUTER_MODEL=  # optional, defaults to qwen/qwen3-coder:free
"""
from __future__ import annotations
import logging
import time
from typing import Optional

import httpx

from app.core.config import settings
from app.services.llm.base import LLMProvider, LLMResult, _clean_json_response
from app.services.llm.fallback_manager import FallbackManager

log = logging.getLogger(__name__)

# Default OpenRouter model when none is configured
_DEFAULT_MODEL = "qwen/qwen3-coder:free"


class OpenRouterProvider(LLMProvider):
    """Provider that calls the OpenRouter API with model fallback."""

    @property
    def name(self) -> str:
        return "openrouter"

    def __init__(self) -> None:
        self.api_key = settings.OPENROUTER_API_KEY
        self.base_url = (
            getattr(settings, "OPENROUTER_BASE_URL", None)
            or "https://openrouter.ai/api/v1"
        ).rstrip("/")
        self.preferred_model = (
            getattr(settings, "OPENROUTER_MODEL", None) or _DEFAULT_MODEL
        )
        self.temperature = settings.MODEL_TEMPERATURE

        if not self.api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is not configured. "
                "Set OPENROUTER_API_KEY in your .env file or environment."
            )

        self.fallback_manager = FallbackManager(
            fallback_models=getattr(settings, "OPENROUTER_FALLBACK_MODELS", None),
        )

        log.info(
            "[llm:openrouter] initialized — base_url=%s preferred_model=%s",
            self.base_url,
            self.preferred_model,
        )

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

        async def _call_model(model: str) -> tuple[LLMResult, str]:
            """Internal: call a specific model and return the result."""
            call_start = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    messages: list[dict] = []
                    if system_prompt:
                        messages.append({"role": "system", "content": system_prompt})
                    messages.append({"role": "user", "content": prompt})

                    body: dict = {
                        "model": model,
                        "messages": messages,
                        "temperature": self.temperature,
                        "max_tokens": max_tokens,
                    }

                    # OpenRouter uses OpenAI-compatible response_format for JSON
                    if json_format:
                        body["response_format"] = {"type": "json_object"}

                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "http://localhost:8000",
                        "X-Title": "JobSphere",
                    }

                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=body,
                        headers=headers,
                    )

                    if resp.status_code == 429:
                        raise RuntimeError("rate limit exceeded")
                    resp.raise_for_status()

                    data = resp.json()
                    content = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )

                    # The model used may differ from what we requested
                    # (OpenRouter can route to alternatives)
                    actual_model = data.get("model", model)

                    if json_format:
                        content = _clean_json_response(content)

                    elapsed = (time.monotonic() - call_start) * 1000
                    return LLMResult(
                        content=content,
                        provider="openrouter",
                        model=actual_model,
                        response_time_ms=elapsed,
                    ), actual_model

            except Exception as e:
                elapsed = (time.monotonic() - call_start) * 1000
                return LLMResult(
                    content="",
                    provider="openrouter",
                    model=model,
                    response_time_ms=elapsed,
                    failure_reason=str(e),
                ), model

        # Use the fallback manager to try models
        result = await self.fallback_manager.execute_with_fallback(
            call_model=_call_model,
            preferred_model=self.preferred_model,
        )

        # Fill in response time from the overall call
        elapsed = (time.monotonic() - start) * 1000
        if result.response_time_ms == 0.0:
            result.response_time_ms = elapsed

        return result
