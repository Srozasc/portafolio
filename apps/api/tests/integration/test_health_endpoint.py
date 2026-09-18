"""Integration tests for GET /api/health endpoint.

See design.md spec REQ-HST-001..003 / WU 3.4.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.health import router as health_router, _get_health_service
from backend.api.errors import register_exception_handlers
from backend.config import Settings
from backend.rag.vector_store import VectorStore
from backend.rag.embedder import Embedder
from backend.rag.retriever import Retriever
from backend.services.health_service import HealthService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_fake_embedder():
    class _FakeEmbedder:
        dim = 8
        def embed(self, texts):
            return [[0.0] * self.dim for _ in texts]
    return _FakeEmbedder()


def make_health_test_app(chroma_dir: Path, chat_model="local-model", embedding_model="text-embedding-nomic-embed-text-v1.5") -> tuple[FastAPI, TestClient, HealthService]:
    """Create a FastAPI app with the health route mounted."""
    from backend.api.routes.health import _get_health_service

    app = FastAPI()
    register_exception_handlers(app)

    store = VectorStore(str(chroma_dir))
    embedder = make_fake_embedder()
    service = HealthService(store=store, chat_model=chat_model, embedding_model=embedding_model)

    app.state.health_service = service
    app.dependency_overrides[_get_health_service] = lambda: service
    app.include_router(health_router)

    client = TestClient(app, raise_server_exceptions=False)
    return app, client, service


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealthEndpointOneCollection:
    """REQ-HST-001: 200 with one collection stats."""

    def test_health_with_one_collection_returns_200(self, tmp_path: Path):
        """GET /api/health with one collection → 200 with collection stats."""
        app, client, service = make_health_test_app(tmp_path)

        # Create a collection with some chunks
        store = app.state.health_service._store
        store.upsert(
            name="knowledge",
            ids=[f"c{i}" for i in range(5)],
            embeddings=[[0.5] * 8 for _ in range(5)],
            documents=[f"Document {i} content." for i in range(5)],
            metadatas=[
                {"section_header": "", "source": "test.md", "chunk_index": i, "char_start": i * 10, "char_end": (i + 1) * 10}
                for i in range(5)
            ],
        )

        response = client.get("/api/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ok"
        assert data["model"] == "local-model"
        assert data["embedding_model"] == "text-embedding-nomic-embed-text-v1.5"
        assert len(data["collections"]) == 1
        assert data["collections"][0]["collection_name"] == "knowledge"
        assert data["collections"][0]["chunk_count"] == 5


class TestHealthEndpointEmpty:
    """REQ-HST-001: 200 with empty ChromaDB."""

    def test_health_empty_returns_200(self, tmp_path: Path):
        """GET /api/health with no collections → 200 with empty collections list."""
        app, client, service = make_health_test_app(tmp_path)

        response = client.get("/api/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ok"
        assert data["collections"] == []


class TestHealthEndpoint503:
    """REQ-HST-002: 503 when ChromaDB unreachable."""

    def test_health_unreachable_returns_503(self, tmp_path: Path):
        """GET /api/health with unreadable persist dir → 503."""
        app, client, service = make_health_test_app(tmp_path)

        # Replace the store with a wrapper that raises on stats()
        class FailingStore:
            def stats(self):
                raise RuntimeError("ChromaDB unreachable")

        app.state.health_service._store = FailingStore()

        response = client.get("/api/health")
        assert response.status_code == 503
        data = response.json()
        assert data["error"] == "VECTOR_STORE_UNAVAILABLE"
