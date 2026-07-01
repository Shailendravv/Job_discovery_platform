"""
Fallback manager for automatic model failover.

When a model times out, returns a rate-limit, 5xx error, invalid JSON,
or empty content, the fallback manager automatically retries with the
next model in the chain using exponential backoff.

Designed for OpenRouter's free-tier models where availability varies.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Callable, Optional

from app.services.llm.base import LLMResult

log = logging.getLogger(__name__)

# ── Default fallback chain (OpenRouter-free tier models) ──────────────

DEFAULT_FALLBACK_MODELS = [
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "google/gemma-4-26b-a4b-it:free",
    "poolside/laguna-xs.2:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
]


class FallbackManager:
    """Manages model fallback with retry logic, backoff, and metrics tracking.

    Usage:
        manager = FallbackManager(fallback_models=[...])
        result = await manager.execute_with_fallback(
            call_model_fn, preferred_model="..."
        )
    """

    def __init__(
        self,
        fallback_models: Optional[list[str]] = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ):
        self.fallback_models = fallback_models or DEFAULT_FALLBACK_MODELS
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    async def execute_with_fallback(
        self,
        call_model: Callable[[str], tuple[LLMResult, str]],
        preferred_model: Optional[str] = None,
    ) -> LLMResult:
        """Execute an LLM call with automatic fallback across models.

        Args:
            call_model: Async function that takes a model name string and
                        returns (LLMResult, model_name_used).
            preferred_model: The first model to try (e.g. the user-configured
                             default). Falls back to fallback_models on failure.

        Returns:
            LLMResult from the first successful model, or the last failure
            result if all models fail.
        """
        # Build the list of models to try
        models_to_try: list[str] = []
        if preferred_model:
            models_to_try.append(preferred_model)
        models_to_try.extend([m for m in self.fallback_models if m != preferred_model])

        last_result: LLMResult = LLMResult(
            content="",
            provider="openrouter",
            model=models_to_try[0] if models_to_try else "",
            failure_reason="No models available",
        )

        failed_models: list[str] = []

        for attempt, model in enumerate(models_to_try):
            log.info(
                "[llm:fallback] attempt %d/%d — model=%s",
                attempt + 1,
                len(models_to_try),
                model,
            )
            try:
                result, actual_model = await call_model(model)
            except Exception as e:
                result = LLMResult(
                    content="",
                    provider="openrouter",
                    model=model,
                    failure_reason=str(e),
                )

            if result.content and not result.failure_reason:
                # Success
                log.info(
                    "[llm:fallback] success — model=%s attempts=%d failures=%s",
                    actual_model,
                    attempt + 1,
                    failed_models,
                )
                result.provider = "openrouter"
                result.model = actual_model
                result.fallback_attempts = attempt
                return result

            # Failure — log and prepare for next attempt
            failed_models.append(model)
            log.warning(
                "[llm:fallback] model=%s failed: %s",
                model,
                result.failure_reason or "empty response",
            )
            last_result = result

            # Exponential backoff before retry (jittered)
            if attempt < len(models_to_try) - 1:
                delay = min(
                    self.base_delay * (2**attempt) + random.uniform(0, 1),
                    self.max_delay,
                )
                log.debug("[llm:fallback] backing off %.1fs before next attempt", delay)
                await asyncio.sleep(delay)

        # All models failed
        log.error(
            "[llm:fallback] all %d models failed: %s",
            len(models_to_try),
            failed_models,
        )
        last_result.fallback_attempts = len(models_to_try) - 1
        last_result.failure_reason = (
            f"All {len(models_to_try)} models failed: {', '.join(failed_models)}"
        )
        return last_result
