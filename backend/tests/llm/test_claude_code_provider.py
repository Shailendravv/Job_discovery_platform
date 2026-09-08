"""
Tests for the Claude Code CLI provider and the generic primary->Ollama
fallback wrapper.

All `subprocess.run` calls are monkeypatched — nothing here spawns a real
`claude` process or hits the network.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from app.services.llm.base import LLMResult
from app.services.llm.claude_code_provider import ClaudeCodeProvider
from app.services.llm.claude_fallback_provider import _PrimaryWithOllamaFallback
from app.services.llm.ollama_provider import OllamaProvider


def _success_envelope(result: str = "OK", **usage_overrides) -> str:
    usage = {
        "input_tokens": 179,
        "output_tokens": 12,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    usage.update(usage_overrides)
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": result,
            "usage": usage,
            "total_cost_usd": 0.001,
        }
    )


@pytest.fixture
def provider():
    with patch("app.services.llm.claude_code_provider.shutil.which", return_value="C:/fake/claude.CMD"):
        return ClaudeCodeProvider()


class TestArgvAndEnv:
    @pytest.mark.asyncio
    async def test_argv_contains_required_flags(self, provider, tmp_path):
        provider._cwd = tmp_path
        captured = {}

        def fake_run(argv, input, capture_output, text, encoding, errors, timeout, env, cwd, shell):
            captured["argv"] = argv
            captured["env"] = env
            captured["input"] = input
            captured["shell"] = shell
            return subprocess.CompletedProcess(argv, 0, stdout=_success_envelope(), stderr="")

        with patch.object(provider, "_run_subprocess", side_effect=lambda argv, prompt, env, timeout: fake_run(
            argv, prompt, True, True, "utf-8", "replace", timeout, env, str(tmp_path), True
        )):
            await provider.generate_async("hello", timeout=30)

        argv = captured["argv"]
        assert argv[0] == provider._bin
        assert "-p" in argv
        assert "--model" in argv and argv[argv.index("--model") + 1] == "haiku"
        assert "--tools" in argv and argv[argv.index("--tools") + 1] == ""
        assert "--strict-mcp-config" in argv
        assert "--setting-sources" in argv and argv[argv.index("--setting-sources") + 1] == ""
        assert "--disable-slash-commands" in argv
        assert "--no-session-persistence" in argv
        assert "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json"
        assert "--system-prompt-file" in argv

    @pytest.mark.asyncio
    async def test_anthropic_api_key_stripped_from_subprocess_env(self, provider, tmp_path, monkeypatch):
        provider._cwd = tmp_path
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-be-inherited")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "also-should-not-be-inherited")
        captured = {}

        def fake_run(argv, prompt, env, timeout):
            captured["env"] = env
            return subprocess.CompletedProcess(argv, 0, stdout=_success_envelope(), stderr="")

        with patch.object(provider, "_run_subprocess", side_effect=fake_run):
            await provider.generate_async("hello")

        assert "ANTHROPIC_API_KEY" not in captured["env"]
        assert "ANTHROPIC_AUTH_TOKEN" not in captured["env"]

    @pytest.mark.asyncio
    async def test_prompt_on_stdin_and_system_prompt_in_file(self, provider, tmp_path):
        provider._cwd = tmp_path
        captured = {}

        def fake_run(argv, prompt, env, timeout):
            captured["prompt"] = prompt
            sysfile_path = argv[argv.index("--system-prompt-file") + 1]
            captured["sysfile_content"] = open(sysfile_path, encoding="utf-8").read()
            return subprocess.CompletedProcess(argv, 0, stdout=_success_envelope(), stderr="")

        with patch.object(provider, "_run_subprocess", side_effect=fake_run):
            await provider.generate_async("the user prompt", system_prompt="be terse")

        assert captured["prompt"] == "the user prompt"
        assert captured["sysfile_content"] == "be terse"

    @pytest.mark.asyncio
    async def test_default_system_prompt_used_when_caller_passes_none(self, provider, tmp_path):
        provider._cwd = tmp_path
        captured = {}

        def fake_run(argv, prompt, env, timeout):
            sysfile_path = argv[argv.index("--system-prompt-file") + 1]
            captured["sysfile_content"] = open(sysfile_path, encoding="utf-8").read()
            return subprocess.CompletedProcess(argv, 0, stdout=_success_envelope(), stderr="")

        with patch.object(provider, "_run_subprocess", side_effect=fake_run):
            await provider.generate_async("hi", json_format=True)

        assert "text-processing assistant" in captured["sysfile_content"]
        assert "JSON" in captured["sysfile_content"]


class TestResponseHandling:
    @pytest.mark.asyncio
    async def test_success_envelope_returns_content(self, provider, tmp_path):
        provider._cwd = tmp_path
        with patch.object(
            provider,
            "_run_subprocess",
            return_value=subprocess.CompletedProcess([], 0, stdout=_success_envelope("hello world"), stderr=""),
        ):
            result = await provider.generate_async("hi")

        assert isinstance(result, LLMResult)
        assert result.content == "hello world"
        assert result.failure_reason == ""
        assert result.provider == "claude-code"

    @pytest.mark.asyncio
    async def test_json_format_strips_markdown_fence(self, provider, tmp_path):
        provider._cwd = tmp_path
        fenced = "```json\n{\"a\": 1}\n```"
        with patch.object(
            provider,
            "_run_subprocess",
            return_value=subprocess.CompletedProcess([], 0, stdout=_success_envelope(fenced), stderr=""),
        ):
            result = await provider.generate_async("hi", json_format=True)

        assert result.content == '{"a": 1}'

    @pytest.mark.asyncio
    async def test_is_error_envelope_yields_failure_reason(self, provider, tmp_path):
        provider._cwd = tmp_path
        envelope = json.dumps({"is_error": True, "result": "something broke"})
        with patch.object(
            provider,
            "_run_subprocess",
            return_value=subprocess.CompletedProcess([], 0, stdout=envelope, stderr=""),
        ):
            result = await provider.generate_async("hi")

        assert result.content == ""
        assert "something broke" in result.failure_reason

    @pytest.mark.asyncio
    async def test_nonzero_exit_yields_failure_reason(self, provider, tmp_path):
        provider._cwd = tmp_path
        with patch.object(
            provider,
            "_run_subprocess",
            return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="auth error"),
        ):
            result = await provider.generate_async("hi")

        assert result.content == ""
        assert "auth error" in result.failure_reason

    @pytest.mark.asyncio
    async def test_unparseable_output_yields_failure_reason(self, provider, tmp_path):
        provider._cwd = tmp_path
        with patch.object(
            provider,
            "_run_subprocess",
            return_value=subprocess.CompletedProcess([], 0, stdout="not json", stderr=""),
        ):
            result = await provider.generate_async("hi")

        assert result.content == ""
        assert result.failure_reason

    @pytest.mark.asyncio
    async def test_timeout_yields_failure_reason_not_exception(self, provider, tmp_path):
        provider._cwd = tmp_path
        with patch.object(
            provider, "_run_subprocess", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=30)
        ):
            result = await provider.generate_async("hi", timeout=30)

        assert result.content == ""
        assert "timeout" in result.failure_reason.lower()

    def test_init_raises_when_binary_not_found(self):
        with patch("app.services.llm.claude_code_provider.shutil.which", return_value=None):
            with pytest.raises(RuntimeError):
                ClaudeCodeProvider()


class TestFallbackWrapper:
    @pytest.mark.asyncio
    async def test_falls_through_to_ollama_when_primary_fails(self):
        class _FailingPrimary:
            name = "fake-primary"

            async def generate_async(self, *a, **kw):
                return LLMResult(content="", provider="fake-primary", failure_reason="boom")

        class _FakeOllama:
            name = "ollama"

            async def generate_async(self, *a, **kw):
                return LLMResult(content="from ollama", provider="ollama")

        class Chain(_PrimaryWithOllamaFallback):
            _primary_cls = _FailingPrimary

        chain = Chain.__new__(Chain)
        chain._primary = _FailingPrimary()
        chain._ollama = _FakeOllama()

        result = await chain.generate_async("hi")
        assert result.content == "from ollama"
        assert result.fallback_attempts == 1

    def test_name_is_ollama_only_when_primary_cannot_init(self):
        class _AlwaysFailsInit:
            def __init__(self):
                raise RuntimeError("no claude on PATH")

        class Chain(_PrimaryWithOllamaFallback):
            _primary_cls = _AlwaysFailsInit

        with patch("app.services.llm.claude_fallback_provider.OllamaProvider", return_value=OllamaProvider.__new__(OllamaProvider)):
            chain = Chain()

        assert chain._primary is None
        assert chain.name == chain._ollama.name
