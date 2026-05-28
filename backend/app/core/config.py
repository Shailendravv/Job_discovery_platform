from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGODB_URI: str
    SEARXNG_URL: str
    CAMOFOX_URL: str
    Ollama: str
    SEARCH_NUM_RESULTS: int

    class Config:
        env_file = ".env"


settings = Settings()
