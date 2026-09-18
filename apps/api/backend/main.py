"""FastAPI application with lifespan wiring.

See design.md Module Layout, Decision 8, WU 3.4.

Lifespan:
  1. On startup: open ChromaDB, build singletons (VectorStore, Embedder,
     Retriever, LLMClient, IngestService, ChatService, HealthService),
     attach to app.state.
  2. On shutdown: ChromaDB PersistentClient has no explicit close() in 0.6.x;
     we call what we can (noop for now).

Routes mounted:
  - /api/ingest  (POST)
  - /api/chat/stream  (POST)
  - /api/health  (GET)

Static UI:
  - / → frontend/index.html (FastAPI StaticFiles with html=True)

CORS:
  - allow_origins from settings.CORS_ALLOW_ORIGINS.split(",")
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import Settings
from backend.api.errors import register_exception_handlers
from backend.api.routes.ingest import router as ingest_router
from backend.api.routes.chat import router as chat_router
from backend.api.routes.health import router as health_router
from backend.api.routes.debug import router as debug_router
from backend.rag.vector_store import VectorStore
from backend.rag.embedder import Embedder
from backend.rag.retriever import Retriever
from backend.rag.llm_client import LLMClient
from backend.rag.chunker import chunk_markdown
from backend.services.ingest_service import IngestService
from backend.services.chat_service import ChatService
from backend.services.health_service import HealthService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: open ChromaDB on startup, no-op on shutdown."""
    settings = Settings()

    # Build singletons
    store = VectorStore(persist_dir=settings.CHROMA_PERSIST_DIR)
    embedder = Embedder(
        base_url=settings.embedding_base_urlEffective,
        api_key=settings.embedding_api_keyEffective,
        model=settings.EMBEDDING_MODEL,
    )
    retriever = Retriever(
        store=store,
        embedder=embedder,
        threshold=settings.SIMILARITY_THRESHOLD,
    )
    llm_client = LLMClient(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        model=settings.CHAT_MODEL,
    )

    ingest_service = IngestService(
        chunker=chunk_markdown,
        embedder=embedder,
        store=store,
        settings=settings,
    )
    chat_service = ChatService(retriever=retriever, llm=llm_client)
    health_service = HealthService(
        store=store,
        chat_model=settings.CHAT_MODEL,
        embedding_model=settings.EMBEDDING_MODEL,
    )

    # Attach to app.state for route access
    app.state.ingest_service = ingest_service
    app.state.chat_service = chat_service
    app.state.health_service = health_service

    yield

    # Shutdown: ChromaDB 0.6.x PersistentClient has no explicit close()
    # The client will flush on interpreter exit.
    # If ChromaDB adds a close() in future versions, call it here.


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HiRag15k",
    lifespan=lifespan,
)

# CORS — added at module level because Starlette forbids add_middleware after
# startup. The Settings() here is evaluated at import time; tests that need
# to override CORS origins can patch the env var before importing backend.main
# (the conftest.py session fixture already does this for LLM_BASE_URL, etc.).
settings = Settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register error handlers
register_exception_handlers(app)

# Mount routes
app.include_router(ingest_router)
app.include_router(chat_router)
app.include_router(health_router)
app.include_router(debug_router)

# Mount static UI (serves frontend/index.html at /)
# Narrow except: only file-system errors are expected (frontend/ may not exist
# yet on a fresh checkout). Other errors should propagate so boot problems
# are visible.
import logging

_logger = logging.getLogger(__name__)
try:
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
except (FileNotFoundError, OSError, RuntimeError) as exc:
    # frontend/ directory may not exist yet (Phase 4 creates it)
    _logger.warning("Static UI mount skipped: %s", exc)
