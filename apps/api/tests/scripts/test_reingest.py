"""Tests for --force and --update modes (Tarea 7).

The merge policy (T7.3):
- Preserved from existing: role_es, role_en, client, impact_es, impact_en
  (human-edited values that must NOT be overwritten on re-ingest).
- Regenerated from new: title_*, summary_*, stack_*, tags, year, links.
- Slug: stable (taken from existing — it's the filename; mismatch is a bug
  that raises ValueError).
- Unknown fields in existing: preserved (might be human-added custom keys).
- Unknown fields in new: included (forward-compat with future additions).
- Empty/None values in existing for preserved fields: NOT taken as truth
  (would clobber a real None with another None — pointless).

The CLI flags --force and --update are tested indirectly via the merge
function; main() wiring is deferred to T7+T8 once the write step is in place.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.ingest_repo import (
    load_existing_frontmatter,
    merge_frontmatter_for_update,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _existing() -> dict:
    """Simulating a previous ingest + manual edits by the human."""
    return {
        "slug": "proj-hello",
        "title_es": "Hola Mundo Manual",
        "title_en": "Hello World Manual",
        "year": 2024,
        "role_es": "Tech Lead Senior",
        "role_en": "Senior Tech Lead",
        "tags": ["manual", "tags"],
        "stack_es": ["Python", "FastAPI"],
        "stack_en": ["Python", "FastAPI"],
        "summary_es": "Manual summary in Spanish.",
        "summary_en": "Manual summary in English.",
        "client": "ACME Corp",
        "impact_es": ["Redujo 50% el tiempo"],
        "impact_en": ["Reduced time by 50%"],
        "links": {
            "repo": "https://github.com/owner/hello",
            "demo": None,
            "case_study": None,
        },
    }


def _new() -> dict:
    """Simulating a fresh build from the current repo state."""
    return {
        "slug": "proj-hello",
        "title_es": "Hola Mundo",
        "title_en": "Hello World",
        "year": 2025,
        "role_es": "Tech Lead",
        "role_en": "Tech Lead",
        "tags": ["cli", "demo"],
        "stack_es": ["Python", "httpx"],
        "stack_en": ["Python", "httpx"],
        "summary_es": "Auto summary in Spanish.",
        "summary_en": "Auto summary in English.",
        "client": None,
        "impact_es": None,
        "impact_en": None,
        "links": {
            "repo": "https://github.com/owner/hello",
            "demo": "https://demo.example.com",
            "case_study": None,
        },
    }


# ===========================================================================
# merge_frontmatter_for_update — preserved fields
# ===========================================================================

class TestMergePreservesHumanFields:
    def test_preserves_role_es(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["role_es"] == "Tech Lead Senior"

    def test_preserves_role_en(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["role_en"] == "Senior Tech Lead"

    def test_preserves_client(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["client"] == "ACME Corp"

    def test_preserves_impact_es(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["impact_es"] == ["Redujo 50% el tiempo"]

    def test_preserves_impact_en(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["impact_en"] == ["Reduced time by 50%"]


# ===========================================================================
# merge_frontmatter_for_update — regenerated fields
# ===========================================================================

class TestMergeRegeneratesDerivedFields:
    def test_regenerates_title_es(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["title_es"] == "Hola Mundo"

    def test_regenerates_title_en(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["title_en"] == "Hello World"

    def test_regenerates_summary_es(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["summary_es"] == "Auto summary in Spanish."

    def test_regenerates_summary_en(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["summary_en"] == "Auto summary in English."

    def test_regenerates_tags(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["tags"] == ["cli", "demo"]

    def test_regenerates_stack_es(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["stack_es"] == ["Python", "httpx"]

    def test_regenerates_stack_en(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["stack_en"] == ["Python", "httpx"]

    def test_regenerates_year(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["year"] == 2025

    def test_regenerates_links(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["links"]["demo"] == "https://demo.example.com"


# ===========================================================================
# merge_frontmatter_for_update — slug stability
# ===========================================================================

class TestMergeSlugStability:
    def test_keeps_existing_slug(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        assert result["slug"] == "proj-hello"

    def test_raises_on_slug_mismatch(self):
        new_diff = {**_new(), "slug": "proj-different"}
        with pytest.raises(ValueError, match="slug"):
            merge_frontmatter_for_update(_existing(), new_diff)

    def test_no_raise_when_both_slugs_none(self):
        existing = {**_existing(), "slug": None}
        new = {**_new(), "slug": None}
        result = merge_frontmatter_for_update(existing, new)
        assert result["slug"] is None

    def test_no_raise_when_only_existing_has_slug(self):
        new = {**_new(), "slug": None}
        result = merge_frontmatter_for_update(_existing(), new)
        assert result["slug"] == "proj-hello"


# ===========================================================================
# merge_frontmatter_for_update — unknown / edge fields
# ===========================================================================

class TestMergeUnknownFields:
    def test_preserves_unknown_field_from_existing(self):
        existing = {**_existing(), "custom_field": "human_added"}
        result = merge_frontmatter_for_update(existing, _new())
        assert result["custom_field"] == "human_added"

    def test_includes_unknown_field_from_new(self):
        new = {**_new(), "auto_derived_extra": "auto_value"}
        result = merge_frontmatter_for_update(_existing(), new)
        assert result["auto_derived_extra"] == "auto_value"

    def test_does_not_overwrite_human_field_with_empty(self):
        # Existing has role_es = "Tech Lead Senior"; if human mistakenly emptied
        # it to None, the merge falls back to the new value (None == empty).
        existing = {**_existing(), "role_es": None}
        result = merge_frontmatter_for_update(existing, _new())
        # None is treated as empty → new value wins
        assert result["role_es"] == "Tech Lead"

    def test_does_not_overwrite_human_field_with_empty_string(self):
        existing = {**_existing(), "client": ""}
        result = merge_frontmatter_for_update(existing, _new())
        assert result["client"] is None  # empty string → new value wins

    def test_does_not_overwrite_human_field_with_empty_list(self):
        existing = {**_existing(), "impact_es": []}
        result = merge_frontmatter_for_update(existing, _new())
        assert result["impact_es"] is None  # empty list → new value wins


# ===========================================================================
# merge_frontmatter_for_update — sparse inputs
# ===========================================================================

class TestMergeSparseInputs:
    def test_existing_with_only_slug_and_title_es(self):
        sparse_existing = {"slug": "proj-hello", "title_es": "Hola"}
        result = merge_frontmatter_for_update(sparse_existing, _new())
        # title_es is in _UPDATE_REGENERATED_FIELDS, so the new value wins
        # even when the existing has a different one (re-ingest semantics).
        assert result["title_es"] == "Hola Mundo"
        assert result["title_en"] == "Hello World"  # from new
        assert result["year"] == 2025

    def test_new_with_minimal_fields(self):
        # Simulates: ingest happened before some fields existed
        minimal_new = {
            "slug": "proj-hello",
            "title_es": "Hola",
            "title_en": "Hello",
            "year": 2025,
        }
        result = merge_frontmatter_for_update(_existing(), minimal_new)
        # Fields only in new: minimal_new's value
        assert result["title_es"] == "Hola"  # from new (not preserved since existing has it but new also has it; new wins for regenerated fields)
        # Actually, the regenerated fields take from new. The existing has tags/role_es/client/impact.
        assert result["tags"] == ["manual", "tags"]  # not in new; use existing (unknown field)

    def test_full_merge_yields_expected_shape(self):
        result = merge_frontmatter_for_update(_existing(), _new())
        # Sanity: every key from either side is present
        for key in set(_existing()) | set(_new()):
            assert key in result, f"missing key: {key}"


# ===========================================================================
# load_existing_frontmatter
# ===========================================================================

class TestLoadExistingFrontmatter:
    def test_returns_none_when_file_missing(self, tmp_path: Path):
        assert load_existing_frontmatter(tmp_path / "missing.md") is None

    def test_loads_valid_frontmatter(self, tmp_path: Path):
        md = tmp_path / "proj-hello.md"
        md.write_text(
            "---\n"
            "slug: proj-hello\n"
            "title_es: Hola\n"
            "title_en: Hello\n"
            "---\n\n"
            "# Body content\n",
            encoding="utf-8",
        )
        result = load_existing_frontmatter(md)
        assert result is not None
        assert result["slug"] == "proj-hello"
        assert result["title_es"] == "Hola"
        assert result["title_en"] == "Hello"

    def test_returns_none_for_no_frontmatter(self, tmp_path: Path):
        md = tmp_path / "no-front.md"
        md.write_text("# Just a heading\n\nNo frontmatter here.\n", encoding="utf-8")
        assert load_existing_frontmatter(md) is None

    def test_returns_none_for_malformed_yaml(self, tmp_path: Path):
        md = tmp_path / "broken.md"
        md.write_text(
            "---\n"
            "slug: proj-hello\n"
            "  bad-indent: x\n"
            "\talso: y\n"
            "---\n\n",
            encoding="utf-8",
        )
        assert load_existing_frontmatter(md) is None

    def test_returns_none_when_yaml_is_not_dict(self, tmp_path: Path):
        md = tmp_path / "list-front.md"
        md.write_text("---\n- item1\n- item2\n---\n\n", encoding="utf-8")
        assert load_existing_frontmatter(md) is None

    def test_loads_minimal_frontmatter(self, tmp_path: Path):
        md = tmp_path / "minimal.md"
        md.write_text("---\nslug: proj-min\n---\n\n", encoding="utf-8")
        result = load_existing_frontmatter(md)
        assert result == {"slug": "proj-min"}
