from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGODB_URI: str
    SEARXNG_URL: str
    CAMOFOX_URL: str
    Ollama: str
    SEARCH_NUM_RESULTS: int       # legacy — used by MCP search tool directly
    SEARCH_MAX_RESULTS: int = 10  # per-query fetch count (search phase)
    BROWSE_TOP_N: int = 5         # top-N relevant results sent to browse/extract phase
    SETTLE_SECONDS: float = 1.5
    MAX_SNAPSHOT_CHARS: int = 3000
    MODEL_NAME: str = "qwen2.5-coder:1.5b"
    MODEL_TEMPERATURE: float = 0.1

    class Config:
        env_file = ".env"


settings = Settings()
