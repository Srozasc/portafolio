"""POST /api/projects/reindex — Re-ingest all project .md files into ChromaDB.

Phase 2 route. NOT wired into main.py (Phase 3+ will include this router).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from backend.api.schemas import ReindexRequest, ReindexResponse
from backend.config import Settings
from backend.rag.embedder import Embedder
from backend.rag.vector_store import VectorStore
from backend.services.projects_service import ProjectsService


router = APIRouter(prefix="/api/projects", tags=["projects"])


def get_projects_service() -> ProjectsService:
    """Build ProjectsService with default deps (Settings, Embedder, VectorStore).

    This is a self-contained factory so the route can be exercised in tests
    via ``app.dependency_overrides[get_projects_service] = ...`` without
    going through the main.py lifespan.
    """
    settings = Settings()
    store = VectorStore(settings.CHROMA_PERSIST_DIR)
    embedder = Embedder(
        base_url=settings.embedding_base_urlEffective,
        api_key=settings.embedding_api_keyEffective,
        model=settings.EMBEDDING_MODEL,
    )
    return ProjectsService(embedder=embedder, store=store, settings=settings)


@router.post("/reindex", response_model=ReindexResponse)
def reindex_projects(
    request: ReindexRequest,
    service: ProjectsService = Depends(get_projects_service),
) -> ReindexResponse:
    """Trigger a full reindex of project .md files into ChromaDB.

    Args:
        request: ReindexRequest with optional `force` flag and `projects_dir` override.
        service: ProjectsService (injected via Depends).

    Returns:
        ReindexResponse with summary and any per-project errors.
    """
    if request.projects_dir:
        projects_dir = Path(request.projects_dir)
    else:
        projects_dir = Path(__file__).parent.parent.parent.parent / "data" / "projects"

    result = service.ingest_all(projects_dir, force=request.force)

    return ReindexResponse(
        ok=True,
        indexed_projects=result.indexed_projects,
        index_chunks=result.index_chunks,
        detail_chunks_total=result.detail_chunks_total,
        duration_ms=result.duration_ms,
        project_slugs=result.project_slugs,
        errors=result.errors,
    )
