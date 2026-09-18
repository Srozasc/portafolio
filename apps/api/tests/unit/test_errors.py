"""Unit tests for backend.api.errors.

Verifies that each exception class maps to the correct (HTTP code, error code) pair
and that the envelope shape is {"error", "message"}.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError as PydanticValidationError

from backend.api.errors import (
    APIError,
    envelope,
    json_error,
    register_exception_handlers,
)
from backend.services.ingest_service import (
    IngestValidationError,
    UnsupportedExtensionError,
    FileTooLargeError,
)


class TestEnvelope:
    """Test the envelope helper and shape."""

    def test_envelope_returns_correct_keys(self):
        result = envelope("TEST_CODE", "A test message")
        assert set(result.keys()) == {"error", "message"}
        assert result["error"] == "TEST_CODE"
        assert result["message"] == "A test message"


class TestJSONError:
    """Test json_error helper."""

    def test_json_error_returns_correct_status_and_body(self):
        resp = json_error("TEST_CODE", "A test message", status_code=400)
        assert resp.status_code == 400
        body = resp.body.decode()
        assert '"error":"TEST_CODE"' in body
        assert '"message":"A test message"' in body


class TestAPIError:
    """Test the APIError exception class."""

    def test_api_error_stores_fields(self):
        exc = APIError("SOME_CODE", "Some message", 422)
        assert exc.code == "SOME_CODE"
        assert exc.message == "Some message"
        assert exc.status_code == 422


class TestExceptionHandlerRegistry:
    """Test that exception handlers are registered and produce correct responses."""

    @pytest.fixture
    def app(self) -> FastAPI:
        app = FastAPI()
        register_exception_handlers(app)
        return app

    def test_file_not_found_returns_404_FILE_NOT_FOUND(self, app: FastAPI):
        from fastapi.testclient import TestClient

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/raise-file-not-found")

        # The handler maps FileNotFoundError → 404 FILE_NOT_FOUND
        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "FILE_NOT_FOUND"
        assert "message" in data

    def test_unsupported_extension_returns_415(self, app: FastAPI):
        from fastapi.testclient import TestClient

        # Manually raise to test the handler
        @app.get("/test")
        def route():
            raise UnsupportedExtensionError("Unsupported extension '.txt'")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test")
        assert response.status_code == 415
        data = response.json()
        assert data["error"] == "UNSUPPORTED_EXTENSION"

    def test_file_too_large_returns_413(self, app: FastAPI):
        from fastapi.testclient import TestClient

        @app.get("/test")
        def route():
            raise FileTooLargeError("File too large")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test")
        assert response.status_code == 413
        data = response.json()
        assert data["error"] == "FILE_TOO_LARGE"

    def test_ingest_validation_error_returns_400(self, app: FastAPI):
        from fastapi.testclient import TestClient

        @app.get("/test")
        def route():
            raise IngestValidationError("Invalid collection name")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test")
        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "INVALID_COLLECTION_NAME"

    def test_catch_all_returns_500_internal_error(self, app: FastAPI):
        from fastapi.testclient import TestClient

        @app.get("/test")
        def route():
            raise RuntimeError("Unexpected error")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test")
        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "INTERNAL_ERROR"
        # Message must not leak the exception text
        assert "Unexpected error" not in data["message"]
