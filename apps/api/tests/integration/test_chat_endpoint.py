"""Integration tests for POST /api/chat/stream SSE endpoint.

See design.md Decision 3, spec REQ-CHS-001..007 / WU 3.3.

Uses a standalone FastAPI app with the chat route mounted, real ChromaDB in tmp_path,
and a scripted fake LLM to avoid network calls.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.chat import router as chat_router, _get_chat_service
from backend.api.errors import register_exception_handlers
from backend.config import Settings
from backend.rag.vector_store import VectorStore
from backend.rag.embedder import Embedder
from backend.rag.retriever import Retriever
from backend.rag.llm_client import StreamError
from backend.services.chat_service import ChatService


# ---------------------------------------------------------------------------
# Fake LLM (scripted token sequence)
# ---------------------------------------------------------------------------

class FakeLLM:
    """Scripted LLM that yields canned tokens then stops."""

    def __init__(self, tokens: list[str] | None = None, raise_after: int | None = None):
        self.tokens = tokens or ["Hello", " world", "!"]
        self.raise_after = raise_after
        self.call_count = 0
        self.last_system = None
        self.last_user = None

    def stream_chat(self, system: str, user: str) -> Iterator[str]:
        self.call_count += 1
        self.last_system = system
        self.last_user = user
        for i, token in enumerate(self.tokens):
            if self.raise_after is not None and i >= self.raise_after:
                raise StreamError("FakeError")
            yield token


class FakeRetriever:
    """Fake retriever returning scripted hits (bypasses ChromaDB for unit-like testing)."""

    def __init__(self, hits: list, store=None):
        self._hits = hits
        self._store = store

    def retrieve(self, question: str, collection: str, **kwargs):
        return self._hits


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_fake_embedder():
    class _FakeEmbedder:
        dim = 8
        def embed(self, texts):
            return [[0.5] * self.dim for _ in texts]
    return _FakeEmbedder()


def parse_sse_lines(raw: str) -> list[dict]:
    """Parse SSE-formatted response into list of event dicts."""
    events = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def make_chat_test_app(chroma_dir: Path, fake_llm) -> tuple[FastAPI, TestClient, ChatService]:
    """Create a FastAPI app with the chat route mounted.

    Returns (app, client, service). Uses dependency_overrides to inject the service.
    """
    app = FastAPI()
    register_exception_handlers(app)

    store = VectorStore(str(chroma_dir))
    embedder = make_fake_embedder()
    retriever = FakeRetriever(hits=[], store=store)
    service = ChatService(retriever=retriever, llm=fake_llm)

    app.state.chat_service = service
    app.dependency_overrides[_get_chat_service] = lambda: service
    app.include_router(chat_router)
    client = TestClient(app, raise_server_exceptions=False)
    return app, client, service


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestChatEndpointHappyPath:
    """Coherent answer path."""

    def test_coherent_stream_yields_content_then_done(self, tmp_path: Path):
        """Normal LLM response: content tokens + done sentinel."""
        fake_llm = FakeLLM(tokens=["Este", " es", " un", " respuesta."])
        app, client, service = make_chat_test_app(tmp_path, fake_llm)

        # Switch to real retriever and add a collection so retrieval finds hits
        embedder = make_fake_embedder()
        real_retriever = Retriever(store=app.state.chat_service._retriever._store, embedder=embedder)
        service._retriever = real_retriever
        store = app.state.chat_service._retriever._store
        store.upsert(
            name="test-coll",
            ids=["c1"],
            embeddings=[[0.5] * 8],
            documents=["Test document content."],
            metadatas=[{"section_header": "Test", "source": "test.md", "chunk_index": 0, "char_start": 0, "char_end": 20}],
        )

        response = client.post(
            "/api/chat/stream",
            json={"question": "¿Qué es esto?", "collection": "test-coll"},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        events = parse_sse_lines(response.text)
        content_events = [e for e in events if e.get("type") == "content"]
        done_events = [e for e in events if e.get("type") == "done"]

        assert len(content_events) == len(fake_llm.tokens)
        assert len(done_events) == 1


class TestChatEndpointDeflection:
    """REQ-CHS-004: canonical deflection, LLM never called.

    Deflection fires when collection is resolved AND retriever returns 0 hits.
    With FakeRetriever returning empty hits and collection explicitly set to an
    existing (but empty) collection, deflection should fire.
    """

    def test_deflection_returns_exact_phrase_and_llm_not_called(self, tmp_path: Path):
        """Deflection path: content = deflection text, done, LLM not called."""
        fake_llm = FakeLLM(tokens=["Should not appear"])
        app, client, service = make_chat_test_app(tmp_path, fake_llm)

        # Create a collection with 0 embeddings (ChromaDB will have it but retriever gets 0 hits)
        # OR: use the FakeRetriever which always returns [] hits
        store = app.state.chat_service._retriever._store
        # Create the collection (it'll exist but have no chunks since we don't upsert)
        # ChromaDB get_or_create makes empty collections possible
        store.get_or_create("empty-coll")

        response = client.post(
            "/api/chat/stream",
            json={"question": "¿Qué es X?", "collection": "empty-coll"},
        )
        assert response.status_code == 200

        events = parse_sse_lines(response.text)
        content_events = [e for e in events if e.get("type") == "content"]
        done_events = [e for e in events if e.get("type") == "done"]

        assert len(content_events) == 1
        assert content_events[0]["text"] == "No tengo información sobre eso."
        assert len(done_events) == 1
        # LLM was never called (REQ-CHS-004 central assertion)
        assert fake_llm.call_count == 0


class TestChatEndpointLLMError:
    """Mid-stream LLM error yields error event then done."""

    def test_llm_error_yields_error_then_done(self, tmp_path: Path):
        """LLM raises StreamError mid-stream: error event + done."""
        fake_llm = FakeLLM(tokens=["First", " token"], raise_after=0)
        app, client, service = make_chat_test_app(tmp_path, fake_llm)

        # Use real retriever with a collection so LLM path fires
        embedder = make_fake_embedder()
        store = app.state.chat_service._retriever._store
        real_retriever = Retriever(store=store, embedder=embedder)
        service._retriever = real_retriever
        store.upsert(
            name="test-coll-llm-err",
            ids=["c1"],
            embeddings=[[0.5] * 8],
            documents=["Test."],
            metadatas=[{"section_header": "T", "source": "t.md", "chunk_index": 0, "char_start": 0, "char_end": 5}],
        )

        response = client.post(
            "/api/chat/stream",
            json={"question": "¿Qué es?", "collection": "test-coll-llm-err"},
        )
        # HTTP 200 even on LLM error (headers already sent per Decision 3)
        assert response.status_code == 200

        events = parse_sse_lines(response.text)
        error_events = [e for e in events if e.get("type") == "error"]
        done_events = [e for e in events if e.get("type") == "done"]

        assert len(error_events) >= 1
        assert error_events[0]["error"] == "LLM_ERROR"
        assert len(done_events) == 1


class TestChatEndpointMissingQuestion:
    """400 MISSING_QUESTION when question is absent/empty."""

    def test_missing_question_returns_400(self, tmp_path: Path):
        """Empty question string → 400 MISSING_QUESTION."""
        fake_llm = FakeLLM()
        app, client, service = make_chat_test_app(tmp_path, fake_llm)

        response = client.post("/api/chat/stream", json={"question": ""})
        assert response.status_code == 400
        assert response.json()["error"] == "MISSING_QUESTION"

    def test_missing_question_field_returns_400(self, tmp_path: Path):
        """Missing question field → 400 MISSING_QUESTION."""
        fake_llm = FakeLLM()
        app, client, service = make_chat_test_app(tmp_path, fake_llm)

        response = client.post("/api/chat/stream", json={})
        assert response.status_code == 400
        assert response.json()["error"] == "MISSING_QUESTION"


class TestChatEndpointInvalidBody:
    """400 INVALID_BODY on malformed JSON."""

    def test_malformed_json_returns_400(self, tmp_path: Path):
        """Non-JSON body → 400 INVALID_BODY."""
        fake_llm = FakeLLM()
        app, client, service = make_chat_test_app(tmp_path, fake_llm)

        response = client.post(
            "/api/chat/stream",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_BODY"


class TestChatEndpointUnknownCollection:
    """404 UNKNOWN_COLLECTION when explicit collection not found."""

    def test_unknown_collection_returns_error_event(self, tmp_path: Path):
        """Explicit unknown collection → SSE error event (service yields error + done)."""
        fake_llm = FakeLLM()
        app, client, service = make_chat_test_app(tmp_path, fake_llm)

        # Store is empty; explicit unknown collection
        response = client.post(
            "/api/chat/stream",
            json={"question": "¿Qué es esto?", "collection": "nonexistent-collection"},
        )
        # The service yields UNKNOWN_COLLECTION error as SSE event
        assert response.status_code == 200
        events = parse_sse_lines(response.text)
        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) >= 1
        assert error_events[0]["error"] == "UNKNOWN_COLLECTION"


class TestChatEndpointAmbiguousCollection:
    """400 AMBIGUOUS_COLLECTION when no override and multiple collections exist."""

    def test_ambiguous_collection_returns_error_event(self, tmp_path: Path):
        """No override + multiple collections → SSE error event (service yields error + done)."""
        fake_llm = FakeLLM()
        app, client, service = make_chat_test_app(tmp_path, fake_llm)

        # Create two collections in ChromaDB
        store = app.state.chat_service._retriever._store
        store.upsert(
            name="coll-a",
            ids=["c1"],
            embeddings=[[0.1] * 8],
            documents=["doc a"],
            metadatas=[{"section_header": "", "source": "a.md", "chunk_index": 0, "char_start": 0, "char_end": 10}],
        )
        store.upsert(
            name="coll-b",
            ids=["c2"],
            embeddings=[[0.2] * 8],
            documents=["doc b"],
            metadatas=[{"section_header": "", "source": "b.md", "chunk_index": 0, "char_start": 0, "char_end": 10}],
        )

        response = client.post(
            "/api/chat/stream",
            json={"question": "¿Qué es esto?"},
        )
        # The service yields AMBIGUOUS_COLLECTION error as SSE event
        assert response.status_code == 200
        events = parse_sse_lines(response.text)
        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) >= 1
        assert error_events[0]["error"] == "AMBIGUOUS_COLLECTION"
