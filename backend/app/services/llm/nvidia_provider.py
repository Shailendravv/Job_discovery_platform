from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from app.core.config import settings
from app.services.llm.base import LLMProvider, LLMResult, _clean_json_response

log = logging.getLogger(__name__)


class NvidiaProvider(LLMProvider):
    """Provider that calls the NVIDIA NIM API (OpenAI-compatible)."""

    @property
    def name(self) -> str:
        return "nvidia"

    def __init__(self) -> None:
        self.api_key = settings.NVIDIA_API_KEY
        self.base_url = settings.NVIDIA_BASE_URL.rstrip("/")
        self.model = settings.NVIDIA_MODEL
        self.temperature = settings.MODEL_TEMPERATURE

        if not self.api_key:
            raise ValueError("NVIDIA_API_KEY is not configured.")

        log.info(
            "[llm:nvidia] initialized — base_url=%s model=%s",
            self.base_url,
            self.model,
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
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                messages: list[dict] = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})

                body: dict = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": max_tokens,
                }

                if json_format:
                    body["response_format"] = {"type": "json_object"}

                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
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

                actual_model = data.get("model", self.model)

                if json_format:
                    content = _clean_json_response(content)

                elapsed = (time.monotonic() - start) * 1000
                log.info(
                    "[llm:nvidia] success — model=%s response_time=%.0fms",
                    actual_model,
                    elapsed,
                )
                return LLMResult(
                    content=content,
                    provider=self.name,
                    model=actual_model,
                    response_time_ms=elapsed,
                )

        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            log.warning("[llm:nvidia] failed — model=%s error=%s", self.model, e)
            return LLMResult(
                content="",
                provider=self.name,
                model=self.model,
                response_time_ms=elapsed,
                failure_reason=str(e),
            )
