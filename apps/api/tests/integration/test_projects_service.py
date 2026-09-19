"""Integration tests for ProjectsService.

Uses REAL ChromaDB in tmp_path with a deterministic mock embedder.
Pattern mirrors tests/integration/test_ingest_service.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.config import Settings
from backend.rag.vector_store import VectorStore
from backend.services.projects_service import ProjectsService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sample_md(
    slug: str,
    body: str = "## Contexto\n\nPárrafo con palabras. " * 40,
) -> str:
    """Return a sample .md text with valid frontmatter."""
    return (
        f"---\n"
        f"slug: {slug}\n"
        f"title_es: {slug}-title-es\n"
        f"title_en: {slug}-title-en\n"
        f"year: 2024\n"
        f"role_es: Lead\n"
        f"role_en: Lead\n"
        f"client: Test Client\n"
        f"tags:\n"
        f"  - python\n"
        f"  - aws\n"
        f"summary_es: \"Resumen {slug}\"\n"
        f"summary_en: \"Summary {slug}\"\n"
        f"---\n\n"
        f"{body}\n"
    )


def _write_md(tmp_path: Path, name: str, content: str) -> Path:
    """Write a .md file under tmp_path/name and return its path."""
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _deterministic_embedder(dim: int = 16) -> MagicMock:
    """Mock embedder that returns [float(i)] * dim for the i-th text."""
    embedder = MagicMock()

    def _embed(texts):
        return [[float(i)] * dim for i, _ in enumerate(texts)]

    embedder.embed.side_effect = _embed
    return embedder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def chroma_dir(tmp_path):
    """ChromaDB persist dir (under tmp_path)."""
    return str(tmp_path / "chroma")


@pytest.fixture
def store(chroma_dir):
    """Real VectorStore backed by chroma_dir."""
    return VectorStore(persist_dir=chroma_dir)


@pytest.fixture
def embedder():
    """Deterministic mock embedder (16-dim)."""
    return _deterministic_embedder(dim=16)


@pytest.fixture
def settings():
    """Default application settings."""
    return Settings()


@pytest.fixture
def seed_projects_dir(tmp_path):
    """5 valid .md files with distinct slugs."""
    for slug in [
        "proj-data-pipeline", "proj-rag-customer", "proj-cloud-migration",
        "proj-ml-scoring", "proj-realtime-fraud",
    ]:
        _write_md(tmp_path, f"{slug}.md", _make_sample_md(slug=slug))
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ingest_5_projects_creates_index_and_details(
    chroma_dir, store, embedder, settings, seed_projects_dir
):
    """Ingest 5 projects: master index has 5 chunks, 5 detail collections exist."""
    service = ProjectsService(embedder=embedder, store=store, settings=settings)
    result = service.ingest_all(seed_projects_dir, force=True)

    # Result summary
    assert result.indexed_projects == 5
    assert result.index_chunks == 5
    assert result.detail_chunks_total > 0
    assert result.errors == []

    # Master index collection exists with 5 chunks
    collections = store.list_collections()
    assert ProjectsService.INDEX_COLLECTION in collections

    # 5 detail collections, one per slug
    expected_details = {
        f"projects_{slug}"
        for slug in [
            "proj-data-pipeline",
            "proj-rag-customer",
            "proj-cloud-migration",
            "proj-ml-scoring",
            "proj-realtime-fraud",
        ]
    }
    assert expected_details.issubset(set(collections))

    # Each detail collection has at least 1 chunk
    for name in expected_details:
        stats = store.stats()
        count_for = next((s.chunk_count for s in stats if s.name == name), 0)
        assert count_for >= 1, f"{name} should have at least 1 chunk"


def test_ingest_idempotent_with_force(
    chroma_dir, store, embedder, settings, seed_projects_dir
):
    """Two consecutive runs with force=True produce the same collection layout."""
    service = ProjectsService(embedder=embedder, store=store, settings=settings)

    # First run
    r1 = service.ingest_all(seed_projects_dir, force=True)
    # Second run
    r2 = service.ingest_all(seed_projects_dir, force=True)

    assert r1.indexed_projects == 5
    assert r2.indexed_projects == 5

    # Master index still has exactly 5 chunks (no duplicates from re-upsert).
    stats = store.stats()
    index_stats = [s for s in stats if s.name == ProjectsService.INDEX_COLLECTION]
    assert len(index_stats) == 1
    assert index_stats[0].chunk_count == 5

    # Each detail collection has a stable, deterministic count
    for slug in [
        "proj-data-pipeline",
        "proj-rag-customer",
        "proj-cloud-migration",
        "proj-ml-scoring",
        "proj-realtime-fraud",
    ]:
        detail_name = f"projects_{slug}"
        detail_stats = [s for s in stats if s.name == detail_name]
        assert len(detail_stats) == 1
        assert detail_stats[0].chunk_count >= 1


def test_ingest_skips_malformed_files(
    chroma_dir, store, embedder, settings, tmp_path
):
    """5 valid + 1 malformed → 5 indexed, errors list has 1 entry."""
    # 5 valid
    for slug in ["proj-a", "proj-b", "proj-c", "proj-d", "proj-e"]:
        _write_md(tmp_path, f"{slug}.md", _make_sample_md(slug=slug))
    # 1 malformed: invalid slug
    _write_md(
        tmp_path,
        "bad.md",
        "---\nslug: BadSlug\ntitle_es: x\ntitle_en: y\n---\n\nBody\n",
    )

    service = ProjectsService(embedder=embedder, store=store, settings=settings)
    result = service.ingest_all(tmp_path, force=True)

    assert result.indexed_projects == 5
    assert result.index_chunks == 5
    assert len(result.errors) == 1
    assert "bad.md" in result.errors[0] or "slug" in result.errors[0].lower()

    # Master index has only the 5 valid projects
    stats = store.stats()
    index_stats = [s for s in stats if s.name == ProjectsService.INDEX_COLLECTION]
    assert index_stats[0].chunk_count == 5


def test_index_metadata_round_trip(
    chroma_dir, store, embedder, settings, seed_projects_dir
):
    """Metadata fields (slug, year, tags-as-JSON) survive the round-trip."""
    service = ProjectsService(embedder=embedder, store=store, settings=settings)
    service.ingest_all(seed_projects_dir, force=True)

    # Query the master index for one of the embedded chunks.
    hits = store.query(
        name=ProjectsService.INDEX_COLLECTION,
        embedding=[0.0] * 16,  # closest to embedding for text 0 (slug='proj-data-pipeline')
        top_k=5,
        threshold=-1.0,  # accept everything
    )
    assert len(hits) == 5

    # Every hit must have slug, year, tags as JSON string, and summary_es/en.
    for hit in hits:
        assert "slug" in hit.metadata
        assert hit.metadata["year"] == 2024
        assert json.loads(hit.metadata["tags"]) == ["python", "aws"]
        assert "summary_es" in hit.metadata
        assert "summary_en" in hit.metadata
        assert hit.metadata["slug"].startswith("proj-")


def test_detail_chunks_have_project_metadata(
    chroma_dir, store, embedder, settings, seed_projects_dir
):
    """Detail-collection chunks carry slug, source, year metadata."""
    service = ProjectsService(embedder=embedder, store=store, settings=settings)
    service.ingest_all(seed_projects_dir, force=True)

    # Use a very negative threshold so all returned hits pass even with our
    # deterministic-but-spread vectors (chunks have embeddings [1.0, 2.0, ...]
    # against a query vector of [0.0]).
    hits = store.query(
        name="projects_proj-data-pipeline",
        embedding=[0.0] * 16,
        top_k=20,
        threshold=-100.0,
    )
    assert len(hits) >= 1

    for hit in hits:
        assert hit.metadata["slug"] == "proj-data-pipeline"
        assert hit.metadata["year"] == 2024
        # source is the absolute path of the .md file
        assert hit.metadata["source"].endswith("proj-data-pipeline.md")
        assert "section_header" in hit.metadata
        assert "chunk_index" in hit.metadata


def test_ingest_against_real_seed_directory(
    chroma_dir, store, embedder, settings
):
    """End-to-end against the seed projects in apps/api/data/projects/."""
    seed_dir = Path(__file__).parent.parent.parent / "data" / "projects"
    if not seed_dir.exists():
        pytest.skip(f"Seed directory not present: {seed_dir}")

    service = ProjectsService(embedder=embedder, store=store, settings=settings)
    result = service.ingest_all(seed_dir, force=True)

    assert result.indexed_projects == 5
    assert result.errors == []
    assert sorted(result.project_slugs) == [
        "proj-cloud-migration",
        "proj-data-pipeline",
        "proj-ml-scoring",
        "proj-rag-customer",
        "proj-realtime-fraud",
    ]

    stats = store.stats()
    assert any(s.name == ProjectsService.INDEX_COLLECTION and s.chunk_count == 5 for s in stats)
    assert any(s.name == "projects_proj-data-pipeline" for s in stats)
    assert any(s.name == "projects_proj-realtime-fraud" for s in stats)
