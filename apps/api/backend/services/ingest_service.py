"""Ingest service: chunk -> embed -> delete-then-upsert pipeline.

Design: design.md Module APIs / WU 2.1.
Orchestrates: file validation -> chunker -> embedder -> VectorStore upsert.
Idempotent per REQ-ING-007 (delete-collection before upsert).
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from backend.config import Settings
from backend.rag.chunker import Chunk, chunk_markdown
from backend.rag.embedder import Embedder
from backend.rag.vector_store import VectorStore


# ---------------------------------------------------------------------------
# Custom exceptions (raised by the service; translated to HTTP by the route)
# ---------------------------------------------------------------------------


class IngestValidationError(Exception):
    """Base class for ingest validation errors."""


class UnsupportedExtensionError(IngestValidationError):
    """Raised when the file extension is not .md or .markdown."""


class FileTooLargeError(IngestValidationError):
    """Raised when the file size exceeds MAX_INGEST_BYTES."""


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    """Return value of IngestService.ingest_file."""

    collection: str
    chunks_indexed: int
    total_chars: int
    duration_ms: int


# ---------------------------------------------------------------------------
# Slugify (matches design.md Decision 2)
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    """Derive a safe collection name from a file stem.

    Lowercases, replaces any run of non-[a-z0-9] with a single '-',
    then strips leading/trailing '-'.
    """
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


# ChromaDB collection naming rules: 3-63 chars, [a-z0-9_-], start/end alphanumeric.
_CHROMA_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,61}[a-z0-9]")


def _validate_collection_name(name: str) -> None:
    """Raise IngestValidationError if `name` is not a valid ChromaDB collection name.

    Per design Decision 2 + ChromaDB requirements.
    """
    if not _CHROMA_NAME_RE.fullmatch(name):
        raise IngestValidationError(
            f"Invalid collection name '{name}': must be 3-63 chars, "
            f"lowercase alphanumeric with - or _, starting and ending "
            f"with alphanumeric."
        )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class IngestService:
    """Orchestrates the ingest pipeline: validate -> chunk -> embed -> upsert."""

    def __init__(
        self,
        chunker,
        embedder: Embedder,
        store: VectorStore,
        settings: Settings | None = None,
    ) -> None:
        """Initialise the ingest service.

        Args:
            chunker: Callable that returns list[Chunk] (typically chunk_markdown).
            embedder: Embedder instance for generating chunk embeddings.
            store: VectorStore instance for ChromaDB persistence.
            settings: Application Settings instance (reads MAX_INGEST_BYTES).
        """
        self._chunker = chunker
        self._embedder = embedder
        self._store = store
        self._settings = settings or Settings()
        self._max_bytes = self._settings.MAX_INGEST_BYTES

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    def ingest_file(
        self,
        file_path: str,
        collection_override: str | None = None,
    ) -> IngestResult:
        """Ingest a markdown file into ChromaDB.

        Algorithm:
          1. Resolve `file_path` and validate (exists, extension, size).
          2. Read file content.
          3. Chunk via `self._chunker`.
          4. Embed chunks via `self._embedder`.
          5. Derive collection name (slugify(stem) or override).
          6. delete_collection(name) — idempotent, handles re-ingest.
          7. upsert(name, ids, embeddings, texts, metadatas).
          8. Return IngestResult.

        Args:
            file_path: Absolute or relative path to the markdown file.
            collection_override: Optional explicit collection name (bypasses
                slugify(stem(file_path))).

        Returns:
            IngestResult with collection name, chunk count, char count, duration.

        Raises:
            FileNotFoundError: The file does not exist.
            UnsupportedExtensionError: Extension is not .md or .markdown.
            FileTooLargeError: File size exceeds MAX_INGEST_BYTES.
        """
        start_ns = time.monotonic_ns()

        # --- Step 1: resolve and pre-flight validate ---
        path = Path(file_path)
        abs_path = str(path.resolve())

        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = path.suffix.lower()
        if ext not in (".md", ".markdown"):
            raise UnsupportedExtensionError(
                f"Unsupported extension '{ext}': only .md and .markdown are accepted."
            )

        file_size = os.path.getsize(abs_path)
        if file_size > self._max_bytes:
            raise FileTooLargeError(
                f"File size {file_size} exceeds MAX_INGEST_BYTES={self._max_bytes}."
            )

        # --- Step 2: read content ---
        with open(abs_path, encoding="utf-8") as fh:
            content = fh.read()

        total_chars = len(content)

        # --- Step 3: chunk ---
        chunks: list[Chunk] = self._chunker(
            content,
            source=abs_path,
            chunk_size=self._settings.CHUNK_SIZE,
            overlap=self._settings.CHUNK_OVERLAP,
        )

        # --- Step 4: embed ---
        texts_for_embed = [c.text for c in chunks]
        embeddings: list[list[float]] = self._embedder.embed(texts_for_embed)

        # --- Step 5: collection name ---
        if collection_override:
            # Defense-in-depth: validate the override against ChromaDB's
            # naming rules. Prevents the caller from clobbering or creating
            # collections with surprising names.
            _validate_collection_name(collection_override)
            collection = collection_override
        else:
            collection = _slugify(path.stem)
            # Defense-in-depth: also validate the slugify output (an all-
            # punctuation stem would produce an empty string).
            if not collection:
                raise IngestValidationError(
                    f"Could not derive a valid collection name from '{file_path}'."
                )
            _validate_collection_name(collection)

        # --- Step 6 + 7: delete then upsert (idempotent per REQ-ING-007) ---
        self._store.delete_collection(collection)

        chunk_ids = [f"chunk_{i}" for i in range(len(chunks))]
        chunk_texts = [c.text for c in chunks]
        chunk_metas = [
            {
                "source": c.source,
                "section_header": c.section_header,
                "chunk_index": c.chunk_index,
                "char_start": c.char_start,
                "char_end": c.char_end,
            }
            for c in chunks
        ]

        self._store.upsert(
            name=collection,
            ids=chunk_ids,
            embeddings=embeddings,
            documents=chunk_texts,
            metadatas=chunk_metas,
        )

        # --- Step 8: duration and result ---
        duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000

        return IngestResult(
            collection=collection,
            chunks_indexed=len(chunks),
            total_chars=total_chars,
            duration_ms=duration_ms,
        )
