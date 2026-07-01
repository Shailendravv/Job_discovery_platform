"""
Ollama LLM provider.

Calls a locally-hosted Ollama instance. Supports JSON format via Ollama's
native format=json parameter.

Environment variables:
    LLM_PROVIDER=ollama
    OLLAMA_BASE_URL=http://localhost:11434
    OLLAMA_MODEL=qwen2.5-coder:1.5b
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import httpx

from app.core.config import settings
from app.services.llm.base import LLMProvider, LLMResult, _clean_json_response

log = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """Provider that calls a locally-hosted Ollama instance."""

    @property
    def name(self) -> str:
        return "ollama"

    def __init__(self) -> None:
        self.base_url = (settings.OLLAMA_BASE_URL or settings.Ollama).rstrip("/")
        self.model = settings.OLLAMA_MODEL or settings.MODEL_NAME
        self.temperature = settings.MODEL_TEMPERATURE
        log.info(
            "[llm:ollama] initialized — url=%s model=%s temperature=%s",
            self.base_url,
            self.model,
            self.temperature,
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
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
                messages: list[dict] = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})

                body: dict = {
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": max_tokens,
                    },
                }
                if json_format:
                    body["format"] = "json"

                try:
                    body["think"] = False
                    resp = await asyncio.wait_for(
                        client.post(f"{self.base_url}/api/chat", json=body),
                        timeout=timeout,
                    )
                except Exception:
                    body.pop("think", None)
                    resp = await asyncio.wait_for(
                        client.post(f"{self.base_url}/api/chat", json=body),
                        timeout=timeout,
                    )

                resp.raise_for_status()
                data = resp.json()
                content = data.get("message", {}).get("content", "")
                if json_format:
                    content = _clean_json_response(content)

            elapsed = (time.monotonic() - start) * 1000
            return LLMResult(
                content=content,
                provider=self.name,
                model=self.model,
                response_time_ms=elapsed,
            )

        except asyncio.TimeoutError:
            elapsed = (time.monotonic() - start) * 1000
            failure_reason = f"Ollama timeout after {timeout}s"
            log.warning("[llm:ollama] generation failed: %s", failure_reason)
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
            log.warning("[llm:ollama] generation failed: %s", failure_reason)
            return LLMResult(
                content="",
                provider=self.name,
                model=self.model,
                response_time_ms=elapsed,
                failure_reason=failure_reason,
            )
