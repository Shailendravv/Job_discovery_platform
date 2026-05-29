from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGODB_URI: str
    SEARXNG_URL: str
    CAMOFOX_URL: str
    Ollama: str
    SEARCH_NUM_RESULTS: int
    SETTLE_SECONDS: float = 1.5
    MAX_SNAPSHOT_CHARS: int = 3000
    MODEL_NAME: str = "qwen3.5:2b"
    MODEL_TEMPERATURE: float = 0.1

    class Config:
        env_file = ".env"


settings = Settings()
