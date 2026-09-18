"""GET /api/health route.

See design.md spec REQ-HST-001..003 / WU 3.4.
Read-only endpoint; delegates to HealthService.status().
Returns 200 with HealthResponse or 503 with ErrorEnvelope.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.api.errors import json_error
from backend.api.schemas import HealthResponse
from backend.services.health_service import HealthService


router = APIRouter(prefix="/api", tags=["health"])


def _get_health_service() -> HealthService:
    """Resolve HealthService from app.state."""
    from backend.main import app

    return app.state.health_service


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={
        200: {"description": "System operational"},
        503: {"description": "Vector store unavailable"},
    },
)
async def get_health(
    service: HealthService = Depends(_get_health_service),
) -> JSONResponse | HealthResponse:
    """Return system health status.

    200: ChromaDB reachable, returns HealthResponse with collection stats.
    503: ChromaDB unreachable, returns ErrorEnvelope with VECTOR_STORE_UNAVAILABLE.
    """
    payload = service.status()

    if "error" in payload:
        # 503 — HealthService detected ChromaDB unreachable
        return json_error(
            code=payload["error"],
            message=payload["message"],
            status_code=503,
        )

    # 200 — return HealthResponse model
    return HealthResponse(
        status="ok",
        model=payload["model"],
        embedding_model=payload["embedding_model"],
        collections=payload["collections"],
    )
