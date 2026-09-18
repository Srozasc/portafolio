"""POST /api/chat/stream SSE route.

See design.md Decision 3, spec REQ-CHS-001..007 / WU 3.3.

Pre-stream validation:
  - 400 INVALID_BODY: malformed JSON
  - 400 MISSING_QUESTION: question missing/empty/non-string
  - 404 UNKNOWN_COLLECTION: explicit collection not in ChromaDB
  - 400 AMBIGUOUS_COLLECTION: no override and multiple collections exist

On success: StreamingResponse yielding SSE-formatted data: lines per Decision 3.
Mid-stream errors from service.stream_answer() are surfaced as SSE error events
(no HTTPException raised after headers sent — per Engram #19).
"""

from __future__ import annotations

import json
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from backend.api.errors import json_error
from backend.api.schemas import ChatRequest
from backend.services.chat_service import ChatService


router = APIRouter(prefix="/api", tags=["chat"])


def _get_chat_service() -> ChatService:
    """Resolve ChatService from app.state.

    Production: set by main.py lifespan.
    Tests: overridden via app.dependency_overrides[_get_chat_service].
    """
    from backend.main import app

    return app.state.chat_service


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    service: ChatService = Depends(_get_chat_service),
) -> StreamingResponse:
    """Stream a chat response via SSE.

    Pre-stream validation:
      1. Body parse → 400 INVALID_BODY (via RequestValidationError handler).
      2. question non-empty → 400 MISSING_QUESTION (via RequestValidationError).
      3. Collection resolution delegated to service (it handles the 0/1/>1
         collections cases and returns error events if needed).

    On success: opens StreamingResponse with an async generator that yields
    SSE-formatted data: lines. The generator calls service.stream_answer()
    and yields each StreamEvent as a JSON string prefixed with "data: ".

    The sentinel done event is always written last (per Decision 3).
    """
    # NOTE: body parsing and question validation are handled by FastAPI's
    # RequestValidationError before this function body runs.
    # ChatRequest.question is declared as str (non-empty via min_length=1).

    collection: str | None = body.collection

    def sse_generator() -> Iterator[str]:
        # NOTE: no async here — service.stream_answer() is sync but may be
        # called from async context. It yields StreamEvent dicts; we
        # serialise each to a "data: <json>\n\n" line.
        try:
            for event in service.stream_answer(
                question=body.question,
                collection=collection,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception:
            # This should never happen: stream_answer() catches all StreamError
            # and yields error+done; it never re-raises.
            # But if it does somehow, yield an emergency done sentinel.
            yield f"data: {json.dumps({'type': 'error', 'error': 'INTERNAL_ERROR', 'message': 'Internal error'})}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"

    response = StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
    )
    # Proxy-friendly SSE headers (the moment you front the app with nginx or
    # any buffering proxy, these become necessary; harmless without one).
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response
