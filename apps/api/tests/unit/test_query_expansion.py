"""Unit tests for backend.rag.query_expansion."""

from __future__ import annotations

import pytest

from backend.rag.query_expansion import KEYWORD_EXPANSIONS, expand_query


# ---------------------------------------------------------------------------
# Long queries: keyword presence is the only gate
# ---------------------------------------------------------------------------


def test_long_query_with_five_words_is_unchanged():
    """A >4-token sentence with NO recognized tech keyword passes through.

    Even though it is long, the only gate now is keyword presence — length
    is irrelevant. A recruiter sentence that doesn't mention any tech
    keyword (e.g. small-talk or a meta-question) is returned verbatim.
    """
    question = "tell me about your projects please"
    assert expand_query(question) == question


def test_long_query_with_keywords_is_now_expanded():
    """A >4-token query containing a known keyword IS expanded.

    Previously the >4-token guard short-circuited and returned the query
    unchanged even when keywords were present. Now any recognized keyword
    fires the expansion regardless of sentence length, so recruiter-style
    Spanish sentences like this one expand.
    """
    long_query_with_keyword = "que proyectos tienes con python y aws"
    result = expand_query(long_query_with_keyword)
    # Original wording is preserved at the start (append-only).
    assert "python" in result.lower()
    # And at least one of the keyword expansions is appended.
    assert any(
        marker in result.lower()
        for marker in ["lenguaje programacion", "amazon web services"]
    )


def test_six_token_query_with_keyword_is_now_expanded():
    """Reported failure: 6-token 'Como fue la migracion a cloud que lidere'.

    Both 'migracion' and 'cloud' are recognized keywords — the sentence
    must expand even though it is longer than the old 4-token cap.
    """
    question = "Como fue la migracion a cloud que lidere"
    result = expand_query(question)
    # Original is preserved at the start (append-only).
    assert result.startswith(question)
    # Keyword presence fires the expansion; 'migracion' appends Spanish
    # with-tilde form 'migración' and 'cloud' appends cloud-related context.
    assert "migración" in result
    assert "AWS" in result


def test_five_token_question_about_rag_is_now_expanded():
    """Reported failure: 5-token 'y que hay de rag?' must expand.

    Old behavior bailed out at >4 tokens and the bot deflected. New
    behavior fires on keyword presence — 'rag' triggers the RAG expansion
    regardless of sentence length.
    """
    question = "y que hay de rag?"
    result = expand_query(question)
    # Original is preserved at the start (append-only).
    assert result.startswith(question)
    # The rag expansion is appended.
    assert "retrieval augmented generation" in result


def test_long_question_with_no_tech_keyword_still_unchanged():
    """A long Spanish sentence with no recognized keyword passes through.

    The keyword gate still applies: 'Cómo estuvo tu día ayer hermano?'
    contains no tech term, so even though it has 6 tokens the expansion
    must not fire and no noise is appended to the embedder input.
    """
    question = "Como estuvo tu día ayer hermano?"
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


# ---------------------------------------------------------------------------
# Accent-insensitive matching + Spanish-recruiter keywords
# ---------------------------------------------------------------------------


def test_migracion_without_tilde_matches():
    """User types 'migracion a cloud' (no tildes) — still matches and expands.

    The recruiter-style query has no diacritics, but the expansion map
    carries proper Spanish ('migración') so the embedder sees rich Spanish
    context after expansion.
    """
    out = expand_query("migracion a cloud")
    # Original user wording is preserved verbatim at the start (append-only).
    assert out.startswith("migracion a cloud")
    # The expansion includes the proper Spanish with-tilde form.
    assert "migración" in out
    # And the cloud keyword also triggered its expansion.
    assert "cloud" in out
    assert "AWS" in out


def test_cloud_keyword_matches():
    """Short 'cloud' query expands with cloud-related context."""
    out = expand_query("cloud")
    assert out.startswith("cloud")
    assert "nube" in out
    assert "AWS" in out


def test_nube_keyword_matches():
    """Short 'nube' query expands; long 'nube' query also expands now."""
    # Short query (2 tokens) expands.
    out_short = expand_query("proyectos nube")
    assert out_short.startswith("proyectos nube")
    assert "AWS" in out_short
    # Long query (6 tokens) used to bail out under the old >4 guard. Now
    # keyword presence is the only gate, so 'nube' triggers expansion even
    # in a full sentence.
    long_q = "qué proyectos hiciste en la nube"
    out_long = expand_query(long_q)
    assert out_long.startswith(long_q)
    assert "AWS" in out_long


@pytest.mark.parametrize(
    "variant",
    ["MIGRACIÓN", "migracion", "Migración", "migración a cloud"],
)
def test_accent_insensitive_matching(variant):
    """Same keyword with/without tilde (and mixed casing) produces an expansion.

    All variants must trigger the 'migracion' expansion — the match is
    normalized via NFKD before the word-boundary regex.
    """
    out = expand_query(variant)
    # Original input is preserved verbatim at the start.
    assert out.startswith(variant)
    # The Spanish with-tilde form appears in the expansion suffix.
    assert "migración" in out


def test_does_not_modify_user_text():
    """The original substring is preserved at the start; expansion is APPENDED."""
    question = "migracion a cloud"
    out = expand_query(question)
    # Original wording is unchanged at the start.
    assert out.startswith(question)
    # And something extra was appended (the expansion).
    assert len(out) > len(question)


def test_palabra_con_tilde_en_keyword_matchea_sin_tilde_en_query():
    """Query typed WITH a tilde matches the no-tilde keyword (and vice versa).

    Symmetric accent-insensitivity: 'migración' typed by the user still
    hits the 'migracion' keyword in the map.
    """
    out_with_tilde = expand_query("migración")
    out_without_tilde = expand_query("migracion")
    # Both expand.
    assert "migración" in out_with_tilde
    assert "migración" in out_without_tilde
    # Original casing is preserved at the start of each result.
    assert out_with_tilde.startswith("migración")
    assert out_without_tilde.startswith("migracion")


def test_word_boundary_still_holds_after_normalization():
    """NFKD normalization doesn't break \\b — 'raíz' does NOT match 'rag'.

    'raíz' normalizes to 'raiz'. The regex \\brag\\b against 'raiz' must NOT
    match because 'rag' is not a complete word in 'raiz'. This guards against
    a regression where dropping combining marks turns word boundaries into
    naive substring matches.
    """
    out = expand_query("raíz")
    # The 'rag' expansion must NOT be appended.
    assert "retrieval augmented generation" not in out
    # With no other matching keyword, the result is the original unchanged.
    assert out == "raíz"
