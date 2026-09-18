"""POST /api/ingest route.

See design.md Decision 4, Decision 5, spec REQ-ING-001..007 / WU 3.2.

R1-W1 security fix: validates that the resolved absolute path is inside
settings.DATA_DIR and is not a symlink BEFORE the file is read.
MAX_INGEST_BYTES is also enforced at the route layer (per Decision 5).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.errors import json_error
from backend.api.schemas import IngestRequest, IngestResponse
from backend.config import Settings
from backend.services.ingest_service import (
    IngestService,
    UnsupportedExtensionError,
    FileTooLargeError,
)


router = APIRouter(prefix="/api", tags=["ingest"])


def _get_ingest_service() -> IngestService:
    """Resolve IngestService from app.state (injected by main.py lifespan)."""
    from backend.main import app

    return app.state.ingest_service


@router.post("/ingest", response_model=IngestResponse)
async def ingest_file(
    body: IngestRequest,
    service: IngestService = Depends(_get_ingest_service),
    settings: Settings = Depends(lambda: Settings()),
) -> IngestResponse:
    """Ingest a markdown file into ChromaDB.

    Pre-flight checks (before any file I/O or service call):
      1. Resolve the path (relative to CWD or absolute).
      2. Reject symlinks (R1-W1).
      3. Reject paths outside DATA_DIR (R1-W1).
      4. Check file exists → 404 FILE_NOT_FOUND.
      5. Check extension is .md/.markdown → 415 UNSUPPORTED_EXTENSION.
      6. Check file size ≤ MAX_INGEST_BYTES → 413 FILE_TOO_LARGE.

    On success: calls service.ingest_file() and returns 200 with IngestResponse.
    On service exceptions: re-raises so global exception handlers translate them.
    """
    file_path = body.file_path
    collection_override = body.collection

    # --- R1-W1: path sandboxing ---
    try:
        resolved = Path(file_path).resolve()
    except Exception:
        # Could not resolve (e.g. invalid path on Windows)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="FILE_NOT_FOUND: could not resolve file path",
        )

    # Reject symlinks
    if os.path.islink(resolved):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PATH_OUTSIDE_DATA_DIR: symlinks are not allowed",
        )

    # Enforce path is inside DATA_DIR
    data_root = Path(settings.DATA_DIR).resolve()
    try:
        resolved.relative_to(data_root)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PATH_OUTSIDE_DATA_DIR: file path must be inside DATA_DIR",
        )

    # --- Pre-flight validation (mirrors service pre-flight but gives
    #     specific HTTP codes before the service is involved) ---
    if not resolved.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="FILE_NOT_FOUND",
        )

    ext = resolved.suffix.lower()
    if ext not in (".md", ".markdown"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="UNSUPPORTED_EXTENSION",
        )

    file_size = resolved.stat().st_size
    if file_size > settings.MAX_INGEST_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="FILE_TOO_LARGE",
        )

    # --- Delegate to service ---
    result = service.ingest_file(
        file_path=str(resolved),
        collection_override=collection_override,
    )

    return IngestResponse(
        ok=True,
        collection=result.collection,
        chunks_indexed=result.chunks_indexed,
        total_chars=result.total_chars,
        duration_ms=result.duration_ms,
    )
