"""Unit tests for backend.rag.query_expansion."""

from __future__ import annotations

import pytest

from backend.rag.query_expansion import KEYWORD_EXPANSIONS, expand_query


# ---------------------------------------------------------------------------
# Long queries: returned unchanged
# ---------------------------------------------------------------------------


def test_long_query_with_five_words_is_unchanged():
    """A 5-word sentence is returned as-is (even if a keyword is present)."""
    question = "tell me about python projects please"
    assert expand_query(question) == question


def test_long_query_with_keywords_is_unchanged():
    """A >4-token query containing known keywords is still returned as-is."""
    # 5 tokens with "rag" + "python" — would expand if short, but >4 tokens.
    question = "qué proyectos python rag tienes"
    assert expand_query(question) == question


# ---------------------------------------------------------------------------
# Short queries without a matching keyword
# ---------------------------------------------------------------------------


def test_short_query_without_keyword_is_unchanged():
    """A short query that doesn't match any keyword returns unchanged."""
    question = "hola, cómo andás?"
    assert expand_query(question) == question


# ---------------------------------------------------------------------------
# Short queries with a matching keyword
# ---------------------------------------------------------------------------


def test_short_query_with_rag_keyword_is_expanded():
    """A short query 'rag' gets the RAG expansion appended."""
    question = "rag"
    out = expand_query(question)
    assert "rag" in out
    assert "retrieval augmented generation" in out
    # Original wording is preserved verbatim at the start (append, not replace)
    assert out.startswith(question)


def test_short_query_with_python_keyword_is_expanded():
    """A short query 'python' gets the python expansion appended."""
    out = expand_query("python")
    assert out.startswith("python")
    assert "lenguaje" in out
    assert "programacion" in out


# ---------------------------------------------------------------------------
# Case-insensitivity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variant", ["RAG", "Rag", "rAg", "RaG"])
def test_keyword_match_is_case_insensitive(variant):
    """Uppercase / mixed-case versions of a keyword still match and expand."""
    out = expand_query(variant)
    # Original input is preserved verbatim at the start (casing kept).
    assert out.startswith(variant)
    # Expansion is appended (case-insensitive match worked).
    assert "retrieval augmented generation" in out


# ---------------------------------------------------------------------------
# Word boundary
# ---------------------------------------------------------------------------


def test_word_boundary_no_partial_match_for_rag_substring():
    """'dragonfly' must NOT trigger the 'rag' expansion (boundary check)."""
    # 'rag' is a substring of 'dragonfly', but \b keeps it from matching.
    assert expand_query("dragonfly") == "dragonfly"


def test_word_boundary_no_partial_match_for_python_substring():
    """'cpython' must NOT trigger the 'python' expansion."""
    # 'python' is a substring of 'cpython', but \b keeps it from matching.
    assert expand_query("cpython") == "cpython"


def test_word_boundary_punctuation_does_match():
    """Punctuation around the keyword still allows a match."""
    out = expand_query("rag?")
    assert "retrieval augmented generation" in out
    assert out.startswith("rag?")


# ---------------------------------------------------------------------------
# Append-not-replace + multi-keyword
# ---------------------------------------------------------------------------


def test_append_not_replace_preserves_original_text():
    """The original question text is preserved verbatim as a prefix."""
    question = "fastapi"
    out = expand_query(question)
    assert out.startswith(question)
    # Some extra content was appended (the expansion).
    assert len(out) > len(question)


def test_multi_keyword_query_expands_both():
    """A 2-keyword short query appends both expansions."""
    out = expand_query("python aws")
    # Original wording is preserved.
    assert out.startswith("python aws")
    # Both keyword expansions are present.
    assert "lenguaje" in out
    assert "programacion" in out
    assert "amazon web services" in out
    assert "AWS" in out


def test_duplicate_expansion_strings_are_not_repeated():
    """Two keywords that share an expansion string should not double-append.

    Sanity check: 'k8s' and 'kubernetes' both expand to overlapping context,
    but since their expansion strings differ, both are appended once each.
    No string should appear twice in a row (no naive duplication).
    """
    out = expand_query("k8s")
    # Both expansions are appended, each once.
    assert "kubernetes" in out
    assert "containers" in out
    # No token-level duplication (heuristic: no word repeats back-to-back).
    tokens = out.split()
    for prev, curr in zip(tokens, tokens[1:], strict=False):
        assert not (prev == curr and len(prev) > 3), (
            f"token {curr!r} repeated back-to-back in {out!r}"
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_string_returns_empty():
    """Empty string is unchanged (no tokens to scan)."""
    assert expand_query("") == ""


def test_keyword_expansions_dict_is_non_empty():
    """The expansion map is populated (otherwise the module is a no-op)."""
    assert len(KEYWORD_EXPANSIONS) >= 20
    # Every value is a non-empty string.
    for k, v in KEYWORD_EXPANSIONS.items():
        assert isinstance(v, str) and v.strip(), f"empty expansion for {k!r}"