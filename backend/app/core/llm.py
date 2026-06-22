"""
Legacy LLM dispatch layer — delegates to the new provider architecture.

Maintains the backward-compatible `call_llm()` function so existing callers
(services, agents, MCP servers) work without changes.

New code should use the provider directly:
    from app.services.llm import get_llm_provider
    result = await get_llm_provider().generate_async(prompt, json_format=True)
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.llm import get_llm_provider

log = logging.getLogger(__name__)


def call_llm(
    prompt: str,
    json_format: bool = False,
    timeout: int = 120,
    provider: str | None = None,
    max_tokens: int = 4096,
    system_prompt: Optional[str] = None,
) -> str:
    """Call the configured LLM provider.

    This is the legacy synchronous entry point. It delegates to the new
    provider architecture in app/services/llm/.

    Args:
        prompt: The prompt text to send.
        json_format: If True, request structured JSON output.
        timeout: Maximum seconds to wait for a response.
        provider: Override the configured provider (ignored — use LLM_PROVIDER env).
        max_tokens: Maximum tokens in the response.
        system_prompt: Optional system-level instruction.

    Returns:
        The generated text content, or empty string on failure.

    Raises:
        Various exceptions from the underlying provider (timeout, API error, etc.).
    """
    llm = get_llm_provider()
    result = llm.generate(
        prompt,
        json_format=json_format,
        timeout=timeout,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
    )

    if result.failure_reason:
        log.warning(
            "[llm] call_llm failed — provider=%s model=%s reason=%s",
            result.provider,
            result.model,
            result.failure_reason,
        )

    return result.content


async def call_llm_async(
    prompt: str,
    json_format: bool = False,
    timeout: int = 120,
    provider: str | None = None,
    max_tokens: int = 4096,
    system_prompt: Optional[str] = None,
) -> str:
    """Async version of call_llm.

    Same interface as call_llm but uses the provider's async path directly
    instead of wrapping in asyncio.run().
    """
    llm = get_llm_provider()
    result = await llm.generate_async(
        prompt,
        json_format=json_format,
        timeout=timeout,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
    )

    if result.failure_reason:
        log.warning(
            "[llm] call_llm_async failed — provider=%s model=%s reason=%s",
            result.provider,
            result.model,
            result.failure_reason,
        )

    return result.content
