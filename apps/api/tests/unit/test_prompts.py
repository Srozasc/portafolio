"""Unit tests for backend.rag.prompts.

Covers:
  - Byte-for-byte pinning of SYSTEM_PROMPT_TEMPLATE against design doc §8.
  - build_chat_system_prompt() output structure.
"""

import unicodedata
from pathlib import Path

import pytest

from backend.rag.prompts import SYSTEM_PROMPT_TEMPLATE, build_chat_system_prompt
from backend.rag.chunker import Chunk


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
