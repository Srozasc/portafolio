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
# Chat (Phase 1: HiRag15k baseline)
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """POST /api/chat/stream request body."""

    question: str = Field(..., min_length=1, description="User question (non-empty string).")
    collection: str | None = Field(
        default=None,
        description="Optional explicit collection name.",
    )


# ---------------------------------------------------------------------------
# Chat (Phase 3: projects-aware router)
# ---------------------------------------------------------------------------


class ChatTurn(BaseModel):
    """One turn of a multi-turn conversation."""

    role: Literal["user", "assistant"]
    content: str


class ProjectsChatRequest(BaseModel):
    """POST /api/chat/stream-projects request body."""

    question: str = Field(..., min_length=1, description="User question (non-empty string).")
    lang: Literal["es", "en"] = Field(
        default="es",
        description="Response language (controls the system prompt and the "
        "card summary/title fields used).",
    )
    session_id: str | None = Field(
        default=None,
        description="Optional client-provided session id (for future use).",
    )
    history: list[ChatTurn] = Field(
        default_factory=list,
        description="Optional recent conversation turns (most recent last). "
        "Used for pronoun resolution (e.g. 'el primero').",
    )


class ProjectCard(BaseModel):
    """A single project card emitted alongside the LLM prose."""

    slug: str = Field(..., description="Project slug, e.g. 'proj-data-pipeline'.")
    title: str = Field(..., description="Project title in the request language.")
    summary: str = Field(..., description="One-line project summary.")
    relevance: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Relevance score 0.0-1.0; 1.0 for explicit detail requests.",
    )


class ProjectsChatResponse(BaseModel):
    """Non-streaming convenience response for /api/chat/stream-projects.

    The SSE endpoint streams `content` / `projects` / `done` events instead
    of returning this model directly. This model is exposed for tests and
    future non-streaming clients.
    """

    ok: bool = True
    route_kind: str = Field(..., description="LIST_PROJECTS / DETAIL_PROJECT / GENERAL.")
    slug: str | None = Field(
        default=None, description="Resolved slug for DETAIL_PROJECT routes."
    )
    project_slugs: list[str] = Field(
        default_factory=list,
        description="Slugs of projects emitted in the `projects` event.",
    )


# ---------------------------------------------------------------------------
# SSE StreamEvent (mirrors backend.services.chat_service.StreamEvent)
# ---------------------------------------------------------------------------

# Re-exported here so the route layer imports a stable type from schemas
StreamEvent = dict
"""SSE event payload. Discriminated by the `type` field.

Phase 1 variants:
  - content: {"type": "content", "text": "<token delta>"}
  - done:    {"type": "done"}
  - error:   {"type": "error", "error": "<CODE>", "message": "<human>"}

Phase 3 additions:
  - projects:{"type": "projects", "items": [ProjectCard, ...]}
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


# ---------------------------------------------------------------------------
# Projects reindex
# ---------------------------------------------------------------------------


class ReindexRequest(BaseModel):
    """POST /api/projects/reindex request body."""

    force: bool = Field(
        default=False,
        description="Delete existing collections before upserting. "
        "Use for first run or after a schema change.",
    )
    projects_dir: str | None = Field(
        default=None,
        description="Path to the projects directory. Defaults to "
        "apps/api/data/projects/ when omitted.",
    )


class ReindexResponse(BaseModel):
    """POST /api/projects/reindex success response body."""

    ok: bool = True
    indexed_projects: int = Field(
        ..., description="Number of projects successfully indexed."
    )
    index_chunks: int = Field(
        ...,
        description="Number of chunks in the master `projects_index` collection "
        "(one per project).",
    )
    detail_chunks_total: int = Field(
        ...,
        description="Total number of chunks across all per-project detail collections.",
    )
    duration_ms: int = Field(..., description="Processing time in milliseconds.")
    project_slugs: list[str] = Field(
        default_factory=list,
        description="Slugs of the projects successfully indexed.",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Per-project error messages that did not abort the batch.",
    )
