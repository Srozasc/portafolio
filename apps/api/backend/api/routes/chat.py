"""Chat SSE routes.

  - POST /api/chat/stream         — Phase 1 HiRag15k baseline (single-collection)
  - POST /api/chat/stream-projects — Phase 3 project-aware router

See design.md Decision 3 (Phase 1) and Phase 3 design (project router).

Pre-stream validation for both routes:
  - 400 INVALID_BODY: malformed JSON
  - 400 MISSING_QUESTION: question missing/empty/non-string

On success: StreamingResponse yielding SSE-formatted data: lines.
Mid-stream errors from the service are surfaced as SSE error events
(no HTTPException raised after headers sent — per Engram #19).
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.api.schemas import ChatRequest, ProjectsChatRequest
from backend.services.chat_service import ChatService


router = APIRouter(prefix="/api", tags=["chat"])


def _get_chat_service() -> ChatService:
    """Resolve ChatService from app.state.

    Production: set by main.py lifespan.
    Tests: overridden via app.dependency_overrides[_get_chat_service].
    """
    from backend.main import app

    return app.state.chat_service


# ---------------------------------------------------------------------------
# Phase 1: HiRag15k baseline (single-collection)
# ---------------------------------------------------------------------------


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    service: ChatService = Depends(_get_chat_service),
) -> StreamingResponse:
    """Stream a chat response via SSE (legacy single-collection mode)."""
    collection: str | None = body.collection

    def sse_generator() -> Iterator[str]:
        try:
            for event in service.stream_answer(
                question=body.question,
                collection=collection,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception:
            # Defensive fallback — should never be reached.
            yield f"data: {json.dumps({'type': 'error', 'error': 'INTERNAL_ERROR', 'message': 'Internal error'})}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"

    response = StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


# ---------------------------------------------------------------------------
# Phase 3: project-aware router
# ---------------------------------------------------------------------------


@router.post("/chat/stream-projects")
async def chat_stream_projects(
    body: ProjectsChatRequest,
    service: ChatService = Depends(_get_chat_service),
) -> StreamingResponse:
    """Stream a project-aware chat response via SSE.

    Routes the user's question via ProjectRouter (LIST / DETAIL / GENERAL),
    queries the appropriate ChromaDB collection (`projects_index` for
    LIST/GENERAL, `projects_<slug>` for DETAIL), and streams an answer
    with up to three SSE event types:

      - ``content``: incremental LLM prose tokens (think-block stripped)
      - ``projects``: a list of project cards emitted at the end of the stream
      - ``done``:    stream-completion sentinel
      - ``error``:   sanitised error code + message (mid-stream failures)

    The events are emitted in this order: content (×N), then projects
    (×0..1), then done.
    """
    history = [turn.model_dump() for turn in body.history]

    def sse_generator() -> Iterator[str]:
        try:
            for event in service.chat_projects_stream(
                question=body.question,
                lang=body.lang,
                history=history,
                session_id=body.session_id,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception:
            # Defensive fallback — the service catches StreamError and
            # surfaces it as an SSE event. Anything else reaching here
            # is a real bug; emit an emergency done.
            yield f"data: {json.dumps({'type': 'error', 'error': 'INTERNAL_ERROR', 'message': 'Internal error'})}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"

    response = StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response
