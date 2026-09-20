"""Unit tests for backend.rag.prompts.

Covers:
  - Byte-for-byte pinning of SYSTEM_PROMPT_TEMPLATE against design doc §8.
  - build_chat_system_prompt() output structure.
"""

import unicodedata
from pathlib import Path

import pytest
from backend.rag.chunker import Chunk
from backend.rag.prompts import (
    SYSTEM_PROMPT_TEMPLATE,
    build_chat_system_prompt,
    build_portfolio_chat_system_prompt,
)

# ---------------------------------------------------------------------------
# Byte-for-byte pinning test (Decision 7 / REQ-CHS-003)
# ---------------------------------------------------------------------------

def _extract_design_doc_template() -> str:
    """Read design doc §8 template.

    The template starts at "Sos un asistente" and ends at the line
    before "=== FIN ===" (which is inside the template content itself).
    We use "Sos un asistente" as the start anchor to avoid matching
    "INFORMACIÓN RECUPERADA" which appears inside the template body.
    """
    design_doc = Path(__file__).parent.parent.parent / "docs" / "plans" / "2026-07-01-hirag15k-design.md"
    content = design_doc.read_text(encoding="utf-8")

    # The template starts at "Sos un asistente" and ends right after "=== FIN ==="
    # (the marker IS part of the string literal, not an editorial delimiter).
    start_marker = "Sos un asistente"
    end_marker = "=== FIN ==="

    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)

    if start_idx == -1:
        pytest.fail(f"Could not find start marker {start_marker!r} in {design_doc}")
    if end_idx == -1:
        pytest.fail(f"Could not find end marker {end_marker!r} in {design_doc}")

    # Extract from start through the end marker INCLUSIVE (slicing is half-open,
    # so we add len(end_marker) to keep the marker in the extracted template).
    template_text = content[start_idx:end_idx + len(end_marker)]
    return unicodedata.normalize("NFC", template_text)


class TestPromptPinning:
    """REQ-CHS-003: system prompt is byte-for-byte locked to design doc §8."""

    def test_template_matches_design_doc(self):
        """Pin SYSTEM_PROMPT_TEMPLATE against the actual design doc file."""
        design_doc_template = _extract_design_doc_template()
        our_template = unicodedata.normalize("NFC", SYSTEM_PROMPT_TEMPLATE)

        if our_template != design_doc_template:
            # Find first diff for readable error
            min_len = min(len(our_template), len(design_doc_template))
            for i in range(min_len):
                if our_template[i] != design_doc_template[i]:
                    raise AssertionError(
                        f"SYSTEM_PROMPT_TEMPLATE drifted from design doc §8 at position {i}.\n"
                        f"Our char: {our_template[i]!r} (U+{ord(our_template[i]):04X})\n"
                        f"Doc  char: {design_doc_template[i]!r} (U+{ord(design_doc_template[i]):04X})\n"
                        f"Our context: {our_template[max(0,i-10):i+10]!r}\n"
                        f"Doc  context: {design_doc_template[max(0,i-10):i+10]!r}"
                    )
            raise AssertionError(
                f"Length mismatch: ours={len(our_template)} vs doc={len(design_doc_template)}"
            )


class TestBuildChatSystemPrompt:
    """build_chat_system_prompt() output structure."""

    def test_empty_chunks_uses_deflection_notice(self):
        """Empty retrieval yields a 'no chunks' notice, not an empty substitution."""
        result = build_chat_system_prompt([])
        assert "(No se recuperó ningún fragmento relevante.)" in result

    def test_single_chunk_formatted_correctly(self):
        """One chunk produces the expected section_header | chunk_0 format."""
        chunks = [
            Chunk(
                text="Este es el contenido.",
                source="/test/file.md",
                section_header="Introducción",
                chunk_index=0,
                char_start=0,
                char_end=20,
                token_count=5,
            )
        ]
        result = build_chat_system_prompt(chunks)
        assert "Introducción | chunk_0" in result
        assert "Este es el contenido." in result
        assert "=== INFORMACIÓN RECUPERADA ===" in result

    def test_multiple_chunks_separated_by_blank_line(self):
        """Multiple chunks are joined with double newlines."""
        chunks = [
            Chunk(
                text="Contenido A.",
                source="/test/file.md",
                section_header="Sección A",
                chunk_index=0,
                char_start=0,
                char_end=12,
                token_count=3,
            ),
            Chunk(
                text="Contenido B.",
                source="/test/file.md",
                section_header="Sección B",
                chunk_index=1,
                char_start=13,
                char_end=26,
                token_count=3,
            ),
        ]
        result = build_chat_system_prompt(chunks)
        assert "Sección A | chunk_0" in result
        assert "Contenido A." in result
        assert "Sección B | chunk_1" in result
        assert "Contenido B." in result
        # Blank line separator
        assert "\n\n" in result

    def test_no_heading_uses_sin_encabezado(self):
        """Chunks without a heading use '(sin encabezado)' as section_header."""
        chunks = [
            Chunk(
                text="Texto sin encabezado.",
                source="/test/file.md",
                section_header="(sin encabezado)",
                chunk_index=0,
                char_start=0,
                char_end=20,
                token_count=5,
            )
        ]
        result = build_chat_system_prompt(chunks)
        assert "(sin encabezado) | chunk_0" in result

    def test_retrieved_chunks_marker_replaced(self):
        """The {retrieved_chunks_with_metadata} placeholder is substituted."""
        chunks = [
            Chunk(
                text=" info.",
                source="/test/file.md",
                section_header="Test",
                chunk_index=0,
                char_start=0,
                char_end=6,
                token_count=2,
            )
        ]
        result = build_chat_system_prompt(chunks)
        assert "{retrieved_chunks_with_metadata}" not in result


# ---------------------------------------------------------------------------
# Phase 5.5: project_context injection in the portfolio builder
# ---------------------------------------------------------------------------


class TestPortfolioProjectContext:
    """build_portfolio_chat_system_prompt() injects a project context block
    when ``project_context`` is provided, and omits it otherwise.

    The block tells the LLM which project the visitor is currently viewing
    and to default to that project on ambiguous questions. Two localizations
    are exercised (es, en). The literal placeholder ``{project_context}``
    must never leak into the rendered output.
    """

    def test_portfolio_prompt_includes_current_project_context_when_provided_es(self):
        """lang='es' + project_context -> slug, title, and localized phrase present."""
        result = build_portfolio_chat_system_prompt(
            [],
            lang="es",
            project_context={
                "slug": "proj-cloud-migration",
                "title": "Migración de monolito a microservicios",
            },
        )
        assert "proj-cloud-migration" in result
        assert "Migración de monolito a microservicios" in result
        assert "El visitante está viendo" in result
        # No literal placeholder leaks.
        assert "{project_context}" not in result

    def test_portfolio_prompt_includes_current_project_context_when_provided_en(self):
        """lang='en' + project_context -> slug, title, and English phrase present."""
        result = build_portfolio_chat_system_prompt(
            [],
            lang="en",
            project_context={
                "slug": "proj-cloud-migration",
                "title": "Monolith to Microservices Migration",
            },
        )
        assert "proj-cloud-migration" in result
        assert "Monolith to Microservices Migration" in result
        assert "The visitor is currently viewing" in result
        assert "{project_context}" not in result

    def test_portfolio_prompt_omits_context_block_when_no_project_context(self):
        """project_context=None -> no localized phrase, no literal placeholder."""
        result = build_portfolio_chat_system_prompt([], lang="es", project_context=None)
        assert "El visitante está viendo" not in result
        assert "The visitor is currently viewing" not in result
        assert "{project_context}" not in result

    def test_portfolio_prompt_omits_context_block_when_default_arg(self):
        """Omitting project_context (default None) behaves like passing None."""
        result = build_portfolio_chat_system_prompt([], lang="en")
        assert "The visitor is currently viewing" not in result
        assert "{project_context}" not in result

    def test_portfolio_prompt_preserves_retrieved_chunks_with_project_context(self):
        """project_context injection does not break the chunk substitution."""
        chunks = [
            Chunk(
                text="Contenido del proyecto.",
                source="/test/file.md",
                section_header="Intro",
                chunk_index=0,
                char_start=0,
                char_end=25,
                token_count=5,
            )
        ]
        result = build_portfolio_chat_system_prompt(
            chunks,
            lang="es",
            project_context={"slug": "proj-x", "title": "X"},
        )
        assert "Contenido del proyecto." in result
        assert "=== INFORMACIÓN RECUPERADA ===" in result
        assert "{retrieved_chunks_with_metadata}" not in result
        assert "{project_context}" not in result

    def test_legacy_build_chat_accepts_project_context_for_signature_parity(self):
        """The legacy build_chat_system_prompt accepts project_context for parity.

        The generic template has no {project_context} placeholder, so the
        argument is a no-op; passing it must not raise and must not inject
        a context phrase into the rendered output.
        """
        result = build_chat_system_prompt(
            [],
            lang="es",
            project_context={"slug": "proj-x", "title": "X"},
        )
        assert "El visitante está viendo" not in result
        assert "{project_context}" not in result
        # Existing substitution still works.
        assert "(No se recuperó ningún fragmento relevante.)" in result
