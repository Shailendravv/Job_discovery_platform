from typing import List, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGODB_URI: str
    SEARXNG_URL: str
    CAMOFOX_URL: str
    MCP_SEARCH_URL: str = "http://localhost:8001"
    MCP_BROWSE_URL: str = "http://localhost:8002"

    # ── LLM Provider Configuration ───────────────────────────────────────
    LLM_PROVIDER: str = "ollama"  # 'ollama' or 'openrouter'
    MODEL_NAME: str = "qwen2.5-coder:1.5b"
    MODEL_TEMPERATURE: float = 0.1

    # Ollama
    Ollama: str = "http://localhost:11434"  # legacy compat, use OLLAMA_BASE_URL
    OLLAMA_BASE_URL: Optional[str] = None  # overrides Ollama if set
    OLLAMA_MODEL: Optional[str] = None     # overrides MODEL_NAME for Ollama

    # OpenRouter
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: Optional[str] = None  # preferred model, with fallback chain

    # Legacy Groq / Gemini (kept for compat, not used by new providers)
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL_NAME: str = "llama-3.3-70b-versatile"
    GEMINI_API_KEY: Optional[str] = None

    # ── Search Configuration ─────────────────────────────────────────────
    SEARCH_MAX_RESULTS: int = 15
    BROWSE_TOP_N: int = 30
    LINKEDIN_MAX_RESULTS: int = 15
    SEARCH_SITES: str = "greenhouse.io,lever.co,myworkdayjobs.com"
    SEARCH_FRESH: bool = True
    SEARCH_CAREERS: bool = False
    SETTLE_SECONDS: float = 1.5
    MAX_SNAPSHOT_CHARS: int = 12000

    # Cloudinary Configuration
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    # SearXNG toggle
    SEARXNG_ENABLED: bool = False  # Set to True to enable SearXNG search results

    # LinkedIn Guest API settings
    LINKEDIN_GUEST_API_ENABLED: bool
    LINKEDIN_GUEST_API_LOCATION: str = "India"
    LINKEDIN_GUEST_API_TIME_RANGE: str = "r86400"  # Past 24 hours
    LINKEDIN_GUEST_API_MAX_RESULTS: int = 15  # Independent cap for LinkedIn results
    LOG_LEVEL: str = "INFO"

    @property
    def search_sites_list(self) -> List[str]:
        return [s.strip() for s in self.SEARCH_SITES.split(",") if s.strip()]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        # env vars from OS/terminal always override .env file values
        "env_file_override": True,
    }


settings = Settings()
