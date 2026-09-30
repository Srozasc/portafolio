"""ProjectsService: index all project .md files into ChromaDB.

Creates two collections per project:
  - Master index: one chunk per project in `projects_index`, used by the chatbot
    to LIST matching projects.
  - Per-project detail: chunks of the body in `projects_<slug>`, used to ANSWER
    questions about a specific project.

This mirrors the IngestService pattern (validate -> chunk -> embed ->
delete-then-upsert) but operates on a whole directory of files instead of
one. Per-project failures are captured in `errors`; the batch is not aborted.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from backend.config import Settings
from backend.rag.chunker import Chunk, chunk_markdown
from backend.rag.embedder import Embedder
from backend.rag.vector_store import VectorStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class ProjectParseError(ValueError):
    """Raised when a project .md file cannot be parsed or has invalid frontmatter."""


# ---------------------------------------------------------------------------
# Slug pattern (matches Phase 1 schema)
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"^proj-[a-z0-9-]+$")


# ChromaDB collection naming rules: 3-63 chars, [a-z0-9_-], start/end alphanumeric.
_CHROMA_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,61}[a-z0-9]$")


def _validate_collection_name(name: str) -> None:
    """Raise ProjectParseError if `name` is not a valid ChromaDB collection name."""
    if not _CHROMA_NAME_RE.fullmatch(name):
        raise ProjectParseError(
            f"Invalid ChromaDB collection name '{name}': must be 3-63 chars, "
            f"lowercase alphanumeric with - or _, starting and ending with "
            f"alphanumeric."
        )


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass
class Project:
    """Parsed project from a .md file with YAML frontmatter."""

    slug: str
    frontmatter: dict  # raw YAML fields
    body: str  # markdown body without frontmatter (leading whitespace stripped)
    source_path: str  # absolute path to the .md file


@dataclass
class ProjectsIngestResult:
    """Result of ProjectsService.ingest_all."""

    indexed_projects: int
    index_chunks: int
    detail_chunks_total: int
    duration_ms: int
    project_slugs: list[str]
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ProjectsService:
    """Orchestrates indexing of a directory of project .md files.

    Public constants:
      INDEX_COLLECTION        — name of the master index collection.
      DETAIL_COLLECTION_PREFIX — prefix for per-project detail collections.
      Detail collection name = f"{DETAIL_COLLECTION_PREFIX}_{slug}" because
      ChromaDB collection names cannot contain '/'.
    """

    INDEX_COLLECTION = "projects_index"
    DETAIL_COLLECTION_PREFIX = "projects"

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        settings: Settings | None = None,
    ) -> None:
        """Initialise the projects service.

        Args:
            embedder: Embedder instance for generating chunk embeddings.
            store: VectorStore instance for ChromaDB persistence.
            settings: Application Settings instance (reads CHUNK_SIZE, CHUNK_OVERLAP).
        """
        self._embedder = embedder
        self._store = store
        self._settings = settings or Settings()

    # ---------------------------------------------------------------------------
    # Frontmatter parsing
    # ---------------------------------------------------------------------------

    def parse_project_file(self, file_path: Path) -> Project:
        """Parse one .md file: split on first two '---' lines, yaml.safe_load frontmatter.

        Args:
            file_path: Path to a .md file.

        Returns:
            Project with slug, frontmatter, body, and source_path.

        Raises:
            ProjectParseError: File cannot be parsed, frontmatter is invalid YAML,
                missing required fields, or slug does not match /^proj-[a-z0-9-]+$/.
        """
        abs_path = str(file_path.resolve())
        try:
            with open(abs_path, encoding="utf-8") as fh:
                content = fh.read()
        except OSError as exc:
            raise ProjectParseError(f"Could not read {file_path}: {exc}") from exc

        # Strip BOM
        content = content.removeprefix("\ufeff")

        # Normalise line endings
        content = content.replace("\r\n", "\n").replace("\r", "\n")

        # Split on the first two '---' lines. Frontmatter format:
        #   ---\n
        #   key: value\n
        #   ---\n
        #   <body>
        lines = content.split("\n")
        if not lines or lines[0].rstrip() != "---":
            raise ProjectParseError(
                f"{file_path}: missing opening '---' for YAML frontmatter."
            )

        # Find the closing '---' line
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].rstrip() == "---":
                end_idx = i
                break
        if end_idx is None:
            raise ProjectParseError(
                f"{file_path}: missing closing '---' for YAML frontmatter."
            )

        frontmatter_text = "\n".join(lines[1:end_idx])
        body = "\n".join(lines[end_idx + 1 :])

        # Strip leading whitespace from body
        body = body.lstrip()

        # Lazy import: keep top-level imports cheap for tooling that
        # only needs constants or dataclasses.
        import yaml

        try:
            frontmatter = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as exc:
            raise ProjectParseError(f"{file_path}: invalid YAML: {exc}") from exc

        if not isinstance(frontmatter, dict):
            raise ProjectParseError(
                f"{file_path}: YAML frontmatter must be a mapping, got "
                f"{type(frontmatter).__name__}."
            )

        slug = frontmatter.get("slug")
        if not isinstance(slug, str):
            raise ProjectParseError(
                f"{file_path}: frontmatter missing string 'slug' field."
            )
        if not _SLUG_RE.fullmatch(slug):
            raise ProjectParseError(
                f"{file_path}: slug '{slug}' does not match pattern {_SLUG_RE.pattern}."
            )

        return Project(
            slug=slug,
            frontmatter=frontmatter,
            body=body,
            source_path=abs_path,
        )

    def list_projects(self, projects_dir: Path) -> list[Project]:
        """Scan `projects_dir` for *.md files, parse frontmatter, return Project list.

        Malformed files raise ProjectParseError — caller decides whether to
        abort or continue.

        Args:
            projects_dir: Directory containing proj-*.md files.

        Returns:
            List of parsed Project objects.

        Raises:
            FileNotFoundError: `projects_dir` does not exist.
            ProjectParseError: A file in the directory is malformed.
        """
        if not projects_dir.exists():
            raise FileNotFoundError(f"projects_dir does not exist: {projects_dir}")
        if not projects_dir.is_dir():
            raise NotADirectoryError(f"projects_dir is not a directory: {projects_dir}")

        md_files = sorted(projects_dir.glob("*.md"))
        return [self.parse_project_file(p) for p in md_files]

    # ---------------------------------------------------------------------------
    # Index / chunk builders
    # ---------------------------------------------------------------------------

    def build_index_entry(self, project: Project) -> tuple[str, dict]:
        """Return (document_text, metadata) for the master index collection.

        The document is a short text blob combining titles + summaries + tags,
        so a single embedding encodes the project identity. Metadata carries
        the structured fields used for filtering (slug, year, tags as JSON, …).

        ChromaDB metadata values must be scalar (str / int / bool). Lists and
        dicts are serialised to JSON strings.

        Returns:
            (document_text, metadata_dict)
        """
        fm = project.frontmatter

        title_es = str(fm.get("title_es", "") or "")
        title_en = str(fm.get("title_en", "") or "")
        summary_es = str(fm.get("summary_es", "") or "")
        summary_en = str(fm.get("summary_en", "") or "")
        tags = fm.get("tags", []) or []
        tags_str = ", ".join(str(t) for t in tags)

        document_text = (
            f"{title_es}\n{title_en}\n{summary_es}\n{summary_en}\nTags: {tags_str}"
        )

        metadata: dict = {
            "slug": project.slug,
            "title_es": title_es,
            "title_en": title_en,
            "year": fm.get("year"),
            "role_es": str(fm.get("role_es", "") or ""),
            "role_en": str(fm.get("role_en", "") or ""),
            "client": str(fm.get("client", "") or ""),
            "tags": json.dumps(list(tags)),
            "summary_es": summary_es,
            "summary_en": summary_en,
        }

        # Optional fields, included only when present (JSON-encoded).
        if "impact_es" in fm and fm["impact_es"] is not None:
            metadata["impact_es"] = json.dumps(list(fm["impact_es"]))
        if "impact_en" in fm and fm["impact_en"] is not None:
            metadata["impact_en"] = json.dumps(list(fm["impact_en"]))

        return document_text, metadata

    def build_project_chunks(self, project: Project) -> list[Chunk]:
        """Use chunk_markdown on the project body (frontmatter excluded).

        The returned Chunks carry the chunker's metadata (source, section_header,
        chunk_index, char_start/char_end). Per-project metadata
        ({slug, source, year, section_header, chunk_index}) is composed in
        ``_ingest_one`` when the chunks are upserted, matching the IngestService
        pattern.

        Args:
            project: Parsed Project.

        Returns:
            List of Chunk objects from the project body.
        """
        return chunk_markdown(
            project.body,
            source=project.source_path,
            chunk_size=self._settings.CHUNK_SIZE,
            overlap=self._settings.CHUNK_OVERLAP,
        )

    # ---------------------------------------------------------------------------
    # Collection helpers
    # ---------------------------------------------------------------------------

    def detail_collection_name(self, slug: str) -> str:
        """Return the per-project detail collection name for a slug.

        ChromaDB disallows '/' in collection names, so we use
        'projects_<slug>' (underscore separator).
        """
        name = f"{self.DETAIL_COLLECTION_PREFIX}_{slug}"
        _validate_collection_name(name)
        return name

    # ---------------------------------------------------------------------------
    # Per-project indexing
    # ---------------------------------------------------------------------------

    def _ingest_one(
        self,
        project: Project,
        *,
        force: bool,
        index_state: dict,
    ) -> tuple[int, int]:
        """Index a single project. Returns (index_chunks, detail_chunks).

        Args:
            project: Parsed Project.
            force: If True, delete-then-upsert for both collections.
            index_state: Mutable dict tracking the in-progress master index
                (entries to add, whether force was applied).

        Returns:
            (index_chunk_count, detail_chunk_count) — each project contributes
            exactly 1 index chunk and N detail chunks.

        Raises:
            ProjectParseError: Re-raised after logging if a chunk/embed step fails.
        """
        # 1. Build the master index entry (single chunk).
        index_doc, index_meta = self.build_index_entry(project)

        # 2. Build the per-project detail chunks from the body.
        detail_chunks = self.build_project_chunks(project)

        # 3. Prepare embeddings for both collections.
        #    We embed the index document + all detail chunk texts in one call.
        texts_to_embed = [index_doc] + [c.text for c in detail_chunks]
        embeddings = self._embedder.embed(texts_to_embed)

        if len(embeddings) != len(texts_to_embed):
            raise ProjectParseError(
                f"{project.slug}: embedder returned {len(embeddings)} vectors "
                f"for {len(texts_to_embed)} texts."
            )

        index_embedding = embeddings[0]
        detail_embeddings = embeddings[1:]

        # 4. Index collection: delete-then-upsert on every call (cheap, 1 chunk per
        #    project) so updates always reflect the latest frontmatter.
        #    We delete the master collection ONCE per batch (first project only)
        #    and then accumulate entries; the flush happens after all projects.
        if force and not index_state.get("force_applied_to_index", False):
            self._store.delete_collection(self.INDEX_COLLECTION)
            index_state["force_applied_to_index"] = True

        # 5. Append index entry for this project.
        #    We accumulate all index entries in `index_state` and flush once
        #    after all projects are processed.
        index_state.setdefault("index_ids", [])
        index_state.setdefault("index_docs", [])
        index_state.setdefault("index_embeddings", [])
        index_state.setdefault("index_metas", [])

        index_state["index_ids"].append(f"{project.slug}__index")
        index_state["index_docs"].append(index_doc)
        index_state["index_embeddings"].append(index_embedding)
        index_state["index_metas"].append(index_meta)

        # 6. Detail collection: delete-then-upsert per project when force=True.
        detail_name = self.detail_collection_name(project.slug)
        if force:
            self._store.delete_collection(detail_name)

        if detail_chunks:
            self._store.upsert(
                name=detail_name,
                ids=[f"{project.slug}__chunk_{i}" for i in range(len(detail_chunks))],
                embeddings=detail_embeddings,
                documents=[c.text for c in detail_chunks],
                metadatas=[
                    {
                        "slug": project.slug,
                        "source": c.source,
                        "year": project.frontmatter.get("year"),
                        "section_header": c.section_header,
                        "chunk_index": c.chunk_index,
                        "char_start": c.char_start,
                        "char_end": c.char_end,
                    }
                    for c in detail_chunks
                ],
            )

        return 1, len(detail_chunks)

    # ---------------------------------------------------------------------------
    # Batch entry point
    # ---------------------------------------------------------------------------

    def ingest_all(
        self,
        projects_dir: Path,
        force: bool = False,
    ) -> ProjectsIngestResult:
        """Index every *.md file in `projects_dir` into ChromaDB.

        For each project:
          1. Parse the file (frontmatter + body).
          2. Build master index entry (slug, titles, summaries, tags).
          3. Build detail chunks from body via chunk_markdown.
          4. Delete-then-upsert the index collection (when force=True).
          5. Delete-then-upsert the per-project detail collection.
          6. Track per-project errors without aborting the batch.

        Args:
            projects_dir: Directory of proj-*.md files.
            force: If True, delete existing collections before upserting
                (use for first run or schema changes).

        Returns:
            ProjectsIngestResult with summary and any per-project errors.

        Raises:
            FileNotFoundError: `projects_dir` does not exist.
        """
        start_ns = time.monotonic_ns()

        if not projects_dir.exists():
            raise FileNotFoundError(f"projects_dir does not exist: {projects_dir}")

        index_state: dict = {
            "index_ids": [],
            "index_docs": [],
            "index_embeddings": [],
            "index_metas": [],
            "force_applied_to_index": False,
        }

        indexed_projects = 0
        detail_chunks_total = 0
        project_slugs: list[str] = []
        errors: list[str] = []

        md_files = sorted(projects_dir.glob("*.md"))
        for md_file in md_files:
            try:
                project = self.parse_project_file(md_file)
            except ProjectParseError as exc:
                logger.warning("Skipping malformed project %s: %s", md_file, exc)
                errors.append(f"{md_file}: {exc}")
                continue
            except Exception as exc:  # defensive: don't lose a file to a crash
                logger.exception("Unexpected error parsing %s", md_file)
                errors.append(f"{md_file}: unexpected error: {exc}")
                continue

            try:
                _, n_detail = self._ingest_one(
                    project, force=force, index_state=index_state
                )
            except ProjectParseError as exc:
                logger.warning(
                    "Skipping project %s after indexing error: %s", project.slug, exc
                )
                errors.append(f"{project.slug}: {exc}")
                continue
            except Exception as exc:
                logger.exception("Unexpected error indexing %s", project.slug)
                errors.append(f"{project.slug}: unexpected error: {exc}")
                continue

            indexed_projects += 1
            detail_chunks_total += n_detail
            project_slugs.append(project.slug)

        # Flush the master index in one upsert call.
        if index_state["index_ids"]:
            if force and not index_state["force_applied_to_index"]:
                # Force was requested but nothing was deleted yet (no projects
                # indexed) — still ensure a clean slate if any entries exist.
                self._store.delete_collection(self.INDEX_COLLECTION)
            self._store.upsert(
                name=self.INDEX_COLLECTION,
                ids=index_state["index_ids"],
                embeddings=index_state["index_embeddings"],
                documents=index_state["index_docs"],
                metadatas=index_state["index_metas"],
            )

        # When force=True, also clean up per-project collections whose source
        # .md no longer exists on disk. This prevents accumulating orphan
        # collections across re-ingests (e.g., after a project is removed from
        # the portfolio). Safe with force=False (no-op — orphans persist
        # until the next --force run, which is the right semantics for
        # incremental updates).
        if force:
            self._cleanup_orphan_collections(project_slugs)

        duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000

        return ProjectsIngestResult(
            indexed_projects=indexed_projects,
            index_chunks=indexed_projects,  # one chunk per project in master index
            detail_chunks_total=detail_chunks_total,
            duration_ms=duration_ms,
            project_slugs=project_slugs,
            errors=errors,
        )

    def _cleanup_orphan_collections(self, current_slugs: list[str]) -> int:
        """Delete per-project detail collections whose slug is not in current_slugs.

        Called from ``ingest_all(force=True)`` to remove orphan collections
        (per-project collections whose source ``.md`` was deleted from disk).
        The master ``INDEX_COLLECTION`` is handled separately by the force
        delete-then-upsert flow, so it's skipped here.

        Args:
            current_slugs: Slugs of projects that exist on disk in this reindex.

        Returns:
            Count of orphan collections deleted.
        """
        current_set = set(current_slugs)
        deleted = 0
        for col_name in self._store.list_collections():
            # Skip the master index (deleted/upserted by the force flow)
            if col_name == self.INDEX_COLLECTION:
                continue
            # Only per-project detail collections (projects_<slug>)
            if not col_name.startswith(self.DETAIL_COLLECTION_PREFIX + "_"):
                continue
            # Extract slug: "projects_proj-foo" -> "proj-foo"
            slug = col_name[len(self.DETAIL_COLLECTION_PREFIX) + 1 :]
            if slug not in current_set:
                logger.info(
                    "Deleting orphan detail collection: %s (slug %r not on disk)",
                    col_name,
                    slug,
                )
                self._store.delete_collection(col_name)
                deleted += 1
        return deleted
