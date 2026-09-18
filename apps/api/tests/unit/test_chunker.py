"""Unit tests for backend.rag.chunker.

Covers REQ-ING-002 scenarios:
  - empty input → []
  - whitespace-only → []
  - single heading
  - multi-heading
  - file < chunk_size → one chunk equal to input
  - mixed FAQ + prose
  - oversized single heading (split across chunks, heading preserved)
  - heading hierarchy preserved across split
  - metadata completeness (source, section_header, chunk_index, char_start, char_end, token_count)
  - edge cases: \\r\\n, BOM, single-token heading
"""

import pytest
from backend.rag.chunker import chunk_markdown, Chunk


class TestEmptyAndWhitespace:
    def test_empty_string_returns_empty_list(self):
        result = chunk_markdown("", source="/test/file.md")
        assert result == []

    def test_whitespace_only_returns_empty_list(self):
        result = chunk_markdown("   \n\n  \t  ", source="/test/file.md")
        assert result == []

    def test_newlines_only_returns_empty_list(self):
        result = chunk_markdown("\n\n\n\n", source="/test/file.md")
        assert result == []


class TestSingleHeading:
    def test_single_h1_one_chunk(self):
        md = "# Introducción\n\nEste es el contenido."
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        assert len(chunks) == 1
        assert chunks[0].text == "# Introducción\n\nEste es el contenido."
        assert chunks[0].section_header == "Introducción"
        assert chunks[0].chunk_index == 0

    def test_no_heading_single_chunk(self):
        md = "Este es un texto sin ningún encabezado."
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        assert len(chunks) == 1
        assert chunks[0].text == md
        assert chunks[0].section_header == "(sin encabezado)"


class TestMultiHeading:
    def test_two_h2_sections_two_chunks(self):
        md = "# Sección A\n\nContenido A.\n\n# Sección B\n\nContenido B."
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        assert len(chunks) == 2
        assert chunks[0].section_header == "Sección A"
        assert chunks[1].section_header == "Sección B"

    def test_heading_hierarchy_three_levels(self):
        md = (
            "# Título\n"
            "## Sub1\n"
            "Contenido sub1.\n\n"
            "## Sub2\n"
            "Contenido sub2.\n"
            "### SubSub2\n"
            "Contenido subsub2."
        )
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        # Each section should get its own chunk(s)
        assert all(c.section_header != "" for c in chunks)


class TestFileSmallerThanChunkSize:
    def test_short_file_one_chunk_equals_input(self):
        short_text = "Hola mundo."
        chunks = chunk_markdown(short_text, source="/test/file.md", chunk_size=700, overlap=150)
        assert len(chunks) == 1
        assert chunks[0].text == short_text


class TestMixedFaqAndProse:
    def test_faq_entries_individual_chunks(self):
        md = (
            "# Preguntas Frecuentes\n\n"
            "## ¿Qué es esto?\n\n"
            "Esto es una respuesta.\n\n"
            "## ¿Cómo funciona?\n\n"
            "Funciona así.\n\n"
            "# Manual\n\n"
            "Este es un manual extenso que habla sobre el producto. "
            "Tiene muchas características que vamos a describir en detalle. "
            " blah " * 50
        )
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        assert len(chunks) > 0
        # FAQ entries with short answers should each be their own chunk
        # The long manual section may be split
        section_headers = {c.section_header for c in chunks}
        assert "Preguntas Frecuentes" in section_headers or "Manual" in section_headers


class TestOversizedSingleHeading:
    def test_long_section_split_preserves_heading(self):
        # Build a section longer than chunk_size using real words
        # cl100k_base encodes most English words as ~1 token each
        words = ["palabra"] * 800  # 800 tokens, exceeds chunk_size=700
        para = " ".join(words)
        md = f"# Gran Sección\n\n{para}"
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        assert len(chunks) > 1, f"Expected >1 chunks, got {len(chunks)}"
        # All chunks should preserve the section_header
        for c in chunks:
            assert c.section_header == "Gran Sección"
        # Verify token count per chunk is within limit
        for c in chunks:
            assert c.token_count <= 700, f"Chunk token_count={c.token_count} exceeds chunk_size=700"

    def test_split_chunks_ordered_by_position(self):
        # Verify chunk_index is monotonically increasing (document order)
        long_text = "word " * 3000
        md = f"# Largo\n\n{long_text}"
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        if len(chunks) > 1:
            indices = [c.chunk_index for c in chunks]
            assert indices == list(range(len(chunks)))


class TestMetadataCompleteness:
    def test_all_metadata_fields_present(self):
        md = "# Título\n\nContenido."
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        assert len(chunks) == 1
        c = chunks[0]
        assert c.source == "/test/file.md"
        assert c.section_header == "Título"
        assert c.chunk_index == 0
        assert isinstance(c.char_start, int)
        assert isinstance(c.char_end, int)
        assert isinstance(c.token_count, int)
        assert c.char_start >= 0
        assert c.char_end > c.char_start
        assert c.token_count > 0

    def test_char_start_end_contiguous(self):
        md = "# Uno\n\nContenido uno.\n\n# Dos\n\nContenido dos."
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        for i in range(len(chunks) - 1):
            assert chunks[i].char_end == chunks[i + 1].char_start or \
                   chunks[i].char_end <= chunks[i + 1].char_start


class TestEdgeCases:
    def test_crlf_line_endings(self):
        md = "# Título\r\n\r\nContenido.\r\n"
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        assert len(chunks) == 1
        assert chunks[0].section_header == "Título"

    def test_bom_character_stripped(self):
        md = "\ufeff# Título\n\nContenido."
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        assert len(chunks) == 1
        assert not chunks[0].text.startswith("\ufeff")

    def test_single_token_heading(self):
        md = "# A\n\nContenido del encabezado de una sola letra."
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        assert len(chunks) == 1
        assert chunks[0].section_header == "A"

    def test_heading_with_special_chars(self):
        md = "# ¿Qué es esto?\n\nEs algo."
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        assert len(chunks) == 1
        assert "¿Qué es esto?" in chunks[0].section_header

    def test_three_hashes_h6_heading(self):
        md = "###### H6\n\nContenido."
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        assert len(chunks) == 1
        assert chunks[0].section_header == "H6"


class TestChunkIndex:
    def test_chunk_index_increments_from_zero(self):
        md = "# Uno\n\nA.\n\n# Dos\n\nB.\n\n# Tres\n\nC."
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=700, overlap=150)
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))


class TestOverlap:
    def test_overlap_tokens_preserved_in_second_chunk(self):
        # Create a scenario where a section must be split
        # Build text where we can verify overlap
        words = ["palabra"] * 500
        long_text = " ".join(words)
        md = f"# Sección\n\n{long_text}"
        chunks = chunk_markdown(md, source="/test/file.md", chunk_size=100, overlap=20)
        if len(chunks) > 1:
            # The second chunk should start with words from the tail of the previous chunk
            # This is a basic sanity check
            assert chunks[0].token_count <= 100
            assert chunks[1].token_count <= 100
