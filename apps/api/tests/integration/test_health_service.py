"""Integration tests for HealthService.

Uses real ChromaDB in tmp_path.
Covers: 200 with collections, 200 with empty ChromaDB, 503 on unreachable store.
No mutations (REQ-HST-003).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.rag.vector_store import CollectionStats, VectorStore
from backend.services.health_service import HealthService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def chroma_dir(tmp_path):
    return str(tmp_path / "chroma")


@pytest.fixture
def store(chroma_dir):
    return VectorStore(persist_dir=chroma_dir)


@pytest.fixture
def health_service(store):
    return HealthService(
        store=store,
        chat_model="MiniMax-M2.7-highspeed",
        embedding_model="text-embedding-3-small",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_healthy_with_one_collection(chroma_dir, store, health_service):
    """200 with one collection populated (REQ-HST-001)."""
    # Upsert directly so we control the collection name
    store.upsert(
        name="knowledge",
        ids=["chunk_0"],
        embeddings=[[0.1] * 8],
        documents=["Some document text."],
        metadatas=[{"source": "test.md", "section_header": "Test", "chunk_index": 0, "char_start": 0, "char_end": 20}],
    )

    result = health_service.status()

    assert result["status"] == "ok"
    assert result["model"] == "MiniMax-M2.7-highspeed"
    assert result["embedding_model"] == "text-embedding-3-small"
    assert len(result["collections"]) == 1
    assert result["collections"][0]["collection_name"] == "knowledge"
    assert result["collections"][0]["chunk_count"] == 1


def test_healthy_with_multiple_collections(store, health_service):
    """200 with multiple collections."""
    store.upsert(
        name="col1",
        ids=["chunk_0"],
        embeddings=[[0.1] * 8],
        documents=["Doc 1."],
        metadatas=[None],
    )
    store.upsert(
        name="col2",
        ids=["chunk_0", "chunk_1"],
        embeddings=[[0.1] * 8, [0.2] * 8],
        documents=["Doc 2a.", "Doc 2b."],
        metadatas=[None, None],
    )

    result = health_service.status()

    assert result["status"] == "ok"
    assert len(result["collections"]) == 2
    names = {c["collection_name"] for c in result["collections"]}
    assert names == {"col1", "col2"}
    counts = {c["collection_name"]: c["chunk_count"] for c in result["collections"]}
    assert counts["col1"] == 1
    assert counts["col2"] == 2


def test_healthy_empty_chromadb(chroma_dir, store, health_service):
    """200 with empty ChromaDB — REQ-HST-001 'No collections yet' branch."""
    result = health_service.status()

    assert result["status"] == "ok"
    assert result["model"] == "MiniMax-M2.7-highspeed"
    assert result["embedding_model"] == "text-embedding-3-small"
    assert result["collections"] == []


def test_503_when_store_raises(store, health_service):
    """REQ-HST-002: when store.stats() raises, return 503-ready payload."""
    # Patch stats to raise
    original_stats = store.stats

    def raising_stats():
        raise RuntimeError("ChromaDB directory not found")

    store.stats = raising_stats

    try:
        result = health_service.status()
    finally:
        store.stats = original_stats

    assert "error" in result
    assert result["error"] == "VECTOR_STORE_UNAVAILABLE"
    assert "message" in result


def test_503_when_store_unreachable(health_service):
    """REQ-HST-002: when store.stats() raises, return 503-ready payload."""
    # ChromaDB auto-creates the persist dir, so we cannot rely on a missing dir.
    # Instead, simulate the failure by patching stats() to raise.
    original_stats = health_service._store.stats

    def raising_stats():
        raise RuntimeError("Simulated ChromaDB failure")

    health_service._store.stats = raising_stats
    try:
        result = health_service.status()
    finally:
        health_service._store.stats = original_stats

    assert "error" in result
    assert result["error"] == "VECTOR_STORE_UNAVAILABLE"


def test_no_mutation_on_status_call(chroma_dir, store, health_service):
    """REQ-HST-003: calling status() does not modify ChromaDB."""
    # Establish a known state
    store.upsert(
        name="before",
        ids=["chunk_0"],
        embeddings=[[0.1] * 8],
        documents=["Initial content."],
        metadatas=[None],
    )
    collections_before = set(store.list_collections())

    # Call status() multiple times
    for _ in range(3):
        _ = health_service.status()

    collections_after = set(store.list_collections())
    stats = store.stats()

    assert collections_after == collections_before
    assert len(stats) == len(collections_after)
