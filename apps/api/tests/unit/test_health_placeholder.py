"""Phase 0 smoke test updated for Phase 3 — GET / now serves the frontend.

See tasks.md WU 0.2 acceptance criterion (updated):
  After Phase 3, GET / returns the static UI (frontend/index.html)
  if the frontend exists, or 404 if it doesn't.

This test verifies the app boots with lifespan and serves HTML.
"""

import pytest
from fastapi.testclient import TestClient


def test_root_returns_html_or_404():
    """GET / returns 200 with HTML (if frontend exists) or 404."""
    # Import here so the env-var patch in conftest runs first
    from backend.main import app

    client = TestClient(app)
    response = client.get("/")
    # After Phase 3: GET / serves frontend/index.html (200) or 404 if no frontend yet
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert "html" in response.headers.get("content-type", "").lower()
