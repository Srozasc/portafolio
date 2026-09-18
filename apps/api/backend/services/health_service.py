"""Health service: read-only ChromaDB stats for /api/health.

Design: design.md Module APIs / WU 2.3 / REQ-HST-001/002/003.
Returns 200-ready dict or 503-ready dict (route decides HTTP status).
No mutations (REQ-HST-003).
"""

from __future__ import annotations

from backend.rag.vector_store import VectorStore


# ---------------------------------------------------------------------------
# 503 payload keys (route checks for "error" key to decide HTTP status)
# ---------------------------------------------------------------------------

_ERROR_PAYLOAD = {
    "error": "VECTOR_STORE_UNAVAILABLE",
    "message": "ChromaDB directory not found or unreadable",
}


class HealthService:
    """Read-only health check backed by ChromaDB VectorStore stats."""

    def __init__(
        self,
        store: VectorStore,
        chat_model: str,
        embedding_model: str,
    ) -> None:
        """Initialise the health service.

        Args:
            store: VectorStore instance for ChromaDB stats.
            chat_model: Configured chat model name (e.g. "MiniMax-M2.7-highspeed").
            embedding_model: Configured embedding model name (e.g. "text-embedding-3-small").
        """
        self._store = store
        self._chat_model = chat_model
        self._embedding_model = embedding_model

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    def status(self) -> dict:
        """Return health status dict.

        Returns:
            - 200 body: {"status": "ok", "model": ..., "embedding_model": ...,
                          "collections": [{"collection_name": c.name,
                                           "chunk_count": c.chunk_count}, ...]}
            - 503 body: {"error": "VECTOR_STORE_UNAVAILABLE",
                         "message": "ChromaDB directory not found or unreadable"}

        No mutations occur on either path (REQ-HST-003).
        """
        try:
            stats = self._store.stats()
        except Exception:
            # ChromaDB unreachable — return 503-ready payload
            return _ERROR_PAYLOAD

        return {
            "status": "ok",
            "model": self._chat_model,
            "embedding_model": self._embedding_model,
            "collections": [
                {"collection_name": s.name, "chunk_count": s.chunk_count}
                for s in stats
            ],
        }
