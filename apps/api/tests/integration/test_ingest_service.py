"""Integration tests for IngestService.

Uses real ChromaDB in tmp_path, mocked Embedder.
Covers: happy path, validation errors, idempotent re-ingest (REQ-ING-007),
collection_override.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.config import Settings
from backend.rag.chunker import Chunk, chunk_markdown
from backend.rag.vector_store import VectorStore
from backend.services.ingest_service import (
    FileTooLargeError,
    IngestService,
    UnsupportedExtensionError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_embedder(return_vectors: list[list[float]]):
    """Return a mock embedder that yields predetermined embedding vectors."""
    embedder = MagicMock()
    embedder.embed.return_value = return_vectors
    return embedder


def _small_chunker(chunks: list[Chunk]):
    """Return a mock chunker that returns a predetermined chunk list."""
    fn = MagicMock()
    fn.return_value = chunks
    return fn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def chroma_dir(tmp_path):
    """Real ChromaDB in a temporary directory."""
    return str(tmp_path / "chroma")


@pytest.fixture
def store(chroma_dir):
    """Real VectorStore backed by tmp_path."""
    return VectorStore(persist_dir=chroma_dir)


@pytest.fixture
def embedder():
    """Mock embedder returning deterministic 8-dim vectors."""
    vector = [0.1] * 8
    return _mock_embedder([vector] * 10)


@pytest.fixture
def settings():
    """Default application settings."""
    return Settings()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_happy_path(chroma_dir, store, embedder, settings):
    """Ingest a small .md file and verify the IngestResult fields."""
    # Create a small markdown file
    md_path = Path(chroma_dir).parent / "test.md"
    md_path.write_text("# Hello\n\nWorld content here.", encoding="utf-8")

    # Deterministic chunks (one chunk)
    chunks = [
        Chunk(
            text="# Hello\n\nWorld content here.",
            source=str(md_path.resolve()),
            section_header="Hello",
            chunk_index=0,
            char_start=0,
            char_end=30,
            token_count=8,
        )
    ]
    chunker = _small_chunker(chunks)
    embedder = _mock_embedder([[0.1] * 8])

    service = IngestService(
        chunker=chunker,
        embedder=embedder,
        store=store,
        settings=settings,
    )

    result = service.ingest_file(str(md_path))

    assert result.collection == "test"
    assert result.chunks_indexed == 1
    assert result.total_chars > 0
    assert result.duration_ms >= 0

    # Verify ChromaDB state
    assert store.list_collections() == ["test"]
    hits = store.query(
        name="test",
        embedding=[0.1] * 8,
        top_k=1,
        threshold=0.0,
    )
    assert len(hits) == 1
    assert "World content here" in hits[0].text


def test_file_not_found(store, embedder, settings):
    """Non-existent file raises FileNotFoundError."""
    service = IngestService(
        chunker=MagicMock(),
        embedder=embedder,
        store=store,
        settings=settings,
    )
    with pytest.raises(FileNotFoundError):
        service.ingest_file("/nonexistent/path/xyz.md")


def test_unsupported_extension(chroma_dir, store, embedder, settings):
    """.txt extension raises UnsupportedExtensionError."""
    txt_path = Path(chroma_dir).parent / "notes.txt"
    txt_path.write_text("some content", encoding="utf-8")

    service = IngestService(
        chunker=MagicMock(),
        embedder=embedder,
        store=store,
        settings=settings,
    )
    with pytest.raises(UnsupportedExtensionError):
        service.ingest_file(str(txt_path))


def test_file_too_large(chroma_dir, store, embedder, settings):
    """File exceeding MAX_INGEST_BYTES raises FileTooLargeError."""
    large_path = Path(chroma_dir).parent / "large.md"
    # Write content larger than MAX_INGEST_BYTES (default 5 MiB = 5_242_880 bytes)
    large_path.write_text("x" * (settings.MAX_INGEST_BYTES + 6), encoding="utf-8")

    service = IngestService(
        chunker=MagicMock(),
        embedder=embedder,
        store=store,
        settings=settings,
    )
    with pytest.raises(FileTooLargeError):
        service.ingest_file(str(large_path))


def test_idempotent_reingest(chroma_dir, store, settings):
    """REQ-ING-007: re-ingesting the same file replaces chunks (no duplicates)."""
    md_path = Path(chroma_dir).parent / "notes.md"
    md_path.write_text("# Notes\n\nInitial content.", encoding="utf-8")

    # First ingest: 1 chunk
    chunks_v1 = [
        Chunk(
            text="# Notes\n\nInitial content.",
            source=str(md_path.resolve()),
            section_header="Notes",
            chunk_index=0,
            char_start=0,
            char_end=30,
            token_count=8,
        )
    ]
    embedder_v1 = _mock_embedder([[0.1] * 8])
    service = IngestService(
        chunker=_small_chunker(chunks_v1),
        embedder=embedder_v1,
        store=store,
        settings=settings,
    )
    r1 = service.ingest_file(str(md_path))
    assert r1.chunks_indexed == 1

    # Second ingest: same path, 2 chunks (simulate content change)
    chunks_v2 = [
        Chunk(
            text="# Notes\n\nInitial content. More text here.",
            source=str(md_path.resolve()),
            section_header="Notes",
            chunk_index=0,
            char_start=0,
            char_end=45,
            token_count=12,
        ),
        Chunk(
            text="Extra second chunk content.",
            source=str(md_path.resolve()),
            section_header="Notes",
            chunk_index=1,
            char_start=45,
            char_end=75,
            token_count=6,
        ),
    ]
    embedder_v2 = _mock_embedder([[0.2] * 8, [0.3] * 8])
    service2 = IngestService(
        chunker=_small_chunker(chunks_v2),
        embedder=embedder_v2,
        store=store,
        settings=settings,
    )
    r2 = service2.ingest_file(str(md_path))

    # Chunk count should be 2 (replaced, not appended)
    assert r2.chunks_indexed == 2
    assert r2.collection == "notes"  # same collection name

    # Query to confirm there are exactly 2 chunks
    all_hits = store.query(
        name="notes",
        embedding=[0.2] * 8,
        top_k=10,
        threshold=0.0,
    )
    assert len(all_hits) == 2


def test_collection_override(chroma_dir, store, settings):
    """collection_override is used instead of slugify(stem(...))."""
    md_path = Path(chroma_dir).parent / "My Doc.md"
    md_path.write_text("# Title\n\nContent.", encoding="utf-8")

    chunks = [
        Chunk(
            text="# Title\n\nContent.",
            source=str(md_path.resolve()),
            section_header="Title",
            chunk_index=0,
            char_start=0,
            char_end=20,
            token_count=5,
        )
    ]
    embedder = _mock_embedder([[0.5] * 8])
    service = IngestService(
        chunker=_small_chunker(chunks),
        embedder=embedder,
        store=store,
        settings=settings,
    )

    result = service.ingest_file(str(md_path), collection_override="custom-name")

    assert result.collection == "custom-name"
    assert store.list_collections() == ["custom-name"]


def test_delete_called_before_upsert(chroma_dir, store, settings):
    """delete_collection is called before upsert (idempotency proof)."""
    md_path = Path(chroma_dir).parent / "test_del.md"
    md_path.write_text("# Test\n\nContent.", encoding="utf-8")

    chunks = [
        Chunk(
            text="# Test\n\nContent.",
            source=str(md_path.resolve()),
            section_header="Test",
            chunk_index=0,
            char_start=0,
            char_end=20,
            token_count=5,
        )
    ]
    embedder = _mock_embedder([[0.1] * 8])

    # Track call order with timestamps
    call_order: list[str] = []
    original_delete = store.delete_collection
    original_upsert = store.upsert

    def spy_delete(name: str):
        call_order.append(f"delete:{name}")
        return original_delete(name)

    def spy_upsert(name, ids, embeddings, documents, metadatas):
        call_order.append(f"upsert:{name}")
        return original_upsert(name, ids, embeddings, documents, metadatas)

    store.delete_collection = spy_delete
    store.upsert = spy_upsert

    service = IngestService(
        chunker=_small_chunker(chunks),
        embedder=embedder,
        store=store,
        settings=settings,
    )
    service.ingest_file(str(md_path))

    # Verify delete comes before upsert
    delete_index = next(i for i, c in enumerate(call_order) if c.startswith("delete:"))
    upsert_index = next(i for i, c in enumerate(call_order) if c.startswith("upsert:"))
    assert delete_index < upsert_index, f"Expected delete before upsert, got: {call_order}"
