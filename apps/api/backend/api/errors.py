"""Canonical error codes and JSON error helpers.

See design.md Decision 4 and Decision 10 / WU 3.1.

Error codes (machine-readable, stable):
  400 INVALID_BODY             — malformed JSON body
  400 MISSING_QUESTION         — question missing / empty / wrong type
  400 AMBIGUOUS_COLLECTION     — collection omitted, multiple exist
  400 PATH_OUTSIDE_DATA_DIR    — resolved path not inside DATA_DIR (R1-W1)
  400 INVALID_COLLECTION_NAME  — collection name fails ChromaDB naming rules
  404 UNKNOWN_COLLECTION       — explicit collection not found in ChromaDB
  404 FILE_NOT_FOUND           — file_path does not resolve
  413 FILE_TOO_LARGE           — file size > MAX_INGEST_BYTES
  415 UNSUPPORTED_EXTENSION    — extension not .md or .markdown
  503 VECTOR_STORE_UNAVAILABLE — ChromaDB unreachable
  500 INTERNAL_ERROR           — unhandled exception
  500 INGEST_FAILED            — unhandled exception during ingest pipeline
  SSE  LLM_ERROR               — mid-stream LLM failure (surfaced via SSE event)
  SSE  VECTOR_STORE_ERROR      — mid-stream ChromaDB failure (rare)
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.services.ingest_service import (
    IngestValidationError,
    UnsupportedExtensionError,
    FileTooLargeError,
)


# ---------------------------------------------------------------------------
# APIError and helper
# ---------------------------------------------------------------------------


class APIError(Exception):
    """Holds a canonical error code + human message + HTTP status code."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def envelope(code: str, message: str) -> dict:
    """Return the canonical error envelope dict."""
    return {"error": code, "message": message}


def json_error(code: str, message: str, status_code: int) -> JSONResponse:
    """Build a JSONResponse with the canonical error envelope."""
    return JSONResponse(envelope(code, message), status_code=status_code)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic RequestValidationError → 400 INVALID_BODY or MISSING_QUESTION."""
    errors = exc.errors()
    first_error = errors[0] if errors else {}
    field_path = ".".join(str(loc) for loc in (first_error.get("loc") or []))
    msg = first_error.get("msg", "Validation error")
    input_value = first_error.get("input")

    # Distinguish MISSING_QUESTION (question field is empty/missing)
    # from generic INVALID_BODY (malformed JSON or wrong types)
    code = "INVALID_BODY"
    if field_path == "question" or "question" in field_path:
        if "missing" in msg.lower() or "field required" in msg.lower():
            code = "MISSING_QUESTION"
        elif isinstance(input_value, str) and input_value == "":
            code = "MISSING_QUESTION"
        elif "min_length" in msg or "less than" in msg.lower():
            code = "MISSING_QUESTION"

    return json_error(
        code=code,
        message=f"Validation error at '{field_path}': {msg}" if field_path else msg,
        status_code=400,
    )


async def _file_not_found_handler(
    request: Request, exc: FileNotFoundError
) -> JSONResponse:
    """Handle FileNotFoundError → 404 FILE_NOT_FOUND."""
    return json_error(
        code="FILE_NOT_FOUND",
        message=f"File not found: {exc}",
        status_code=404,
    )


async def _unsupported_extension_handler(
    request: Request, exc: UnsupportedExtensionError
) -> JSONResponse:
    """Handle UnsupportedExtensionError → 415 UNSUPPORTED_EXTENSION."""
    return json_error(
        code="UNSUPPORTED_EXTENSION",
        message=str(exc),
        status_code=415,
    )


async def _file_too_large_handler(
    request: Request, exc: FileTooLargeError
) -> JSONResponse:
    """Handle FileTooLargeError → 413 FILE_TOO_LARGE."""
    return json_error(
        code="FILE_TOO_LARGE",
        message=str(exc),
        status_code=413,
    )


async def _ingest_validation_handler(
    request: Request, exc: IngestValidationError
) -> JSONResponse:
    """Handle IngestValidationError → 400 INVALID_COLLECTION_NAME."""
    return json_error(
        code="INVALID_COLLECTION_NAME",
        message=str(exc),
        status_code=400,
    )


async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Handle StarletteHTTPException (used for pre-stream 4xx from routes)."""
    # Map to our canonical codes where possible
    code_map = {
        400: "INVALID_BODY",
        404: "FILE_NOT_FOUND",
        413: "FILE_TOO_LARGE",
        415: "UNSUPPORTED_EXTENSION",
    }
    code = code_map.get(exc.status_code, "INTERNAL_ERROR")
    return json_error(code=code, message=exc.detail, status_code=exc.status_code)


async def _fastapi_http_exception_handler(
    request: Request, exc
) -> JSONResponse:
    """Handle FastAPI HTTPException (raised by routes using `raise HTTPException`)."""
    detail = getattr(exc, "detail", str(exc))

    # Routes use "CODE: message" format; parse the code from detail
    code: str | None = None
    if isinstance(detail, str):
        known_codes = (
            "PATH_OUTSIDE_DATA_DIR",
            "FILE_NOT_FOUND",
            "UNSUPPORTED_EXTENSION",
            "FILE_TOO_LARGE",
            "MISSING_QUESTION",
            "AMBIGUOUS_COLLECTION",
            "UNKNOWN_COLLECTION",
            "INVALID_BODY",
        )
        for known in known_codes:
            if detail.startswith(known):
                code = known
                break

    # Fall back to status code mapping
    if code is None:
        code_map = {
            400: "INVALID_BODY",
            404: "FILE_NOT_FOUND",
            413: "FILE_TOO_LARGE",
            415: "UNSUPPORTED_EXTENSION",
        }
        code = code_map.get(exc.status_code, "INTERNAL_ERROR")

    return json_error(code=code, message=detail, status_code=exc.status_code)


async def _generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all 500 handler — never leaks stack traces or internal paths."""
    # In production this should also logger.exception(exc) server-side
    return json_error(
        code="INTERNAL_ERROR",
        message="An unexpected internal error occurred.",
        status_code=500,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app."""
    from fastapi import HTTPException as FastAPIHTTPException

    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(FileNotFoundError, _file_not_found_handler)
    app.add_exception_handler(UnsupportedExtensionError, _unsupported_extension_handler)
    app.add_exception_handler(FileTooLargeError, _file_too_large_handler)
    app.add_exception_handler(IngestValidationError, _ingest_validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(FastAPIHTTPException, _fastapi_http_exception_handler)
    app.add_exception_handler(Exception, _generic_exception_handler)
