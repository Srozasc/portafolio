"""Application configuration via pydantic-settings.

All env vars are declared here with defaults from design doc §6 / design.md Configuration table.
Local-by-default per design Decision 6 and preflight.

Defaults (LOCAL path, overridable via .env):
  LLM_BASE_URL        = "http://localhost:1234/v1"
  LLM_API_KEY         = "not-needed"
  CHAT_MODEL          = "local-model"
  EMBEDDING_BASE_URL  = (falls back to LLM_BASE_URL)
  EMBEDDING_API_KEY   = (falls back to LLM_API_KEY)
  EMBEDDING_MODEL     = "text-embedding-nomic-embed-text-v1.5"
  DATA_DIR            = "./data"
  CHROMA_PERSIST_DIR  = "./data/chroma"
  CHUNK_SIZE          = 700
  CHUNK_OVERLAP       = 150
  TOP_K               = 4
  SIMILARITY_THRESHOLD = 0.1
  MAX_INGEST_BYTES    = 5242880  (5 MiB)
  APP_HOST            = "127.0.0.1"
  APP_PORT            = 8000
  CORS_ALLOW_ORIGINS  = "http://localhost:8000,http://127.0.0.1:8000"

MiniMax chat defaults (uncommented in .env.example):
  LLM_BASE_URL  = "https://api.MiniMax.io/v1"
  LLM_API_KEY   = "<your_MiniMax_api_key>"
  CHAT_MODEL    = "MiniMax-M2.7-highspeed"

OpenAI embedding defaults (uncommented in .env.example):
  EMBEDDING_BASE_URL = "https://api.openai.com/v1"
  EMBEDDING_API_KEY  = "<your_openai_api_key>"
  EMBEDDING_MODEL    = "text-embedding-3-small"
"""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM / chat settings (MiniMax by default per locked design Decision 6)
    LLM_BASE_URL: str = "http://localhost:1234/v1"
    LLM_API_KEY: str = "not-needed"
    CHAT_MODEL: str = "local-model"

    # Embedding settings (falls back to LLM values when not set)
    EMBEDDING_BASE_URL: Optional[str] = None
    EMBEDDING_API_KEY: Optional[str] = None
    EMBEDDING_MODEL: str = "text-embedding-nomic-embed-text-v1.5"

    # Paths
    DATA_DIR: str = "./data"
    CHROMA_PERSIST_DIR: str = "./data/chroma"

    # Chunking
    CHUNK_SIZE: int = 700
    CHUNK_OVERLAP: int = 150

    # Retrieval
    TOP_K: int = 4
    SIMILARITY_THRESHOLD: float = 0.1

    # Ingest
    MAX_INGEST_BYTES: int = 5242880  # 5 MiB

    # Server
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    CORS_ALLOW_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000,http://localhost:4321,http://127.0.0.1:4321"
    CORS_ALLOW_VERCEL_REGEX: bool = True

    # -------------------------------------------------------------------------
    # Derived / computed properties
    # -------------------------------------------------------------------------

    @property
    def embedding_base_urlEffective(self) -> str:
        """Resolved embedding base URL (falls back to LLM_BASE_URL)."""
        return self.EMBEDDING_BASE_URL or self.LLM_BASE_URL

    @property
    def embedding_api_keyEffective(self) -> str:
        """Resolved embedding API key (falls back to LLM_API_KEY)."""
        return self.EMBEDDING_API_KEY or self.LLM_API_KEY


def get_settings() -> Settings:
    """Return a Settings instance loaded from current env vars.

    Lazy/single instance per call — pydantic-settings reads env at
    construction time, so a fresh instance always reflects the latest
    env. For hot-reload safety, callers that mutate env vars mid-process
    must call this again to pick up changes.
    """
    return Settings()
