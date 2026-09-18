"""Integration tests for ChatService.

Uses real ChromaDB in tmp_path, mocked Embedder and LLMClient.
Central assertion (REQ-CHS-004): `mock_llm.call_count == 0` when the
retriever returns an empty hit list (deflection path, no LLM call).
Also covers: happy path, StreamError handling, unknown/ambiguous collection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock

import pytest

from backend.rag.chunker import Chunk, chunk_markdown
from backend.rag.embedder import Embedder
from backend.rag.llm_client import StreamError
from backend.rag.retriever import Retriever
from backend.rag.vector_store import Hit, VectorStore
from backend.services.chat_service import ChatService


# ---------------------------------------------------------------------------
# Mock LLM that yields scripted tokens
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Scripted LLM that yields a fixed token sequence or raises StreamError."""

    def __init__(self, tokens: list[str] | None = None, raise_exc: Exception | None = None):
        self.tokens = tokens or []
        self.raise_exc = raise_exc
        self.call_count = 0

    def stream_chat(self, system: str, user: str) -> Iterator[str]:
        self.call_count += 1
        for token in self.tokens:
            yield token
        if self.raise_exc:
            raise self.raise_exc


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def chroma_dir(tmp_path):
    return str(tmp_path / "chroma")


@pytest.fixture
def store(chroma_dir):
    return VectorStore(persist_dir=chroma_dir)


@pytest.fixture
def mock_embedder():
    """Mock embedder that returns a fixed 8-dim vector."""
    embedder = MagicMock(spec=Embedder)
    embedder.embed.return_value = [[0.1] * 8]
    return embedder


@pytest.fixture
def retriever(store, mock_embedder):
    return Retriever(store=store, embedder=mock_embedder)


# ---------------------------------------------------------------------------
# Helper: populate a collection in the store so retrieval can return []
# ---------------------------------------------------------------------------


def _setup_collection_with_no_hits(store, collection_name: str) -> None:
    """Create a collection with one chunk that will NOT match any question.

    We upsert a chunk with a fixed embedding vector [0.1]*8.
    The mock embedder always returns [0.1]*8 for any question,
    so cosine similarity = 1.0 (perfect match).
    To simulate "no hits above threshold", we need the stored vector to be
    far from the query vector. We can't easily do this with mocked embedder.
    Instead: we upsert with a known vector and the retriever is patched
    in the test to return [].
    """
    store.upsert(
        name=collection_name,
        ids=["chunk_0"],
        embeddings=[[0.9] * 8],  # very different from [0.1]*8
        documents=["Some document that will not match."],
        metadatas=[{"source": "test.md", "section_header": "Test", "chunk_index": 0, "char_start": 0, "char_end": 40}],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_central_deflection_no_llm_call(chroma_dir, retriever):
    """REQ-CHS-004: when retriever returns empty hits, LLM is never called.

    Setup: one collection exists, but retriever returns [] (threshold gates).
    Central assertion: events are exactly [content(deflection), done].
    """
    # Create a collection so the collection check passes
    _setup_collection_with_no_hits(retriever._store, "existing-col")

    # Override retrieve to return [] (threshold gates the response)
    retriever.retrieve = MagicMock(return_value=[])

    fake_llm = _FakeLLM(tokens=["should-not-be-called"])
    service = ChatService(retriever=retriever, llm=fake_llm)

    events = list(service.stream_answer("any question", collection="existing-col"))

    # Central assertion: LLM was NOT called
    assert fake_llm.call_count == 0, (
        f"LLM was called {fake_llm.call_count} time(s); "
        "expected 0 on the deflection path"
    )

    # Events: deflection content + done
    assert len(events) == 2
    assert events[0] == {"type": "content", "text": "No tengo información sobre eso."}
    assert events[1] == {"type": "done"}


def test_deflection_with_empty_retrieval_patched(retriever):
    """Explicit: retriever returns [] directly (no hits above threshold)."""
    # Create a collection so the collection check passes
    _setup_collection_with_no_hits(retriever._store, "test-col")

    # Override retrieve to return [] — simulates threshold gating
    retriever.retrieve = MagicMock(return_value=[])

    fake_llm = _FakeLLM(tokens=["should-not-be-called"])
    service = ChatService(retriever=retriever, llm=fake_llm)

    events = list(service.stream_answer("question", collection="test-col"))

    assert fake_llm.call_count == 0
    assert len(events) == 2
    assert events[0]["type"] == "content"
    assert events[0]["text"] == "No tengo información sobre eso."
    assert events[1]["type"] == "done"


def test_happy_path_with_hits(retriever):
    """When retriever returns hits, LLM is called and tokens are forwarded."""
    fake_llm = _FakeLLM(tokens=["token1", " token2", " token3"])

    # Set up retriever with mock hits
    fake_hits = [
        Hit(text="Some answer content.", metadata={"section_header": "FAQ"}, score=0.9),
        Hit(text="More content.", metadata={"section_header": "Notes"}, score=0.85),
    ]
    retriever.retrieve = MagicMock(return_value=fake_hits)

    # Set up a real collection so collection resolution succeeds
    retriever._store.upsert(
        name="test-collection",
        ids=["c0"],
        embeddings=[[0.1] * 8],
        documents=["Content."],
        metadatas=[{"source": "x.md", "section_header": "X", "chunk_index": 0, "char_start": 0, "char_end": 9}],
    )

    service = ChatService(retriever=retriever, llm=fake_llm)

    events = list(service.stream_answer("what is it?", collection="test-collection"))

    # LLM was called exactly once
    assert fake_llm.call_count == 1

    # Content events for each token
    content_events = [e for e in events if e["type"] == "content"]
    token_texts = [e["text"] for e in content_events]
    assert "".join(token_texts) == "token1 token2 token3"

    # Done sentinel present
    assert any(e["type"] == "done" for e in events)


def test_llm_midstream_error(retriever):
    """When LLM raises StreamError mid-stream, error + done are yielded."""
    stream_error = StreamError("Mid-stream error (RuntimeError)")
    failing_llm = _FakeLLM(
        tokens=["partial", " token"],
        raise_exc=stream_error,
    )

    fake_hits = [
        Hit(text="Some answer.", metadata={"section_header": "FAQ"}, score=0.9),
    ]
    retriever.retrieve = MagicMock(return_value=fake_hits)

    # Set up a real collection so collection resolution succeeds
    retriever._store.upsert(
        name="test-collection",
        ids=["c0"],
        embeddings=[[0.1] * 8],
        documents=["Content."],
        metadatas=[{"source": "x.md", "section_header": "X", "chunk_index": 0, "char_start": 0, "char_end": 9}],
    )

    service = ChatService(retriever=retriever, llm=failing_llm)

    events = list(service.stream_answer("question", collection="test-collection"))

    # LLM was called once before error
    assert failing_llm.call_count == 1

    # Content for tokens emitted before error
    content_events = [e for e in events if e["type"] == "content"]
    assert len(content_events) >= 1  # at least "partial" token

    # Error event with sanitised code
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) == 1
    assert error_events[0]["error"] == "LLM_ERROR"
    assert error_events[0]["message"] == "StreamError"  # class name only

    # Done sentinel present
    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1


def test_unknown_collection_explicit(retriever):
    """Explicit collection name that does not exist → error + done, no LLM call."""
    fake_llm = _FakeLLM(tokens=["should-not-be-called"])
    service = ChatService(retriever=retriever, llm=fake_llm)

    events = list(service.stream_answer("question", collection="nonexistent-collection"))

    assert fake_llm.call_count == 0
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) == 1
    assert error_events[0]["error"] == "UNKNOWN_COLLECTION"
    # Done must be present
    assert any(e["type"] == "done" for e in events)


def test_ambiguous_collection_no_override(chroma_dir, retriever):
    """No override + multiple collections → AMBIGUOUS_COLLECTION error, no LLM call."""
    # Ingest two collections directly
    retriever._store.upsert(
        name="col-a",
        ids=["c0"],
        embeddings=[[0.1] * 8],
        documents=["Content A."],
        metadatas=[{"source": "a.md", "section_header": "A", "chunk_index": 0, "char_start": 0, "char_end": 10}],
    )
    retriever._store.upsert(
        name="col-b",
        ids=["c0"],
        embeddings=[[0.1] * 8],
        documents=["Content B."],
        metadatas=[{"source": "b.md", "section_header": "B", "chunk_index": 0, "char_start": 0, "char_end": 10}],
    )

    fake_llm2 = _FakeLLM()
    service = ChatService(retriever=retriever, llm=fake_llm2)

    events = list(service.stream_answer("question", collection=None))

    assert fake_llm2.call_count == 0
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) == 1
    assert error_events[0]["error"] == "AMBIGUOUS_COLLECTION"
    assert any(e["type"] == "done" for e in events)


def test_single_collection_auto_resolved(chroma_dir, retriever):
    """No override + exactly one collection → uses that collection, LLM is called."""
    # Create exactly one collection
    retriever._store.upsert(
        name="only-one",
        ids=["c0"],
        embeddings=[[0.1] * 8],
        documents=["Content."],
        metadatas=[{"source": "x.md", "section_header": "X", "chunk_index": 0, "char_start": 0, "char_end": 9}],
    )

    fake_llm2 = _FakeLLM(tokens=["respuesta"])
    service = ChatService(retriever=retriever, llm=fake_llm2)

    events = list(service.stream_answer("pregunta", collection=None))

    assert fake_llm2.call_count == 1
    content_events = [e for e in events if e["type"] == "content"]
    assert any("respuesta" in e["text"] for e in content_events)
    assert any(e["type"] == "done" for e in events)


def test_collection_override_uses_explicit_name(chroma_dir, retriever):
    """Explicit collection_override is used without auto-resolution."""
    retriever._store.upsert(
        name="explicit-col",
        ids=["c0"],
        embeddings=[[0.1] * 8],
        documents=["Explicit content."],
        metadatas=[{"source": "x.md", "section_header": "X", "chunk_index": 0, "char_start": 0, "char_end": 16}],
    )

    fake_llm2 = _FakeLLM(tokens=["explicit answer"])
    service = ChatService(retriever=retriever, llm=fake_llm2)

    events = list(service.stream_answer("question", collection="explicit-col"))

    assert fake_llm2.call_count == 1
    assert any(e["type"] == "done" for e in events)


def test_veto_no_llm_call_on_zero_collections(retriever):
    """With 0 collections and collection=None: UNKNOWN_COLLECTION, not deflection."""
    # ChromaDB is empty — this is a different error from "no hits above threshold"
    fake_llm = _FakeLLM(tokens=["should-not-be-called"])
    service = ChatService(retriever=retriever, llm=fake_llm)

    events = list(service.stream_answer("question", collection=None))

    assert fake_llm.call_count == 0
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) == 1
    assert error_events[0]["error"] == "UNKNOWN_COLLECTION"
    assert any(e["type"] == "done" for e in events)


# ---------------------------------------------------------------------------
# Think-block stripping (MiniMax-M2.7-highspeed emits <think>...</think>
# reasoning blocks that the system prompt forbids; ChatService strips them
# before forwarding tokens to the SSE stream)
# ---------------------------------------------------------------------------


class _RetrieverWithOneHit:
    """Minimal retriever stand-in returning a single hit so the chat
    service proceeds to call the LLM."""

    class _Store:
        def list_collections(self):
            return ["knowledge"]

    def __init__(self):
        self._store = self._Store()

    def retrieve(self, question, collection, *, top_k=4, threshold=None):
        return [
            Hit(
                text="GestorDocs acepta .md y .markdown.",
                metadata={"section_header": "1. Introducción", "chunk_index": 1},
                score=0.5,
            )
        ]


def _gather(events):
    """Return concatenated content text from a list of StreamEvent dicts."""
    return "".join(e["text"] for e in events if e["type"] == "content")


def test_strips_think_block_from_llm_output():
    """Tokens containing <think>...</think> must not leak to the client."""
    fake_llm = _FakeLLM(
        tokens=[
            "<think>\n",
            "reasoning here\n",
            "</think>\n",
            "La respuesta es .md y .markdown.",
        ]
    )
    svc = ChatService(retriever=_RetrieverWithOneHit(), llm=fake_llm)
    events = list(svc.stream_answer("extensiones?", collection=None))
    content_text = _gather(events)
    assert "<think>" not in content_text
    assert "</think>" not in content_text
    assert "reasoning here" not in content_text
    assert "La respuesta es .md y .markdown." in content_text


def test_think_block_split_across_tokens():
    """The <think> tag may be split across multiple streaming tokens.

    Realistic split: the opening tag chars come in separate tokens but
    the closing tag arrives intact.
    """
    fake_llm = _FakeLLM(
        tokens=["<th", "in", "k>reasoning</think>Hola mundo"]
    )
    svc = ChatService(retriever=_RetrieverWithOneHit(), llm=fake_llm)
    content_text = _gather(list(svc.stream_answer("q", collection=None)))
    assert content_text == "Hola mundo"


def test_unclosed_think_block_is_dropped():
    """If the LLM forgets to close <think>, drop the buffered content
    rather than leak it to the client."""
    fake_llm = _FakeLLM(tokens=["<think>reasoning que nunca cierra"])
    svc = ChatService(retriever=_RetrieverWithOneHit(), llm=fake_llm)
    content_text = _gather(list(svc.stream_answer("q", collection=None)))
    assert content_text == ""


def test_no_think_block_passes_through():
    """Normal LLM output without <think> tags is untouched."""
    fake_llm = _FakeLLM(tokens=["Hola", " mundo", "!"])
    svc = ChatService(retriever=_RetrieverWithOneHit(), llm=fake_llm)
    content_text = _gather(list(svc.stream_answer("q", collection=None)))
    assert content_text == "Hola mundo!"
