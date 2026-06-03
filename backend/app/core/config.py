from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGODB_URI: str
    SEARXNG_URL: str
    CAMOFOX_URL: str
    Ollama: str
    SEARCH_MAX_RESULTS: int = 10
    BROWSE_TOP_N: int = 5
    SEARCH_SITES: str = "naukri.com,linkedin.com/jobs,apna.co,indeed.com,instahyre.com,shine.com,foundit.in"
    SEARCH_FRESH: bool = True
    SEARCH_CAREERS: bool = False
    SETTLE_SECONDS: float = 1.5
    MAX_SNAPSHOT_CHARS: int = 3000
    MODEL_NAME: str = "qwen2.5-coder:1.5b"
    MODEL_TEMPERATURE: float = 0.1

    @property
    def search_sites_list(self) -> List[str]:
        return [s.strip() for s in self.SEARCH_SITES.split(",") if s.strip()]

    class Config:
        env_file = ".env"


settings = Settings()
