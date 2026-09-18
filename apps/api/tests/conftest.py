"""Pytest configuration and shared fixtures.

IMPORTANT (Engram #19 v1 gotcha):
  pydantic-settings reads env vars at Settings() instantiation time.
  If the app is imported before env vars are patched, defaults are frozen.
  We set required env vars in pytest_configure (session scope) BEFORE any
  backend.main import happens in test modules.
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Session-level env-var patch — runs before any test module is imported
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Patch required env vars before any app import."""
    os.environ.setdefault("LLM_BASE_URL", "http://localhost:1234/v1")
    os.environ.setdefault("LLM_API_KEY", "not-needed")
    os.environ.setdefault("CHAT_MODEL", "local-model")
    os.environ.setdefault("EMBEDDING_BASE_URL", "http://localhost:1234/v1")
    os.environ.setdefault("EMBEDDING_API_KEY", "not-needed")
    os.environ.setdefault("EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5")
    os.environ.setdefault("DATA_DIR", "./data")
    os.environ.setdefault("CHROMA_PERSIST_DIR", "./data/chroma")
    os.environ.setdefault("CHUNK_SIZE", "700")
    os.environ.setdefault("CHUNK_OVERLAP", "150")
    os.environ.setdefault("TOP_K", "4")
    os.environ.setdefault("SIMILARITY_THRESHOLD", "0.75")
    os.environ.setdefault("MAX_INGEST_BYTES", "5242880")
    os.environ.setdefault("APP_HOST", "127.0.0.1")
    os.environ.setdefault("APP_PORT", "8000")
    os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")


# ---------------------------------------------------------------------------
# Integration test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client() -> TestClient:
    """Return a TestClient for the FastAPI app.

    The app lifespan is executed on client creation.
    Note: tests that need to inject specific services (for integration testing)
    should create their own TestClient via a local app fixture, not use this one.
    This fixture uses the real app with full lifespan startup.
    """
    from backend.main import app

    return TestClient(app, raise_server_exceptions=False)
