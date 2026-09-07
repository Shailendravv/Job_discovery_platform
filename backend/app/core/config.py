from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGODB_URI: str

    # ── LLM Provider Configuration ───────────────────────────────────────
    # Fixed two-step chain: Claude (Haiku) first, Ollama as the local
    # fallback if the Claude API call fails. No other providers.
    LLM_PROVIDER: str = "claude"
    MODEL_TEMPERATURE: float = 0.1

    # Claude (Anthropic API) — credentials resolve from ANTHROPIC_API_KEY /
    # an `ant auth login` profile; not read as a Settings field.
    CLAUDE_MODEL: str = "claude-haiku-4-5"

    # Ollama — local fallback
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5-coder:1.5b"

    # Cloudinary Configuration
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    LOG_LEVEL: str = "INFO"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        # env vars from OS/terminal always override .env file values
        "env_file_override": True,
    }


settings = Settings()
