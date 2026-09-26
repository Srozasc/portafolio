"""Tests for validate_frontmatter, build_frontmatter, write_project_md (Tarea 2)."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from scripts.ingest_repo import (
    FrontmatterValidationError,
    ProjectExistsError,
    StreamError,
    build_frontmatter,
    validate_frontmatter,
    write_project_md,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def minimal_valid_frontmatter(**overrides) -> dict:
    """Return a frontmatter dict that passes validation. Override fields ad-hoc."""
    fm = {
        "slug": "proj-hello",
        "title_es": "Hola Mundo",
        "title_en": "Hello World",
        "year": 2024,
        "role_es": "Tech Lead",
        "role_en": "Tech Lead",
        "tags": ["cli"],
        "stack_es": ["Python"],
        "stack_en": ["Python"],
        "summary_es": "Un proyecto de prueba para validar el schema.",
        "summary_en": "A test project used to validate the schema.",
        "client": None,
        "impact_es": None,
        "impact_en": None,
        "links": {
            "repo": "https://github.com/owner/hello",
            "demo": None,
            "case_study": None,
        },
    }
    fm.update(overrides)
    return fm


def make_repo_data(**overrides) -> dict:
    """Return a fake GitHub repo_data dict for build_frontmatter inputs."""
    data = {
        "name": "hello-world",
        "full_name": "owner/hello-world",
        "description": "A test project for the ingestion pipeline.",
        "language": "Python",
        "topics": ["cli", "demo"],
        "created_at": "2024-01-15T10:00:00Z",
        "default_branch": "main",
        "html_url": "https://github.com/owner/hello-world",
    }
    data.update(overrides)
    return data


# ===========================================================================
# validate_frontmatter — mirrors apps/web/src/content/config.ts
# ===========================================================================


class TestValidateFrontmatter:
    def test_minimal_valid_passes(self):
        validate_frontmatter(minimal_valid_frontmatter())  # no raise

    def test_non_dict_raises(self):
        with pytest.raises(FrontmatterValidationError, match="must be a dict"):
            validate_frontmatter("not a dict")  # type: ignore[arg-type]

    def test_missing_slug_raises(self):
        fm = minimal_valid_frontmatter()
        del fm["slug"]
        with pytest.raises(FrontmatterValidationError, match="slug"):
            validate_frontmatter(fm)

    def test_invalid_slug_uppercase_raises(self):
        fm = minimal_valid_frontmatter(slug="Hello-World")
        with pytest.raises(FrontmatterValidationError, match=r"/\^proj-"):
            validate_frontmatter(fm)

    def test_slug_without_proj_prefix_raises(self):
        fm = minimal_valid_frontmatter(slug="hello-world")
        with pytest.raises(FrontmatterValidationError, match=r"/\^proj-"):
            validate_frontmatter(fm)

    def test_title_es_too_short_raises(self):
        fm = minimal_valid_frontmatter(title_es="ab")
        with pytest.raises(FrontmatterValidationError, match="title_es"):
            validate_frontmatter(fm)

    def test_title_en_too_short_raises(self):
        fm = minimal_valid_frontmatter(title_en="ab")
        with pytest.raises(FrontmatterValidationError, match="title_en"):
            validate_frontmatter(fm)

    def test_year_too_low_raises(self):
        fm = minimal_valid_frontmatter(year=1999)
        with pytest.raises(FrontmatterValidationError, match="year"):
            validate_frontmatter(fm)

    def test_year_too_high_raises(self):
        fm = minimal_valid_frontmatter(year=2200)
        with pytest.raises(FrontmatterValidationError, match="year"):
            validate_frontmatter(fm)

    def test_year_must_be_int(self):
        fm = minimal_valid_frontmatter(year="2024")  # type: ignore[arg-type]
        with pytest.raises(FrontmatterValidationError, match="year"):
            validate_frontmatter(fm)

    def test_year_bool_rejected(self):
        fm = minimal_valid_frontmatter(year=True)  # type: ignore[arg-type]
        with pytest.raises(FrontmatterValidationError, match="year"):
            validate_frontmatter(fm)

    def test_empty_tags_raises(self):
        fm = minimal_valid_frontmatter(tags=[])
        with pytest.raises(FrontmatterValidationError, match="tags"):
            validate_frontmatter(fm)

    def test_tags_must_be_strings(self):
        fm = minimal_valid_frontmatter(tags=["cli", 42])  # type: ignore[list-item]
        with pytest.raises(FrontmatterValidationError, match="tags"):
            validate_frontmatter(fm)

    def test_empty_stack_es_raises(self):
        fm = minimal_valid_frontmatter(stack_es=[])
        with pytest.raises(FrontmatterValidationError, match="stack_es"):
            validate_frontmatter(fm)

    def test_empty_stack_en_raises(self):
        fm = minimal_valid_frontmatter(stack_en=[])
        with pytest.raises(FrontmatterValidationError, match="stack_en"):
            validate_frontmatter(fm)

    def test_summary_es_too_short_raises(self):
        fm = minimal_valid_frontmatter(summary_es="corto")
        with pytest.raises(FrontmatterValidationError, match="summary_es"):
            validate_frontmatter(fm)

    def test_summary_en_too_short_raises(self):
        fm = minimal_valid_frontmatter(summary_en="short")
        with pytest.raises(FrontmatterValidationError, match="summary_en"):
            validate_frontmatter(fm)

    def test_role_es_required(self):
        fm = minimal_valid_frontmatter()
        del fm["role_es"]
        with pytest.raises(FrontmatterValidationError, match="role_es"):
            validate_frontmatter(fm)

    def test_role_en_required(self):
        fm = minimal_valid_frontmatter()
        del fm["role_en"]
        with pytest.raises(FrontmatterValidationError, match="role_en"):
            validate_frontmatter(fm)

    def test_client_none_ok(self):
        fm = minimal_valid_frontmatter(client=None)
        validate_frontmatter(fm)  # no raise

    def test_client_string_ok(self):
        fm = minimal_valid_frontmatter(client="ACME Corp")
        validate_frontmatter(fm)

    def test_client_must_be_string_when_present(self):
        fm = minimal_valid_frontmatter(client=123)  # type: ignore[arg-type]
        with pytest.raises(FrontmatterValidationError, match="client"):
            validate_frontmatter(fm)

    def test_impact_none_ok(self):
        fm = minimal_valid_frontmatter(impact_es=None, impact_en=None)
        validate_frontmatter(fm)

    def test_impact_list_of_strings_ok(self):
        fm = minimal_valid_frontmatter(
            impact_es=["Reducido 50% el tiempo de deploy", "Saved $1M"],
            impact_en=["Reduced deploy time by 50%", "Saved $1M"],
        )
        validate_frontmatter(fm)

    def test_impact_must_be_list_of_strings(self):
        fm = minimal_valid_frontmatter(impact_es=["line", 42])
        with pytest.raises(FrontmatterValidationError, match="impact_es"):
            validate_frontmatter(fm)

    def test_links_repo_must_be_http_url(self):
        fm = minimal_valid_frontmatter()
        fm["links"]["repo"] = "not-a-url"
        with pytest.raises(FrontmatterValidationError, match="links.repo"):
            validate_frontmatter(fm)

    def test_links_repo_none_ok(self):
        fm = minimal_valid_frontmatter()
        fm["links"]["repo"] = None
        validate_frontmatter(fm)

    def test_links_demo_must_be_http_url(self):
        fm = minimal_valid_frontmatter()
        fm["links"]["demo"] = "ftp://example.com"
        with pytest.raises(FrontmatterValidationError, match="links.demo"):
            validate_frontmatter(fm)

    def test_links_case_study_can_be_relative_or_url(self):
        # Per the TS schema, case_study is .nullable() (no .url() constraint).
        fm = minimal_valid_frontmatter()
        fm["links"]["case_study"] = "/blog/case-studies/hello"
        validate_frontmatter(fm)


# ===========================================================================
# build_frontmatter
# ===========================================================================


class _MockLLMClient:
    """Mock LLMClient that returns 5 fixed tags as a JSON array.

    Used to mock the LLM in build_frontmatter tests so they don't
    require an actual OpenAI call. ``response_text`` is overridable
    per-test to simulate failure modes (invalid JSON, wrong count,
    non-list, etc.).
    """

    def __init__(self, response_text: str | None = None) -> None:
        self.response_text = response_text or json.dumps(
            ["api-gateway", "typescript", "rate-limiting", "circuit-breaker", "fastify"]
        )
        self.call_count = 0
        self.last_system: str | None = None
        self.last_user: str | None = None

    def chat(self, system: str, user: str, **kwargs) -> str:
        self.call_count += 1
        self.last_system = system
        self.last_user = user
        return self.response_text


class TestBuildFrontmatter:
    def test_returns_zod_valid_dict_en(self):
        repo = make_repo_data()
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        validate_frontmatter(fm)  # integration: built dict must validate

    def test_returns_zod_valid_dict_es(self):
        repo = make_repo_data()
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="es",
            llm_client=_MockLLMClient(),
        )
        validate_frontmatter(fm)

    def test_invalid_detected_lang_raises(self):
        repo = make_repo_data()
        with pytest.raises(ValueError, match="detected_lang"):
            build_frontmatter(
                repo,
                role="Tech Lead",
                detected_lang="fr",
                llm_client=_MockLLMClient(),
            )

    def test_empty_role_raises(self):
        repo = make_repo_data()
        with pytest.raises(ValueError, match="role"):
            build_frontmatter(
                repo, role="", detected_lang="en", llm_client=_MockLLMClient()
            )

    def test_missing_llm_client_raises(self):
        """Per user policy: build_frontmatter requires an LLM client."""
        repo = make_repo_data()
        with pytest.raises(ValueError, match="llm_client is required"):
            build_frontmatter(repo, role="Tech Lead", detected_lang="en")

    def test_slug_derived_from_repo_name(self):
        repo = make_repo_data(name="My-Cool-Repo")
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        assert fm["slug"] == "proj-my-cool-repo"
        import re as _re

        assert _re.match(r"^proj-[a-z0-9-]+$", fm["slug"])

    def test_year_comes_from_created_at(self):
        repo = make_repo_data(created_at="2023-06-01T12:34:56Z")
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        assert fm["year"] == 2023

    def test_year_defaults_when_created_at_missing(self):
        repo = make_repo_data()
        del repo["created_at"]
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        assert isinstance(fm["year"], int)
        assert 2000 <= fm["year"] <= 2100

    def test_year_out_of_range_falls_back(self):
        repo = make_repo_data(created_at="1850-01-01T00:00:00Z")
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        assert 2000 <= fm["year"] <= 2100

    def test_en_detected_fills_en_title_with_real_content(self):
        repo = make_repo_data(name="hello")
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        assert "TODO" not in fm["title_en"]
        assert fm["title_en"] != ""

    def test_es_detected_fills_es_title_with_real_content(self):
        repo = make_repo_data(name="hola")
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="es",
            llm_client=_MockLLMClient(),
        )
        assert "TODO" not in fm["title_es"]
        assert fm["title_es"] != ""

    def test_other_lang_title_is_placeholder(self):
        repo = make_repo_data()
        fm_en = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        assert fm_en["title_es"] != fm_en["title_en"]
        assert "TODO" in fm_en["title_es"] or "traducc" in fm_en["title_es"].lower()

    def test_other_lang_summary_is_placeholder_zod_safe(self):
        repo = make_repo_data()
        fm_en = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        assert len(fm_en["summary_es"]) >= 20
        assert ("TODO" in fm_en["summary_es"]) or (
            "traducc" in fm_en["summary_es"].lower()
        )

    def test_es_detection_placeholder_in_en_side(self):
        repo = make_repo_data()
        fm_es = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="es",
            llm_client=_MockLLMClient(),
        )
        assert "TODO" in fm_es["title_en"] or "traducc" in fm_es["title_en"].lower()
        assert "TODO" in fm_es["summary_en"] or "traducc" in fm_es["summary_en"].lower()

    def test_includes_github_html_url_as_link_repo(self):
        repo = make_repo_data(html_url="https://github.com/foo/bar")
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        assert fm["links"]["repo"] == "https://github.com/foo/bar"

    def test_tags_includes_llm_generated(self):
        """tags combines existing (lang + topics) + 5 LLM-generated tags."""
        repo = make_repo_data(language="Python", topics=["api"])
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),  # default 5 tags
        )
        # 2 existing (python, api) + 5 LLM tags = 7 total (no overlap with mock)
        assert "python" in fm["tags"]
        assert "api" in fm["tags"]
        assert "api-gateway" in fm["tags"]
        assert "fastify" in fm["tags"]
        assert len(fm["tags"]) == 7

    def test_tags_dedupes_case_insensitive_with_llm(self):
        """If the LLM returns a tag that's already in existing, it's deduped."""
        repo = make_repo_data(language="Python", topics=[])
        # Mock LLM that returns a tag matching the existing language.
        mock_llm = _MockLLMClient(
            response_text=json.dumps(
                ["python", "django", "flask", "fastapi", "postgres"]
            )
        )
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=mock_llm,
        )
        # "python" appears once, not twice
        assert fm["tags"].count("python") == 1
        assert "django" in fm["tags"]
        assert "fastapi" in fm["tags"]

    def test_llm_failure_propagates_runtime_error(self):
        """If the LLM raises StreamError, build_frontmatter propagates it."""
        repo = make_repo_data()
        bad_llm = MagicMock()
        bad_llm.chat.side_effect = StreamError("API down")
        with pytest.raises(RuntimeError, match="LLM failed to generate tags"):
            build_frontmatter(
                repo,
                role="Tech Lead",
                detected_lang="en",
                llm_client=bad_llm,
            )

    def test_llm_invalid_json_propagates_runtime_error(self):
        """If the LLM returns non-JSON, build_frontmatter raises RuntimeError."""
        repo = make_repo_data()
        mock_llm = _MockLLMClient(response_text="this is not json")
        with pytest.raises(RuntimeError, match="invalid JSON"):
            build_frontmatter(
                repo,
                role="Tech Lead",
                detected_lang="en",
                llm_client=mock_llm,
            )

    def test_llm_wrong_count_propagates_runtime_error(self):
        """If the LLM returns != 5 tags, build_frontmatter raises RuntimeError."""
        repo = make_repo_data()
        mock_llm = _MockLLMClient(response_text=json.dumps(["only", "three", "tags"]))
        with pytest.raises(RuntimeError, match="expected exactly 5"):
            build_frontmatter(
                repo,
                role="Tech Lead",
                detected_lang="en",
                llm_client=mock_llm,
            )

    def test_handles_missing_description(self):
        repo = make_repo_data()
        repo["description"] = None
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        assert len(fm["summary_en"]) >= 20
        assert len(fm["summary_es"]) >= 20

    def test_pads_short_description_to_min_summary_length(self):
        repo = make_repo_data(description="Short.")
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        assert len(fm["summary_en"]) >= 20

    def test_handles_empty_topics(self):
        """When language is None and topics are empty, stack is [] but tags
        still has 5 LLM-generated entries (per current policy: LLM is
        always called)."""
        repo = make_repo_data()
        repo["topics"] = []
        repo["language"] = None
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        assert fm["stack_en"] == []
        assert len(fm["tags"]) == 5  # 5 from LLM, 0 from existing

    def test_stack_language_first_then_topics(self):
        repo = make_repo_data(language="Python", topics=["cli", "demo"])
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        assert fm["stack_en"][0] == "Python"
        assert "cli" in fm["stack_en"]
        assert "demo" in fm["stack_en"]

    def test_stack_dedupes_case_insensitive(self):
        repo = make_repo_data(language="Python", topics=["python", "cli"])
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        # count of case-insensitive "python" occurrences
        normalized = [s.lower() for s in fm["stack_en"]]
        assert normalized.count("python") == 1

    def test_tags_includes_lowercased_language_in_existing(self) -> None:
        """Regression: when only language exists (no topics), tags must
        include the lowercased language in the 'existing' portion."""
        repo = make_repo_data(language="TypeScript", topics=[])
        mock_llm = _MockLLMClient(
            response_text=json.dumps(
                [
                    "api-gateway",
                    "rate-limiting",
                    "circuit-breaker",
                    "fastify",
                    "observability",
                ]
            )
        )
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=mock_llm,
        )
        assert "typescript" in fm["tags"]
        # 1 existing + 5 LLM = 6 total
        assert len(fm["tags"]) == 6
        # LLM tags after existing
        assert fm["tags"][0] == "typescript"
        assert "api-gateway" in fm["tags"]

    def test_role_passed_through_to_both_languages(self):
        repo = make_repo_data()
        fm = build_frontmatter(
            repo,
            role="Senior Engineer",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        assert fm["role_es"] == "Senior Engineer"
        assert fm["role_en"] == "Senior Engineer"

    def test_impact_fields_default_to_none(self):
        repo = make_repo_data()
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        assert fm["impact_es"] is None
        assert fm["impact_en"] is None

    def test_html_url_garbage_normalized_to_none(self):
        repo = make_repo_data(html_url="not-a-url")
        fm = build_frontmatter(
            repo,
            role="Tech Lead",
            detected_lang="en",
            llm_client=_MockLLMClient(),
        )
        # Either None or normalized away; we just want the validation to pass.
        if fm["links"]["repo"] is not None:
            assert fm["links"]["repo"].startswith(("http://", "https://"))


# ===========================================================================
# write_project_md
# ===========================================================================


class TestWriteProjectMd:
    def _fm(self, slug: str = "proj-hello") -> dict:
        return minimal_valid_frontmatter(slug=slug)

    def test_writes_file_with_yaml_frontmatter_and_body(self, tmp_path: Path):
        body = "# Hello\n\nThis is the body.\n"
        out = write_project_md(self._fm(), body, tmp_path)
        assert out.exists()
        assert out.name == "proj-hello.md"
        text = out.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        # Find closing ---
        parts = text.split("---\n", 2)
        assert len(parts) == 3
        _, yaml_text, body_after = parts
        parsed = yaml.safe_load(yaml_text)
        assert parsed["slug"] == "proj-hello"
        assert parsed["year"] == 2024
        assert body_after.lstrip().startswith("# Hello")

    def test_creates_out_dir_if_missing(self, tmp_path: Path):
        out_dir = tmp_path / "deep" / "nested" / "projects"
        assert not out_dir.exists()
        write_project_md(self._fm(), "body", out_dir)
        assert out_dir.exists()
        assert (out_dir / "proj-hello.md").exists()

    def test_raises_project_exists_error_without_force(self, tmp_path: Path):
        write_project_md(self._fm(), "first body", tmp_path)
        with pytest.raises(ProjectExistsError, match="already exists"):
            write_project_md(self._fm(), "second body", tmp_path)

    def test_existing_file_left_untouched_on_conflict(self, tmp_path: Path):
        first = write_project_md(self._fm(), "first body", tmp_path)
        with contextlib.suppress(ProjectExistsError):
            write_project_md(self._fm(), "second body", tmp_path)
        assert first.read_text(encoding="utf-8").endswith("first body\n")

    def test_force_overwrites_existing(self, tmp_path: Path):
        out1 = write_project_md(self._fm(), "first body", tmp_path)
        out2 = write_project_md(self._fm(), "second body", tmp_path, force=True)
        assert out1 == out2
        text = out2.read_text(encoding="utf-8")
        assert "second body" in text
        assert "first body" not in text

    def test_atomic_write_no_partial_files_on_failure(
        self, tmp_path: Path, monkeypatch
    ):
        # Force os.replace to raise after the temp file has been written.
        target_path = tmp_path / "proj-hello.md"

        def boom(src, dst):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError, match="simulated"):
            write_project_md(self._fm(), "body", tmp_path)
        # Target file must not exist (we never replaced).
        assert not target_path.exists()
        # No leftover .tmp files in tmp_path.
        leftover = [p.name for p in tmp_path.iterdir()]
        assert not any(name.endswith(".md.tmp") for name in leftover), (
            f"unexpected tmp leftovers: {leftover}"
        )

    def test_writes_utf8_characters(self, tmp_path: Path):
        fm = minimal_valid_frontmatter(
            slug="proj-utf8",
            summary_es="Diseño — ñoño, ¡genial!",
            title_es="Hola Mí Mundo",
        )
        write_project_md(fm, "Cuerpo con ñ, á, é, ü.\n", tmp_path)
        out = tmp_path / "proj-utf8.md"
        assert out.exists()
        text = out.read_text(encoding="utf-8")
        assert "ñ" in text
        assert "á" in text

    def test_invalid_frontmatter_raises_before_writing(self, tmp_path: Path):
        fm = minimal_valid_frontmatter(slug="INVALID-Upper")
        with pytest.raises(FrontmatterValidationError, match="slug"):
            write_project_md(fm, "body", tmp_path)
        assert not (tmp_path / "INVALID-Upper.md").exists()
        # Also no leftover tmp
        leftover = [p.name for p in tmp_path.iterdir()]
        assert not any(name.endswith(".md.tmp") for name in leftover)

    def test_body_rstrip_then_trailing_newline(self, tmp_path: Path):
        body = "body with trailing whitespace   \n\n\n"
        out = write_project_md(self._fm(), body, tmp_path)
        text = out.read_text(encoding="utf-8")
        # No trailing whitespace before final newline
        assert text.endswith("body with trailing whitespace\n")
        assert "   \n" not in text

    def test_output_is_yaml_round_trippable(self, tmp_path: Path):
        fm = minimal_valid_frontmatter(
            slug="proj-yaml",
            tags=["one", "two"],
            stack_es=["Python", "FastAPI"],
            links={
                "repo": "https://github.com/foo/bar",
                "demo": "https://demo.example.com",
                "case_study": "/blog/cs",
            },
        )
        write_project_md(fm, "body\n", tmp_path)
        text = (tmp_path / "proj-yaml.md").read_text(encoding="utf-8")
        _, yaml_text, _ = text.split("---\n", 2)
        parsed = yaml.safe_load(yaml_text)
        assert parsed == fm
