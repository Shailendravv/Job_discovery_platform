from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGODB_URI: str

    # ── LLM Provider Configuration ───────────────────────────────────────
    # Default chain: Claude (Haiku) via the local Claude Code CLI first —
    # billed against the Claude Code subscription, not per-token API
    # usage — falling back to Ollama if the CLI call fails. See
    # backend/docs/llm.md for the full provider matrix.
    LLM_PROVIDER: str = "claude-code"
    MODEL_TEMPERATURE: float = 0.1

    # Claude Code CLI — used by "claude-code" / "claude-code-only".
    # CLAUDE_CODE_BIN is the binary name/path passed to shutil.which();
    # CLAUDE_CODE_MODEL is passed to `claude --model`.
    CLAUDE_CODE_BIN: str = "claude"
    CLAUDE_CODE_MODEL: str = "haiku"

    # Claude (Anthropic API) — used by "claude" / "claude-only". Credentials
    # resolve from ANTHROPIC_API_KEY / an `ant auth login` profile; not read
    # as a Settings field.
    CLAUDE_MODEL: str = "claude-haiku-4-5"

    # Ollama — local fallback
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5-coder:1.5b"

    # Cloudinary Configuration
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    # ── Job Discovery ────────────────────────────────────────────────────
    # Default recency window for a discovery session — "only jobs posted in
    # the last 24 hours". Parsed by app.ingest.time_util.parse_duration, so
    # "24h" / "48h" / "7d" / "30m" all work. Callers (the API body, the
    # jobctl --since flag) may override it per run.
    DISCOVERY_WINDOW: str = "24h"

    LOG_LEVEL: str = "INFO"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        # env vars from OS/terminal always override .env file values
        "env_file_override": True,
    }


settings = Settings()
