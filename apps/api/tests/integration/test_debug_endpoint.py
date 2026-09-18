"""Integration tests for POST /api/_debug/retrieve diagnostic endpoint.

Uses the same app.dependency_overrides pattern from test_chat_endpoint.py.
Real ChromaDB in tmp_path, mocked LLM, no network calls.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.debug import router as debug_router, _get_chat_service
from backend.api.errors import register_exception_handlers
from backend.rag.vector_store import VectorStore
from backend.rag.retriever import Retriever
from backend.services.chat_service import ChatService


# ---------------------------------------------------------------------------
# Fake LLM (not used by debug endpoint but required by ChatService init)
# ---------------------------------------------------------------------------


class FakeLLM:
    def stream_chat(self, system: str, user: str):
        yield "fake"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_fake_embedder():
    class _FakeEmbedder:
        dim = 8

        def embed(self, texts):
            return [[0.5] * self.dim for _ in texts]

    return _FakeEmbedder()


def make_debug_test_app(chroma_dir: Path):
    """Create a FastAPI app with the debug route mounted.

    Returns (app, client, service).
    """
    app = FastAPI()
    register_exception_handlers(app)

    store = VectorStore(str(chroma_dir))
    embedder = make_fake_embedder()
    retriever = Retriever(store=store, embedder=embedder)
    service = ChatService(retriever=retriever, llm=FakeLLM())

    app.state.chat_service = service
    app.dependency_overrides[_get_chat_service] = lambda: service
    app.include_router(debug_router)
    client = TestClient(app, raise_server_exceptions=False)
    return app, client, service


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDebugRetrieveHappyPath:
    """Happy path: raw hits returned with scores."""

    def test_debug_retrieve_returns_top_k_hits(self, tmp_path: Path):
        """When collection has chunks, returns up to top_k hits with scores."""
        app, client, service = make_debug_test_app(tmp_path)

        store = app.state.chat_service.retriever._store
        store.upsert(
            name="debug-coll",
            ids=["c1", "c2", "c3"],
            embeddings=[[0.5] * 8, [0.4] * 8, [0.3] * 8],
            documents=[
                "Este es el primer documento de prueba.",
                "Segundo documento con contenido diferente.",
                "Tercer documento para completar.",
            ],
            metadatas=[
                {"section_header": "Intro", "source": "doc1.md", "chunk_index": 0, "char_start": 0, "char_end": 35},
                {"section_header": "Body", "source": "doc2.md", "chunk_index": 0, "char_start": 0, "char_end": 40},
                {"section_header": "End", "source": "doc3.md", "chunk_index": 0, "char_start": 0, "char_end": 30},
            ],
        )

        response = client.post(
            "/api/_debug/retrieve",
            json={"question": "¿Qué es esto?", "collection": "debug-coll", "top_k": 10},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["question"] == "¿Qué es esto?"
        assert data["resolved_collection"] == "debug-coll"
        assert len(data["hits"]) == 3
        for hit in data["hits"]:
            assert "score" in hit
            assert "text" in hit
            assert "metadata" in hit
            assert "snippet" in hit
            assert len(hit["snippet"]) <= 200

    def test_debug_retrieve_resolves_single_collection_automatically(self, tmp_path: Path):
        """When collection=None and exactly one collection exists, it is used."""
        app, client, service = make_debug_test_app(tmp_path)

        store = app.state.chat_service.retriever._store
        store.upsert(
            name="only-coll",
            ids=["c1"],
            embeddings=[[0.5] * 8],
            documents=["Unico documento."],
            metadatas=[{"section_header": "", "source": "d.md", "chunk_index": 0, "char_start": 0, "char_end": 17}],
        )

        response = client.post(
            "/api/_debug/retrieve",
            json={"question": "Pregunta", "top_k": 5},
        )
        assert response.status_code == 200
        assert response.json()["resolved_collection"] == "only-coll"


class TestDebugRetrieveThresholdZero:
    """threshold=0.0 bypass: low-score hits still appear."""

    def test_debug_retrieve_threshold_zero_includes_low_score_hits(self, tmp_path: Path):
        """With threshold=0.0, even very-low-score hits are returned.

        This is the key diagnostic capability: in production the threshold
        (0.75) filters out chunks that still contain relevant information.
        The debug endpoint uses threshold=0.0 to expose those candidates.
        """
        app, client, service = make_debug_test_app(tmp_path)

        store = app.state.chat_service.retriever._store
        # FakeEmbedder always returns [0.5]*8 for any query.
        # Store one embedding at exactly [0.5]*8 (similarity=1.0) and
        # one at [0.4]*8 (small euclidean distance, moderate similarity).
        # With threshold=0.75 production filter, only the first would pass.
        # With threshold=0.0 in the debug endpoint, both are returned.
        store.upsert(
            name="low-score-coll",
            ids=["c1", "c2"],
            embeddings=[[0.5] * 8, [0.4] * 8],
            documents=["Alta similitud.", "Baja similitud."],
            metadatas=[
                {"section_header": "A", "source": "a.md", "chunk_index": 0, "char_start": 0, "char_end": 16},
                {"section_header": "B", "source": "b.md", "chunk_index": 0, "char_start": 0, "char_end": 16},
            ],
        )

        response = client.post(
            "/api/_debug/retrieve",
            json={"question": "Prueba", "collection": "low-score-coll", "top_k": 10},
        )
        assert response.status_code == 200
        hits = response.json()["hits"]
        # Both hits returned with threshold=0.0; in production (0.75) only
        # the first would pass the filter
        assert len(hits) == 2
        scores = [h["score"] for h in hits]
        assert scores == sorted(scores, reverse=True)  # descending


class TestDebugRetrieveErrors:
    """Error envelope consistency with backend/api/errors.py."""

    def test_debug_retrieve_unknown_collection_returns_error(self, tmp_path: Path):
        """Unknown explicit collection → 404 UNKNOWN_COLLECTION."""
        app, client, service = make_debug_test_app(tmp_path)

        response = client.post(
            "/api/_debug/retrieve",
            json={"question": "¿Qué es esto?", "collection": "no-existe"},
        )
        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "UNKNOWN_COLLECTION"

    def test_debug_retrieve_ambiguous_collection_returns_error(self, tmp_path: Path):
        """No override + multiple collections → 400 AMBIGUOUS_COLLECTION."""
        app, client, service = make_debug_test_app(tmp_path)

        store = app.state.chat_service.retriever._store
        store.upsert(
            name="coll-x",
            ids=["c1"],
            embeddings=[[0.1] * 8],
            documents=["Doc X."],
            metadatas=[{"section_header": "", "source": "x.md", "chunk_index": 0, "char_start": 0, "char_end": 6}],
        )
        store.upsert(
            name="coll-y",
            ids=["c2"],
            embeddings=[[0.2] * 8],
            documents=["Doc Y."],
            metadatas=[{"section_header": "", "source": "y.md", "chunk_index": 0, "char_start": 0, "char_end": 6}],
        )

        response = client.post(
            "/api/_debug/retrieve",
            json={"question": "¿Qué es esto?"},
        )
        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "AMBIGUOUS_COLLECTION"

    def test_debug_retrieve_empty_question_returns_400(self, tmp_path: Path):
        """Empty question string → 400 MISSING_QUESTION (via error handler)."""
        app, client, service = make_debug_test_app(tmp_path)

        response = client.post(
            "/api/_debug/retrieve",
            json={"question": "", "collection": "any"},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "MISSING_QUESTION"
