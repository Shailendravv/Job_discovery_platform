"""
Claude Code CLI LLM provider.

Runs prompts through the local `claude` CLI (Claude Code) instead of the
metered Anthropic API — calls are billed against the Claude Code
subscription, not per-token API usage. Every request is built to spend as
few tokens as possible: no tools, no MCP servers, no user/project/local
settings (so no hooks fire), no slash commands, no session persistence, and
a short system prompt supplied via a temp file instead of the default
Claude Code agent prompt.

Environment variables:
    LLM_PROVIDER=claude-code            (or claude-code-only, no Ollama fallback)
    CLAUDE_CODE_BIN=claude              (binary name or path, default "claude")
    CLAUDE_CODE_MODEL=haiku             (model alias passed to `--model`)

Requires the `claude` CLI to be installed and authenticated
(`claude auth login` / an active subscription) — this provider does not
read or set ANTHROPIC_API_KEY; it explicitly strips it (and
ANTHROPIC_AUTH_TOKEN) from the subprocess environment so the CLI can never
silently fall through to metered API billing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.services.llm.base import LLMProvider, LLMResult, _clean_json_response

log = logging.getLogger(__name__)

DEFAULT_MODEL = "haiku"

_DEFAULT_SYSTEM_PROMPT = (
    "You are a text-processing assistant. Answer the user's message "
    "directly. Output only what is asked."
)
_JSON_SUFFIX = "\nRespond with a single valid JSON object and nothing else."


class ClaudeCodeProvider(LLMProvider):
    """Provider that calls Claude (Haiku) via the local Claude Code CLI."""

    @property
    def name(self) -> str:
        return "claude-code"

    def __init__(self) -> None:
        bin_name = settings.CLAUDE_CODE_BIN or "claude"
        resolved = shutil.which(bin_name)
        if not resolved:
            raise RuntimeError(
                f"claude CLI ({bin_name!r}) not found on PATH — "
                "install Claude Code or set CLAUDE_CODE_BIN"
            )
        self._bin = bin_name
        self.model = settings.CLAUDE_CODE_MODEL or DEFAULT_MODEL

        # Stable scratch cwd, kept outside the app's own workspace so the
        # CLI never picks up this repo's CLAUDE.md / .claude/ config even
        # if --setting-sources/--strict-mcp-config were ever loosened.
        self._cwd = Path(tempfile.gettempdir()) / "jobsphere-llm-cwd"
        self._cwd.mkdir(parents=True, exist_ok=True)

        log.info(
            "[llm:claude-code] initialized — bin=%s model=%s cwd=%s",
            resolved,
            self.model,
            self._cwd,
        )

    def _build_argv(self, system_prompt_file: str) -> list[str]:
        return [
            self._bin,
            "-p",
            "--model",
            self.model,
            "--system-prompt-file",
            system_prompt_file,
            "--tools",
            "",
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--output-format",
            "json",
        ]

    def _build_env(self) -> dict:
        env = dict(os.environ)
        # Force subscription billing — never let a stray API key redirect
        # this provider's calls to the metered Anthropic API.
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        return env

    def _run_subprocess(
        self, argv: list[str], prompt: str, env: dict, timeout: int
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            cwd=str(self._cwd),
            shell=True,  # required on Windows: `claude` resolves to claude.CMD,
            # which CreateProcess cannot launch directly without a shell host.
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

        # max_tokens has no equivalent CLI flag — the interface promises it,
        # but there's nothing to enforce here, so log rather than pretend.
        log.debug(
            "[llm:claude-code] max_tokens=%d requested — not enforceable via CLI, ignoring",
            max_tokens,
        )

        effective_system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
        if json_format:
            effective_system_prompt = effective_system_prompt + _JSON_SUFFIX

        sysfile = self._cwd / f"sysprompt-{uuid.uuid4().hex}.txt"
        try:
            sysfile.write_text(effective_system_prompt, encoding="utf-8")
            argv = self._build_argv(str(sysfile))
            env = self._build_env()

            try:
                result = await asyncio.to_thread(
                    self._run_subprocess, argv, prompt, env, timeout
                )
            except subprocess.TimeoutExpired:
                elapsed = (time.monotonic() - start) * 1000
                failure_reason = f"claude CLI timeout after {timeout}s"
                log.warning("[llm:claude-code] generation failed: %s", failure_reason)
                return LLMResult(
                    content="",
                    provider=self.name,
                    model=self.model,
                    response_time_ms=elapsed,
                    failure_reason=failure_reason,
                )
            except Exception as e:
                elapsed = (time.monotonic() - start) * 1000
                failure_reason = f"failed to launch claude CLI: {e}"
                log.warning("[llm:claude-code] generation failed: %s", failure_reason)
                return LLMResult(
                    content="",
                    provider=self.name,
                    model=self.model,
                    response_time_ms=elapsed,
                    failure_reason=failure_reason,
                )

            elapsed = (time.monotonic() - start) * 1000

            if result.returncode != 0:
                failure_reason = (
                    f"claude CLI exited {result.returncode}: "
                    f"{(result.stderr or result.stdout or '').strip()[:500]}"
                )
                log.warning("[llm:claude-code] generation failed: %s", failure_reason)
                return LLMResult(
                    content="",
                    provider=self.name,
                    model=self.model,
                    response_time_ms=elapsed,
                    failure_reason=failure_reason,
                )

            try:
                envelope = json.loads(result.stdout)
            except (json.JSONDecodeError, TypeError) as e:
                failure_reason = f"unparseable claude CLI output: {e}"
                log.warning("[llm:claude-code] generation failed: %s", failure_reason)
                return LLMResult(
                    content="",
                    provider=self.name,
                    model=self.model,
                    response_time_ms=elapsed,
                    failure_reason=failure_reason,
                )

            if envelope.get("is_error"):
                failure_reason = f"claude CLI reported an error: {envelope.get('result')}"
                log.warning("[llm:claude-code] generation failed: %s", failure_reason)
                return LLMResult(
                    content="",
                    provider=self.name,
                    model=self.model,
                    response_time_ms=elapsed,
                    failure_reason=failure_reason,
                )

            content = envelope.get("result", "") or ""
            if json_format:
                content = _clean_json_response(content)

            usage = envelope.get("usage") or {}
            cost = envelope.get("total_cost_usd")
            log.info(
                "[llm:claude-code] ok — input_tokens=%s output_tokens=%s "
                "cache_read=%s cache_creation=%s cost_usd=%s",
                usage.get("input_tokens"),
                usage.get("output_tokens"),
                usage.get("cache_read_input_tokens"),
                usage.get("cache_creation_input_tokens"),
                cost,
            )

            return LLMResult(
                content=content,
                provider=self.name,
                model=self.model,
                response_time_ms=elapsed,
            )
        finally:
            sysfile.unlink(missing_ok=True)
