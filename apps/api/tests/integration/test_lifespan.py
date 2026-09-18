"""Integration tests for main.py lifespan.

Verifies that the FastAPI app's lifespan builds app.state singletons on startup.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from fastapi.testclient import TestClient


def test_lifespan_creates_all_three_services(tmp_path: Path):
    """Verify the lifespan creates ingest_service, chat_service, health_service on app.state."""
    import os
    old_chroma = os.environ.get("CHROMA_PERSIST_DIR")
    os.environ["CHROMA_PERSIST_DIR"] = str(tmp_path)

    try:
        import importlib
        import backend.main
        importlib.reload(backend.main)
        app = backend.main.app

        # TestClient triggers lifespan on __enter__
        with TestClient(app, raise_server_exceptions=False) as client:
            # Starlette State hides attrs from hasattr/dir; check _state directly
            state_keys = list(app.state._state.keys())
            assert "ingest_service" in state_keys, f"ingest_service not in {state_keys}"
            assert "chat_service" in state_keys, f"chat_service not in {state_keys}"
            assert "health_service" in state_keys, f"health_service not in {state_keys}"

            from backend.services.ingest_service import IngestService
            from backend.services.chat_service import ChatService
            from backend.services.health_service import HealthService

            assert isinstance(app.state._state["ingest_service"], IngestService)
            assert isinstance(app.state._state["chat_service"], ChatService)
            assert isinstance(app.state._state["health_service"], HealthService)
    finally:
        if old_chroma:
            os.environ["CHROMA_PERSIST_DIR"] = old_chroma
        else:
            os.environ.pop("CHROMA_PERSIST_DIR", None)


def test_lifespan_wires_similarity_threshold_to_retriever(tmp_path: Path):
    """Verify that the lifespan passes settings.SIMILARITY_THRESHOLD to the Retriever
    constructor, so ChatService's retriever uses the configured threshold.

    Regression guard: if someone removes the threshold=... argument from the
    Retriever() call in main.py lifespan, this test fails.
    """
    import os
    old_chroma = os.environ.get("CHROMA_PERSIST_DIR")
    os.environ["CHROMA_PERSIST_DIR"] = str(tmp_path)

    try:
        import importlib
        import backend.main
        importlib.reload(backend.main)
        app = backend.main.app

        with TestClient(app, raise_server_exceptions=False) as client:
            chat_service = app.state._state["chat_service"]
            assert hasattr(chat_service, "retriever"), (
                f"chat_service has no retriever attribute: {dir(chat_service)}"
            )
            # SIMILARITY_THRESHOLD defaults to 0.75 in conftest setup_test_env
            assert chat_service.retriever.threshold == 0.75, (
                f"Expected retriever.threshold == 0.75, got {chat_service.retriever.threshold}"
            )
    finally:
        if old_chroma:
            os.environ["CHROMA_PERSIST_DIR"] = old_chroma
        else:
            os.environ.pop("CHROMA_PERSIST_DIR", None)


def test_lifespan_shutdown_is_clean(tmp_path: Path):
    """Verify lifespan shutdown does not raise."""
    import os
    old_chroma = os.environ.get("CHROMA_PERSIST_DIR")
    os.environ["CHROMA_PERSIST_DIR"] = str(tmp_path)

    try:
        import importlib
        import backend.main
        importlib.reload(backend.main)
        app = backend.main.app

        with TestClient(app, raise_server_exceptions=False) as client:
            pass  # Triggers lifespan shutdown on context exit
    finally:
        if old_chroma:
            os.environ["CHROMA_PERSIST_DIR"] = old_chroma
        else:
            os.environ.pop("CHROMA_PERSIST_DIR", None)
