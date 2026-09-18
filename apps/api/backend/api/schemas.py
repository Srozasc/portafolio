"""Pydantic request/response models and SSE event types.

See design.md Decision 8 / Module APIs / WU 3.1.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    """POST /api/ingest request body."""

    file_path: str = Field(..., description="Path to the markdown file to ingest.")
    collection: str | None = Field(
        default=None,
        description="Optional explicit collection name. "
        "If omitted, derived from the file stem.",
    )


class IngestResponse(BaseModel):
    """POST /api/ingest success response body."""

    ok: bool = True
    collection: str = Field(..., description="ChromaDB collection name used.")
    chunks_indexed: int = Field(..., description="Number of chunks written.")
    total_chars: int = Field(..., description="Total characters in the source file.")
    duration_ms: int = Field(..., description="Processing time in milliseconds.")


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """POST /api/chat/stream request body."""

    question: str = Field(..., min_length=1, description="User question (non-empty string).")
    collection: str | None = Field(
        default=None,
        description="Optional explicit collection name.",
    )


# ---------------------------------------------------------------------------
# SSE StreamEvent (mirrors backend.services.chat_service.StreamEvent)
# ---------------------------------------------------------------------------

# Re-exported here so the route layer imports a stable type from schemas
StreamEvent = dict
"""SSE event payload. Three variants discriminated by the `type` field:

  - content: {"type": "content", "text": "<token delta>"}
  - done:    {"type": "done"}
  - error:   {"type": "error", "error": "<CODE>", "message": "<human>"}
"""


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class CollectionStatOut(BaseModel):
    """Single collection stat in GET /api/health response."""

    collection_name: str
    chunk_count: int


class HealthResponse(BaseModel):
    """GET /api/health success response body."""

    status: Literal["ok"] = "ok"
    model: str = Field(..., description="Configured chat model name.")
    embedding_model: str = Field(..., description="Configured embedding model name.")
    collections: list[CollectionStatOut] = Field(
        default_factory=list,
        description="Per-collection chunk counts.",
    )


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------


class ErrorEnvelope(BaseModel):
    """Canonical error response envelope. Used for all HTTP error responses."""

    error: str = Field(..., description="Machine-readable error code.")
    message: str = Field(..., description="Human-readable error description.")
