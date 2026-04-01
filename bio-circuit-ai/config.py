from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    openai_api_key: str = ""
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "bio_parts"
    embedding_model: str = "all-MiniLM-L6-v2"
    llm_model: str = "gpt-4o"
    ncbi_email: str = ""
    ncbi_api_key: str = ""
    embedding_dim: int = 384

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
