from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGODB_URI: str
    SEARXNG_URL: str
    CAMOFOX_URL: str
    MCP_SEARCH_URL: str = "http://localhost:8001"
    MCP_BROWSE_URL: str = "http://localhost:8002"
    Ollama: str = "http://localhost:11434"
    LLM_PROVIDER: str = "ollama"  # e.g., 'ollama', 'groq', 'gemini'
    GROQ_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    SEARCH_MAX_RESULTS: int = 10
    BROWSE_TOP_N: int = 15
    SEARCH_SITES: str = "greenhouse.io,lever.co,myworkdayjobs.com"
    SEARCH_FRESH: bool = True
    SEARCH_CAREERS: bool = False
    SETTLE_SECONDS: float = 1.5
    MAX_SNAPSHOT_CHARS: int = 3000
    MODEL_NAME: str = "qwen2.5-coder:1.5b"
    MODEL_TEMPERATURE: float = 0.1

    # LinkedIn Guest API settings
    LINKEDIN_GUEST_API_ENABLED: bool = True
    LINKEDIN_GUEST_API_LOCATION: str = "India"
    LINKEDIN_GUEST_API_TIME_RANGE: str = "r86400"  # Past 24 hours

    # JSearch API (OpenWebNinja) settings
    JSEARCH_API_KEY: str | None = None
    JSEARCH_API_HOST: str = "jsearch.p.rapidapi.com"
    JSEARCH_API_URL: str | None = None  # Custom URL if needed
    JSEARCH_API_LOCATION: str = "India"
    JSEARCH_API_DATE_POSTED: str = "today"  # Equivalent to LinkedIn's r86400

    @property
    def search_sites_list(self) -> List[str]:
        return [s.strip() for s in self.SEARCH_SITES.split(",") if s.strip()]

    class Config:
        env_file = ".env"


settings = Settings()
