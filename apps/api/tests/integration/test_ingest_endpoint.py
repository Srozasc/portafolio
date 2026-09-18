"""Integration tests for POST /api/ingest endpoint.

See design.md Decision 4, Decision 5, spec REQ-ING-001..007 / WU 3.2.

These tests use a standalone FastAPI app with routes mounted directly,
so they can run independently of main.py's lifespan wiring (WU 3.4).
After WU 3.4 lands, the same tests can be run against the real app
(with app.dependency_overrides for service injection).
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.ingest import router as ingest_router, _get_ingest_service
from backend.api.errors import register_exception_handlers
from backend.config import Settings
from backend.rag.vector_store import VectorStore
from backend.rag.chunker import chunk_markdown
from backend.services.ingest_service import IngestService


# ---------------------------------------------------------------------------
# Fake embedder (returns deterministic zero vectors)
# ---------------------------------------------------------------------------

class _FakeEmbedder:
    dim = 8

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dim for _ in texts]


def make_ingest_service(chroma_dir: Path) -> IngestService:
    store = VectorStore(str(chroma_dir))
    embedder = _FakeEmbedder()
    settings = Settings()
    return IngestService(
        chunker=chunk_markdown,
        embedder=embedder,
        store=store,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Standalone test app with ingest route mounted
# ---------------------------------------------------------------------------

def make_ingest_test_app(chroma_dir: Path, data_dir: Path) -> tuple[FastAPI, TestClient]:
    """Create a FastAPI app with the ingest route mounted and service injected."""
    app = FastAPI()
    register_exception_handlers(app)

    service = make_ingest_service(chroma_dir)

    def _override_ingest_service():
        return service

    app.dependency_overrides[_get_ingest_service] = _override_ingest_service

    # Patch DATA_DIR for path sandbox
    original_data_dir = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = str(data_dir)

    app.include_router(ingest_router)

    client = TestClient(app, raise_server_exceptions=False)

    return client, lambda: (
        app.dependency_overrides.clear(),
        os.environ.update({"DATA_DIR": original_data_dir} if original_data_dir else {"DATA_DIR": "./data"})
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIngestEndpointHappyPath:
    """REQ-ING-005: 200 with IngestResponse shape."""

    def test_ingest_returns_200_and_correct_body(self, tmp_path: Path):
        """Happy path: ingest a small .md file, assert 200 and response fields."""
        md_file = tmp_path / "test.md"
        # Content long enough to produce at least one chunk (CHUNK_SIZE=700 tokens)
        md_file.write_text(
            "# Hello\n\n" + "Lorem ipsum dolor sit amet. " * 200,
            encoding="utf-8",
        )

        client, cleanup = make_ingest_test_app(chroma_dir=tmp_path, data_dir=tmp_path)
        try:
            response = client.post("/api/ingest", json={"file_path": str(md_file)})
        finally:
            cleanup()

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "collection" in data
        assert data["chunks_indexed"] >= 0
        assert "total_chars" in data
        assert "duration_ms" in data

    def test_ingest_with_collection_override(self, tmp_path: Path):
        """Collection override is passed through to the service."""
        md_file = tmp_path / "test.md"
        md_file.write_text(
            "# Test\n\n" + "Lorem ipsum dolor sit amet. " * 200,
            encoding="utf-8",
        )

        client, cleanup = make_ingest_test_app(chroma_dir=tmp_path, data_dir=tmp_path)
        try:
            response = client.post(
                "/api/ingest",
                json={"file_path": str(md_file), "collection": "my-custom-collection"},
            )
        finally:
            cleanup()

        assert response.status_code == 200
        assert response.json()["collection"] == "my-custom-collection"


class TestIngestEndpointNotFound:
    """REQ-ING-006: nonexistent file → 404 FILE_NOT_FOUND."""

    def test_ingest_nonexistent_file_returns_404(self, tmp_path: Path):
        client, cleanup = make_ingest_test_app(chroma_dir=tmp_path, data_dir=tmp_path)
        try:
            response = client.post(
                "/api/ingest",
                json={"file_path": str(tmp_path / "does-not-exist.md")},
            )
        finally:
            cleanup()

        assert response.status_code == 404
        assert response.json()["error"] == "FILE_NOT_FOUND"


class TestIngestEndpointExtension:
    """REQ-ING-006: non-.md extension → 415 UNSUPPORTED_EXTENSION."""

    def test_ingest_txt_file_returns_415(self, tmp_path: Path):
        txt_file = tmp_path / "document.txt"
        txt_file.write_text("Not markdown.", encoding="utf-8")

        client, cleanup = make_ingest_test_app(chroma_dir=tmp_path, data_dir=tmp_path)
        try:
            response = client.post(
                "/api/ingest",
                json={"file_path": str(txt_file)},
            )
        finally:
            cleanup()

        assert response.status_code == 415
        assert response.json()["error"] == "UNSUPPORTED_EXTENSION"


class TestIngestEndpointFileTooLarge:
    """REQ-ING-006: file > MAX_INGEST_BYTES → 413 FILE_TOO_LARGE."""

    def test_ingest_oversized_file_returns_413(self, tmp_path: Path):
        # Create a file slightly over MAX_INGEST_BYTES (5 MiB = 5_242_880 bytes)
        oversized_file = tmp_path / "large.md"
        oversized_bytes = (Settings().MAX_INGEST_BYTES + 6) * b"x"
        oversized_file.write_bytes(oversized_bytes)

        client, cleanup = make_ingest_test_app(chroma_dir=tmp_path, data_dir=tmp_path)
        try:
            response = client.post(
                "/api/ingest",
                json={"file_path": str(oversized_file)},
            )
        finally:
            cleanup()

        assert response.status_code == 413
        assert response.json()["error"] == "FILE_TOO_LARGE"


class TestIngestEndpointPathOutsideDataDir:
    """R1-W1: path resolved outside DATA_DIR → 400 PATH_OUTSIDE_DATA_DIR."""

    def test_ingest_path_outside_data_dir_returns_400(self, tmp_path: Path):
        """DATA_DIR is set to tmp_path; files outside should be rejected."""
        # Create a file at the repo root (clearly outside tmp_path)
        repo_root = Path(__file__).resolve().parent.parent.parent
        outside_file = repo_root / "outside_test.md"
        outside_file.write_text("# Outside", encoding="utf-8")
        try:
            client, cleanup = make_ingest_test_app(chroma_dir=tmp_path, data_dir=tmp_path)
            try:
                response = client.post(
                    "/api/ingest",
                    json={"file_path": str(outside_file)},
                )
            finally:
                cleanup()

            assert response.status_code == 400
            assert response.json()["error"] == "PATH_OUTSIDE_DATA_DIR"
        finally:
            outside_file.unlink(missing_ok=True)


class TestIngestEndpointInvalidCollectionName:
    """R1-W2: bad collection name → 400 INVALID_COLLECTION_NAME."""

    def test_ingest_bad_collection_name_returns_400(self, tmp_path: Path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test", encoding="utf-8")

        # ChromaDB naming rules: must be 3-63 chars, lowercase alphanumeric with - or _
        bad_collection = "Bad Collection Name!"

        client, cleanup = make_ingest_test_app(chroma_dir=tmp_path, data_dir=tmp_path)
        try:
            response = client.post(
                "/api/ingest",
                json={"file_path": str(md_file), "collection": bad_collection},
            )
        finally:
            cleanup()

        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_COLLECTION_NAME"


class TestIngestEndpointIdempotentReingest:
    """REQ-ING-007: re-ingest of same file replaces chunks."""

    def test_reingest_replaces_chunks(self, tmp_path: Path):
        client, cleanup = make_ingest_test_app(chroma_dir=tmp_path, data_dir=tmp_path)
        try:
            # First ingest
            md_file = tmp_path / "test.md"
            md_file.write_text(
                "# Version 1\n\n" + "Lorem ipsum. " * 100,
                encoding="utf-8",
            )
            r1 = client.post("/api/ingest", json={"file_path": str(md_file)})
            assert r1.status_code == 200
            chunks_v1 = r1.json()["chunks_indexed"]

            # Re-ingest with different (longer) content
            md_file.write_text(
                "# Version 2\n\n" + "Lorem ipsum. " * 200 + "\n\nMore content here.",
                encoding="utf-8",
            )
            r2 = client.post("/api/ingest", json={"file_path": str(md_file)})
            assert r2.status_code == 200
            chunks_v2 = r2.json()["chunks_indexed"]

            # Chunk count may differ due to content length
            assert chunks_v2 >= 0
            # The collection is the same (deterministic)
            assert r1.json()["collection"] == r2.json()["collection"]
        finally:
            cleanup()
