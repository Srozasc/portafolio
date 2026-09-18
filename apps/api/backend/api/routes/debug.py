"""Debug diagnostic endpoint for retriever inspection.

Adds POST /api/_debug/retrieve which returns raw retriever hits
(with scores, text, metadata, snippet) bypassing the threshold filter.
Adds POST /api/_debug/prompt which returns the system prompt that
would be sent to the LLM, given a question and the configured
threshold + top_k. Intended for manual walkthrough diagnosis only;
not part of the production chat flow.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, status


from backend.services.chat_service import ChatService
from backend.rag.prompts import build_chat_system_prompt
from backend.config import get_settings


router = APIRouter(prefix="/api", tags=["debug"])


class DebugRetrieveRequest(BaseModel):
    """POST /api/_debug/retrieve request body."""

    question: str = Field(..., min_length=1, description="User question string.")
    collection: str | None = Field(
        default=None,
        description="Optional explicit collection name. "
        "If omitted and exactly one collection exists, it is used automatically.",
    )
    top_k: int = Field(default=10, ge=1, le=100, description="Maximum hits to return.")


class DebugHit(BaseModel):
    """A single retriever hit with score and snippet."""

    score: float
    text: str
    metadata: dict
    snippet: str


class DebugRetrieveResponse(BaseModel):
    """POST /api/_debug/retrieve success response body."""

    question: str
    resolved_collection: str | None
    hits: list[DebugHit]


def _get_chat_service() -> ChatService:
    """Resolve ChatService from app.state.

    Production: set by main.py lifespan.
    Tests: overridden via app.dependency_overrides[_get_chat_service].
    """
    from backend.main import app

    return app.state.chat_service


def _resolve_collection(service: ChatService, collection: str | None) -> tuple[str, bool, str | None]:
    """Resolve collection name for the debug endpoint.

    Mirrors ChatService._resolve_collection but returns a tuple
    suitable for HTTP error responses.

    Returns:
        (resolved_name, ok, error_code_or_none)
    """
    store = service.retriever._store  # noqa: SLF001

    try:
        existing = store.list_collections()
    except Exception:
        return ("", False, "VECTOR_STORE_ERROR")

    if collection is not None:
        if collection not in existing:
            return ("", False, "UNKNOWN_COLLECTION")
        return (collection, True, None)

    if len(existing) == 0:
        return ("", False, "UNKNOWN_COLLECTION")
    if len(existing) > 1:
        return ("", False, "AMBIGUOUS_COLLECTION")
    return (existing[0], True, None)


@router.post("/_debug/retrieve", response_model=DebugRetrieveResponse)
async def debug_retrieve(
    body: DebugRetrieveRequest,
    service: ChatService = Depends(_get_chat_service),
) -> DebugRetrieveResponse:
    """Return raw retriever hits for a question with threshold=0.0.

    This endpoint is intended for manual diagnosis during AC-4 walkthrough.
    It does NOT modify the production /api/chat/stream flow.

    The response includes all hits with their similarity scores, full text,
    metadata, and a 200-char snippet for readability — regardless of the
    configured threshold (0.75 in MVP).
    """
    resolved, ok, error_code = _resolve_collection(service, body.collection)

    if not ok:
        status_map = {
            "UNKNOWN_COLLECTION": (status.HTTP_404_NOT_FOUND, "UNKNOWN_COLLECTION"),
            "AMBIGUOUS_COLLECTION": (status.HTTP_400_BAD_REQUEST, "AMBIGUOUS_COLLECTION"),
            "VECTOR_STORE_ERROR": (status.HTTP_503_SERVICE_UNAVAILABLE, "VECTOR_STORE_ERROR"),
        }
        http_status, code = status_map.get(error_code, (status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR"))
        raise HTTPException(
            status_code=http_status,
            detail=f"{code}: {code}",
        )

    hits = service.retriever.retrieve(
        question=body.question,
        collection=resolved,
        top_k=body.top_k,
        threshold=0.0,  # bypass threshold — return all candidates
    )

    debug_hits = [
        DebugHit(
            score=h.score,
            text=h.text,
            metadata=h.metadata,
            snippet=h.text[:200],
        )
        for h in hits
    ]

    return DebugRetrieveResponse(
        question=body.question,
        resolved_collection=resolved,
        hits=debug_hits,
    )


@router.post("/_debug/prompt")
async def debug_prompt(
    body: DebugRetrieveRequest,
    service: ChatService = Depends(_get_chat_service),
) -> dict:
    """Return the system prompt that WOULD be sent to the LLM for `body.question`.

    Uses the production threshold and top_k from Settings.
    Calls retriever.retrieve with the configured threshold (NOT 0.0).
    If no hits pass, returns the system prompt with the deflection
    chunk_block so we can see what the LLM sees in the deflection path.
    """
    resolved, ok, error_code = _resolve_collection(service, body.collection)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{error_code}: {error_code}",
        )

    settings = get_settings()
    top_k = body.top_k
    threshold = settings.SIMILARITY_THRESHOLD

    hits = service.retriever.retrieve(
        question=body.question,
        collection=resolved,
        top_k=top_k,
        threshold=threshold,
    )

    from backend.services.chat_service import _ChunkFromHit
    chunks_for_prompt = [
        _ChunkFromHit(
            section_header=h.metadata.get("section_header", ""),
            text=h.text,
        )
        for h in hits
    ]
    system_prompt = build_chat_system_prompt(chunks_for_prompt)

    return {
        "question": body.question,
        "resolved_collection": resolved,
        "configured_threshold": threshold,
        "configured_top_k": top_k,
        "hits_returned": len(hits),
        "hits": [
            {
                "score": h.score,
                "chunk_index": h.metadata.get("chunk_index"),
                "section_header": h.metadata.get("section_header"),
                "snippet": h.text[:200],
            }
            for h in hits
        ],
        "system_prompt": system_prompt,
        "system_prompt_length": len(system_prompt),
    }
