"""
LLM smoke test / token-cost check.

Sends one fixed short prompt through the configured LLM chain
(`call_llm_async` -> `get_llm_provider()`) and prints whatever cost/usage
data the active provider reported. Useful for confirming:

  1. the chain is actually reachable (no silent fall-through to Ollama
     when you expect the Claude Code CLI to answer), and
  2. how many tokens/dollars a single call costs — re-run after changing
     any of the token-minimization flags in claude_code_provider.py to
     see the before/after difference (see backend/docs/llm.md).

Usage:
    cd backend
    .venv/Scripts/python.exe scripts/llm_smoke.py
    .venv/Scripts/python.exe scripts/llm_smoke.py --provider ollama
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

sys.path.insert(0, ".")

from app.services.llm import get_llm_provider  # noqa: E402

PROMPT = "Reply with exactly: OK"


async def main(provider_name: str | None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    provider = get_llm_provider(provider=provider_name)
    print(f"provider chain: {provider.name}")

    result = await provider.generate_async(PROMPT, timeout=60)

    print(f"content        : {result.content!r}")
    print(f"actual provider: {result.provider}")
    print(f"model          : {result.model}")
    print(f"response_time  : {result.response_time_ms:.0f} ms")
    print(f"fallback_used  : {bool(result.fallback_attempts)}")
    if result.failure_reason:
        print(f"failure_reason : {result.failure_reason}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        default=None,
        help="override LLM_PROVIDER for this run (claude-code, claude-code-only, "
        "claude, claude-only, ollama)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.provider))
