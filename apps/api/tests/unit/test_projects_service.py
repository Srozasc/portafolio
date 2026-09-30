"""Unit tests for backend.services.projects_service.

Embedder and store are mocked; the focus is on:
  - frontmatter parsing (valid / invalid slug / missing frontmatter)
  - build_index_entry (document shape + metadata fields)
  - build_project_chunks (body-only, no frontmatter leakage)
  - ingest_all flow (delete-then-upsert order, per-project error tolerance,
    index chunks count for N projects)

Uses pytest tmp_path for any real file IO. No ChromaDB needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.services.projects_service import (
    Project,
    ProjectParseError,
    ProjectsService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sample_md(
    slug: str = "proj-test",
    title_es: str = "Título ES",
    title_en: str = "Title EN",
    body: str = "## Contexto\n\nPárrafo de prueba.",
) -> str:
    """Return a sample .md text with valid frontmatter."""
    return (
        f"---\n"
        f"slug: {slug}\n"
        f"title_es: {title_es}\n"
        f"title_en: {title_en}\n"
        f"year: 2024\n"
        f"role_es: Tech Lead\n"
        f"role_en: Tech Lead\n"
        f"client: Cliente X\n"
        f"tags:\n"
        f"  - python\n"
        f"  - aws\n"
        f'summary_es: "Resumen ES"\n'
        f'summary_en: "Summary EN"\n'
        f"impact_es:\n"
        f'  - "Métrica 1"\n'
        f'  - "Métrica 2"\n'
        f"---\n"
        f"\n"
        f"{body}\n"
    )


def _write_md(tmp_path: Path, name: str, content: str) -> Path:
    """Write a .md file under tmp_path/name and return its path."""
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def embedder_mock():
    """Mock embedder returning a deterministic 16-dim vector per text."""
    embedder = MagicMock()
    embedder.embed.side_effect = lambda texts: [
        [float(i)] * 16 for i, _ in enumerate(texts)
    ]
    return embedder


@pytest.fixture
def store_mock():
    """Mock VectorStore with no-op upsert/delete and a list_collections stub."""
    store = MagicMock()
    store.delete_collection.return_value = None
    store.upsert.return_value = None
    store.list_collections.return_value = []
    return store


@pytest.fixture
def service(embedder_mock, store_mock):
    """ProjectsService wired with mocks (no Settings needed for tests)."""
    return ProjectsService(embedder=embedder_mock, store=store_mock, settings=None)


# ---------------------------------------------------------------------------
# parse_project_file
# ---------------------------------------------------------------------------


class TestParseProjectFile:
    def test_valid(self, tmp_path: Path, service: ProjectsService) -> None:
        """Valid frontmatter parses into a Project with all fields populated."""
        md = _write_md(tmp_path, "proj-foo.md", _make_sample_md(slug="proj-foo"))

        project = service.parse_project_file(md)

        assert project.slug == "proj-foo"
        assert project.frontmatter["title_es"] == "Título ES"
        assert project.frontmatter["title_en"] == "Title EN"
        assert project.frontmatter["year"] == 2024
        assert project.frontmatter["tags"] == ["python", "aws"]
        assert "## Contexto" in project.body
        # Source path is absolute and points at the file we wrote.
        assert Path(project.source_path).resolve() == md.resolve()
        # Leading whitespace before the body was stripped.
        assert not project.body.startswith("\n")

    def test_invalid_slug_raises(
        self, tmp_path: Path, service: ProjectsService
    ) -> None:
        """frontmatter with `slug: BadSlug` raises ProjectParseError."""
        bad = "---\nslug: BadSlug\ntitle_es: X\ntitle_en: Y\n---\n\nBody\n"
        md = _write_md(tmp_path, "bad.md", bad)

        with pytest.raises(ProjectParseError) as excinfo:
            service.parse_project_file(md)
        assert "slug" in str(excinfo.value).lower()

    def test_invalid_slug_uppercase_raises(
        self, tmp_path: Path, service: ProjectsService
    ) -> None:
        """Slug with uppercase letters is rejected."""
        bad = "---\nslug: proj-Foo\ntitle_es: X\ntitle_en: Y\n---\n\nBody\n"
        md = _write_md(tmp_path, "bad.md", bad)
        with pytest.raises(ProjectParseError):
            service.parse_project_file(md)

    def test_invalid_slug_no_prefix_raises(
        self, tmp_path: Path, service: ProjectsService
    ) -> None:
        """Slug without proj- prefix is rejected."""
        bad = "---\nslug: foo\ntitle_es: X\ntitle_en: Y\n---\n\nBody\n"
        md = _write_md(tmp_path, "bad.md", bad)
        with pytest.raises(ProjectParseError):
            service.parse_project_file(md)

    def test_missing_frontmatter_raises(
        self, tmp_path: Path, service: ProjectsService
    ) -> None:
        """File without `---` opening separator raises ProjectParseError."""
        md = _write_md(
            tmp_path, "nofm.md", "# Just a heading\n\nNo frontmatter here.\n"
        )

        with pytest.raises(ProjectParseError) as excinfo:
            service.parse_project_file(md)
        assert "frontmatter" in str(excinfo.value).lower()

    def test_unclosed_frontmatter_raises(
        self, tmp_path: Path, service: ProjectsService
    ) -> None:
        """Frontmatter without closing `---` raises ProjectParseError."""
        md = _write_md(tmp_path, "unclosed.md", "---\nslug: proj-foo\ntitle_es: x\n")

        with pytest.raises(ProjectParseError):
            service.parse_project_file(md)

    def test_missing_slug_field_raises(
        self, tmp_path: Path, service: ProjectsService
    ) -> None:
        """Valid frontmatter but missing slug field raises ProjectParseError."""
        bad = "---\ntitle_es: X\ntitle_en: Y\n---\n\nBody\n"
        md = _write_md(tmp_path, "no-slug.md", bad)
        with pytest.raises(ProjectParseError) as excinfo:
            service.parse_project_file(md)
        assert "slug" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# list_projects
# ---------------------------------------------------------------------------


class TestListProjects:
    def test_missing_dir_raises(self, service: ProjectsService, tmp_path: Path) -> None:
        """Non-existent directory raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            service.list_projects(tmp_path / "does-not-exist")

    def test_returns_one_project_per_file(
        self, service: ProjectsService, tmp_path: Path
    ) -> None:
        """Two valid .md files → two Project entries."""
        _write_md(tmp_path, "a.md", _make_sample_md(slug="proj-a"))
        _write_md(tmp_path, "b.md", _make_sample_md(slug="proj-b"))

        projects = service.list_projects(tmp_path)
        assert len(projects) == 2
        slugs = {p.slug for p in projects}
        assert slugs == {"proj-a", "proj-b"}

    def test_ignores_non_md(self, service: ProjectsService, tmp_path: Path) -> None:
        """Files without .md extension are ignored."""
        _write_md(tmp_path, "a.md", _make_sample_md(slug="proj-a"))
        _write_md(tmp_path, "notes.txt", "irrelevant")

        projects = service.list_projects(tmp_path)
        assert len(projects) == 1
        assert projects[0].slug == "proj-a"


# ---------------------------------------------------------------------------
# build_index_entry
# ---------------------------------------------------------------------------


class TestBuildIndexEntry:
    def test_document_contains_titles_and_summaries(
        self, service: ProjectsService
    ) -> None:
        """Document text contains title_es, title_en, summary_es, summary_en, Tags."""
        project = Project(
            slug="proj-x",
            frontmatter={
                "title_es": "T1 ES",
                "title_en": "T1 EN",
                "summary_es": "S1 ES",
                "summary_en": "S1 EN",
                "tags": ["python", "aws"],
                "year": 2024,
                "role_es": "Lead",
                "role_en": "Lead",
            },
            body="body",
            source_path="/abs/proj-x.md",
        )

        doc, _meta = service.build_index_entry(project)

        assert "T1 ES" in doc
        assert "T1 EN" in doc
        assert "S1 ES" in doc
        assert "S1 EN" in doc
        assert "python" in doc
        assert "aws" in doc

    def test_metadata_has_required_fields(self, service: ProjectsService) -> None:
        """Metadata dict contains slug, year, title_es/en, summary_es/en, tags-as-JSON."""
        project = Project(
            slug="proj-x",
            frontmatter={
                "title_es": "T ES",
                "title_en": "T EN",
                "summary_es": "S ES",
                "summary_en": "S EN",
                "tags": ["python", "aws"],
                "year": 2024,
                "role_es": "Lead",
                "role_en": "Lead",
                "client": "Acme",
            },
            body="body",
            source_path="/abs/proj-x.md",
        )

        _doc, meta = service.build_index_entry(project)

        assert meta["slug"] == "proj-x"
        assert meta["year"] == 2024
        assert meta["title_es"] == "T ES"
        assert meta["title_en"] == "T EN"
        assert meta["summary_es"] == "S ES"
        assert meta["summary_en"] == "S EN"
        assert meta["role_es"] == "Lead"
        assert meta["role_en"] == "Lead"
        assert meta["client"] == "Acme"

        # tags must be JSON-encoded (ChromaDB requires scalar metadata values).
        assert isinstance(meta["tags"], str)
        assert json.loads(meta["tags"]) == ["python", "aws"]

    def test_metadata_includes_impact_when_present(
        self, service: ProjectsService
    ) -> None:
        """impact_es / impact_en are JSON-encoded when present."""
        project = Project(
            slug="proj-x",
            frontmatter={
                "title_es": "T ES",
                "title_en": "T EN",
                "summary_es": "S ES",
                "summary_en": "S EN",
                "tags": ["python"],
                "year": 2024,
                "role_es": "Lead",
                "role_en": "Lead",
                "impact_es": ["Métrica A", "Métrica B"],
                "impact_en": ["Metric A", "Metric B"],
            },
            body="body",
            source_path="/abs/proj-x.md",
        )

        _doc, meta = service.build_index_entry(project)
        assert json.loads(meta["impact_es"]) == ["Métrica A", "Métrica B"]
        assert json.loads(meta["impact_en"]) == ["Metric A", "Metric B"]

    def test_metadata_omits_impact_when_missing(self, service: ProjectsService) -> None:
        """impact_es / impact_en are absent from metadata when not in frontmatter."""
        project = Project(
            slug="proj-x",
            frontmatter={
                "title_es": "T ES",
                "title_en": "T EN",
                "summary_es": "S ES",
                "summary_en": "S EN",
                "tags": ["python"],
                "year": 2024,
                "role_es": "Lead",
                "role_en": "Lead",
            },
            body="body",
            source_path="/abs/proj-x.md",
        )

        _doc, meta = service.build_index_entry(project)
        assert "impact_es" not in meta
        assert "impact_en" not in meta


# ---------------------------------------------------------------------------
# build_project_chunks
# ---------------------------------------------------------------------------


class TestBuildProjectChunks:
    def test_uses_body_not_frontmatter(self, service: ProjectsService) -> None:
        """Chunks do NOT include the frontmatter text."""
        # Body is long enough to produce at least one chunk.
        body = "## Contexto\n\n" + ("Párrafo con palabras. " * 80)
        project = Project(
            slug="proj-x",
            frontmatter={"title_es": "Should NOT appear in chunks", "year": 2024},
            body=body,
            source_path="/abs/proj-x.md",
        )

        chunks = service.build_project_chunks(project)

        assert len(chunks) >= 1
        joined = "\n".join(c.text for c in chunks)
        assert "Should NOT appear in chunks" not in joined
        # The body content IS in the chunks
        assert "Párrafo con palabras" in joined

    def test_source_is_the_file_path(self, service: ProjectsService) -> None:
        """Each chunk's source attribute is the file's absolute path."""
        project = Project(
            slug="proj-x",
            frontmatter={},
            body="## Section\n\nSome content here.",
            source_path="/abs/path/proj-x.md",
        )

        chunks = service.build_project_chunks(project)
        assert len(chunks) >= 1
        for c in chunks:
            assert c.source == "/abs/path/proj-x.md"

    def test_empty_body_returns_no_chunks(self, service: ProjectsService) -> None:
        """Body with only whitespace returns an empty list."""
        project = Project(
            slug="proj-x",
            frontmatter={},
            body="",
            source_path="/abs/proj-x.md",
        )
        assert service.build_project_chunks(project) == []


# ---------------------------------------------------------------------------
# detail_collection_name
# ---------------------------------------------------------------------------


class TestDetailCollectionName:
    def test_prefixes_with_projects_underscore(self, service: ProjectsService) -> None:
        """Detail collection name uses `projects_<slug>` (underscore separator)."""
        assert (
            service.detail_collection_name("proj-data-pipeline")
            == "projects_proj-data-pipeline"
        )

    def test_rejects_invalid_chroma_names(self, service: ProjectsService) -> None:
        """Slugs that would produce invalid ChromaDB names raise ProjectParseError."""
        # A slug with a '/' would map to an invalid name.
        with pytest.raises(ProjectParseError):
            service.detail_collection_name("proj-foo/bar")


# ---------------------------------------------------------------------------
# ingest_all
# ---------------------------------------------------------------------------


class TestIngestAll:
    def test_force_deletes_then_upserts(
        self, embedder_mock, store_mock, tmp_path: Path
    ) -> None:
        """With force=True, delete_collection is called before upsert for
        both the master index and each detail collection."""
        _write_md(tmp_path, "a.md", _make_sample_md(slug="proj-a"))
        _write_md(tmp_path, "b.md", _make_sample_md(slug="proj-b"))

        service = ProjectsService(
            embedder=embedder_mock, store=store_mock, settings=None
        )
        result = service.ingest_all(tmp_path, force=True)

        # Force deleted the master collection once.
        names = [c.args[0] for c in store_mock.delete_collection.call_args_list]
        assert ProjectsService.INDEX_COLLECTION in names
        # Detail collections were also deleted (one per project).
        assert "projects_proj-a" in names
        assert "projects_proj-b" in names

        # upsert was called for the master index + 2 detail collections.
        upsert_names = [c.kwargs.get("name") for c in store_mock.upsert.call_args_list]
        assert ProjectsService.INDEX_COLLECTION in upsert_names
        assert "projects_proj-a" in upsert_names
        assert "projects_proj-b" in upsert_names

        # Result summary
        assert result.indexed_projects == 2
        assert result.index_chunks == 2  # one index entry per project
        assert result.detail_chunks_total > 0
        assert sorted(result.project_slugs) == ["proj-a", "proj-b"]
        assert result.errors == []

    def test_continues_on_per_project_error(
        self, embedder_mock, store_mock, tmp_path: Path
    ) -> None:
        """One malformed file does NOT abort the batch; errors list populated."""
        _write_md(tmp_path, "good.md", _make_sample_md(slug="proj-good"))
        _write_md(
            tmp_path,
            "bad.md",
            "---\nslug: BadSlug\ntitle_es: x\ntitle_en: y\n---\n\nBody\n",
        )
        _write_md(tmp_path, "other-good.md", _make_sample_md(slug="proj-other"))

        service = ProjectsService(
            embedder=embedder_mock, store=store_mock, settings=None
        )
        result = service.ingest_all(tmp_path, force=True)

        assert result.indexed_projects == 2
        assert sorted(result.project_slugs) == ["proj-good", "proj-other"]
        assert len(result.errors) == 1
        assert (
            "bad.md" in result.errors[0].lower() or "slug" in result.errors[0].lower()
        )

    def test_index_chunks_count_matches_projects(
        self, embedder_mock, store_mock, tmp_path: Path
    ) -> None:
        """Five projects → five chunks in the master index upsert call."""
        for i in range(5):
            _write_md(tmp_path, f"p{i}.md", _make_sample_md(slug=f"proj-p{i}"))

        service = ProjectsService(
            embedder=embedder_mock, store=store_mock, settings=None
        )
        result = service.ingest_all(tmp_path, force=True)

        assert result.indexed_projects == 5
        assert result.index_chunks == 5

        # Verify the master index upsert received 5 ids/documents/embeddings.
        master_upsert = None
        for call in store_mock.upsert.call_args_list:
            if call.kwargs.get("name") == ProjectsService.INDEX_COLLECTION:
                master_upsert = call
                break
        assert master_upsert is not None
        ids_arg = master_upsert.kwargs["ids"]
        docs_arg = master_upsert.kwargs["documents"]
        assert len(ids_arg) == 5
        assert len(docs_arg) == 5

    def test_force_false_skips_master_delete(
        self, embedder_mock, store_mock, tmp_path: Path
    ) -> None:
        """Without force, the master index is NOT deleted."""
        _write_md(tmp_path, "a.md", _make_sample_md(slug="proj-a"))

        service = ProjectsService(
            embedder=embedder_mock, store=store_mock, settings=None
        )
        service.ingest_all(tmp_path, force=False)

        # The master index should not have been deleted.
        deleted_names = [c.args[0] for c in store_mock.delete_collection.call_args_list]
        assert ProjectsService.INDEX_COLLECTION not in deleted_names

    def test_empty_dir_returns_zero(
        self, embedder_mock, store_mock, tmp_path: Path
    ) -> None:
        """Empty directory returns a result with zero counts, no errors."""
        service = ProjectsService(
            embedder=embedder_mock, store=store_mock, settings=None
        )
        result = service.ingest_all(tmp_path, force=True)

        assert result.indexed_projects == 0
        assert result.index_chunks == 0
        assert result.detail_chunks_total == 0
        assert result.project_slugs == []
        assert result.errors == []

    def test_missing_dir_raises(
        self, embedder_mock, store_mock, tmp_path: Path
    ) -> None:
        """Non-existent projects_dir raises FileNotFoundError."""
        service = ProjectsService(
            embedder=embedder_mock, store=store_mock, settings=None
        )
        with pytest.raises(FileNotFoundError):
            service.ingest_all(tmp_path / "missing", force=True)


# ---------------------------------------------------------------------------
# Smoke check on the real fixture data
# ---------------------------------------------------------------------------


class TestAgainstSeedFixtures:
    """Light coverage that the service runs end-to-end on the actual seed projects.

    Uses real ChromaDB in tmp_path (the only real dependency). No embedding calls
    (mocked) so this stays in the unit tier.
    """

    def test_seed_files_parse_and_index(self, embedder_mock, store_mock) -> None:
        """All seed projects in apps/api/data/projects/ parse and index.

        As of the placeholder cleanup (commit 17483be), only the 2 real
        projects remain: proj-portafolio-rag and proj-safegateway.
        """
        from backend.config import Settings

        seed_dir = Path(__file__).parent.parent.parent / "data" / "projects"
        if not seed_dir.exists():
            pytest.skip(f"Seed directory not present: {seed_dir}")

        # Use real Settings so we exercise the real config wiring.
        service = ProjectsService(
            embedder=embedder_mock,
            store=store_mock,
            settings=Settings(),
        )
        result = service.ingest_all(seed_dir, force=True)

        assert result.indexed_projects == 2
        assert result.index_chunks == 2
        assert result.detail_chunks_total > 0
        assert sorted(result.project_slugs) == [
            "proj-portafolio-rag",
            "proj-safegateway",
        ]
        assert result.errors == []
