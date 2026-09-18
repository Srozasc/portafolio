"""Markdown-aware chunker with tiktoken token counting.

Algorithm (design.md Decision 1):
  1. Strip BOM if present; normalise \\r\\n / \\r to \\n.
  2. Walk lines detecting ATX headings (^#{1,6}\\s).
  3. Group body lines under the most-recent heading into sections.
  4. For each section:
     - If token count <= chunk_size: emit one Chunk with heading prepended.
     - Else split by paragraph (\\n\\n), then by line,
       copying `overlap` tokens from the previous chunk's tail
       into the new chunk's head.
  5. Token counting: tiktoken.get_encoding("cl100k_base").encode(...)

Metadata per Chunk: text, source, section_header, chunk_index,
  char_start, char_end, token_count.
"""

from __future__ import annotations

import re
import tiktoken
from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    source: str
    section_header: str
    chunk_index: int
    char_start: int
    char_end: int
    token_count: int


# ---------------------------------------------------------------------------
# ATX heading regex: 1-6 # followed by space and non-empty text
# ---------------------------------------------------------------------------
_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")

# ---------------------------------------------------------------------------
# tiktoken encoder (cl100k_base — shared across calls for performance)
# ---------------------------------------------------------------------------
_encoder = tiktoken.get_encoding("cl100k_base")


def _token_count(text: str) -> int:
    """Return number of tokens in `text` using cl100k_base."""
    return len(_encoder.encode(text))


def _split_paragraphs(section_text: str) -> list[str]:
    """Split section into paragraphs on double newlines, dropping empty."""
    paras = section_text.split("\n\n")
    return [p.strip() for p in paras if p.strip()]


def _build_overlap_tail(words: list[str], max_tokens: int) -> tuple[list[str], int]:
    """Return (tail_words, tail_token_count) for overlap from the last words."""
    tail: list[str] = []
    count = 0
    for w in reversed(words):
        w_t = _token_count(w) + 1  # +1 for space separator
        if count + w_t <= max_tokens:
            tail.insert(0, w)
            count += w_t
        else:
            break
    # Remove trailing space token from count
    if tail and count > 0:
        count -= 1
    return tail, count


def chunk_markdown(
    text: str,
    *,
    source: str,
    chunk_size: int = 700,
    overlap: int = 150,
) -> list[Chunk]:
    """Markdown-aware splitter.

    Args:
        text: Raw markdown content.
        source: Absolute file path string (stored in Chunk.source).
        chunk_size: Max tokens per chunk (default 700).
        overlap: Token overlap between consecutive chunks (default 150).

    Returns:
        List of Chunk objects in document order.
    """
    if not text or not text.strip():
        return []

    # Step 1: Strip BOM
    if text.startswith("\ufeff"):
        text = text[1:]

    # Step 2: Normalise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines = text.split("\n")

    # Step 3: Build sections (heading -> body lines)
    # Each section: (heading_text, body_lines_without_heading)
    sections: list[tuple[str, list[str]]] = []
    current_header = "(sin encabezado)"
    current_body: list[str] = []

    for line in lines:
        m = _ATX_HEADING_RE.match(line)
        if m:
            # Flush previous section (only if it has body content)
            if current_body:
                sections.append((current_header, current_body))
                current_body = []
            current_header = m.group(2).strip()
        else:
            current_body.append(line)

    # Flush last section
    if current_body:
        sections.append((current_header, current_body))

    if not sections:
        return []

    # Step 4: For each section, emit chunk(s)
    chunks: list[Chunk] = []
    chunk_index = 0
    prev_tail_words: list[str] = []  # overlap words from previous chunk
    prev_tail_tok = 0

    for sec_header, body_lines in sections:
        # heading_line is the markdown heading line for this section
        heading_line = f"# {sec_header}" if sec_header != "(sin encabezado)" else ""

        # section body text (no heading line)
        sec_body = "\n".join(body_lines)
        sec_body_tokens = _token_count(sec_body)

        if sec_body_tokens == 0 and heading_line:
            # Section has heading but no body — emit empty section as single chunk
            heading_text = heading_line
            chunks.append(
                Chunk(
                    text=heading_text,
                    source=source,
                    section_header=sec_header,
                    chunk_index=chunk_index,
                    char_start=text.find(heading_text),
                    char_end=text.find(heading_text) + len(heading_text),
                    token_count=_token_count(heading_text),
                )
            )
            chunk_index += 1
            prev_tail_words = []
            prev_tail_tok = 0
            continue

        if sec_body_tokens <= chunk_size:
            # Single chunk — prepend heading if present
            if heading_line:
                chunk_text = heading_line + "\n" + sec_body
            else:
                chunk_text = sec_body

            if _token_count(chunk_text) <= chunk_size:
                # Whole section fits
                start = text.find(chunk_text)
                if start == -1:
                    start = 0
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        source=source,
                        section_header=sec_header,
                        chunk_index=chunk_index,
                        char_start=start,
                        char_end=start + len(chunk_text),
                        token_count=_token_count(chunk_text),
                    )
                )
                chunk_index += 1
                # Overlap tail = last `overlap` tokens of sec_body
                body_words = sec_body.split()
                prev_tail_words, prev_tail_tok = _build_overlap_tail(body_words, overlap)
                continue

            # Heading makes it exceed chunk_size — drop heading from body, split body
            if sec_body_tokens <= chunk_size:
                start = text.find(sec_body)
                if start == -1:
                    start = 0
                chunks.append(
                    Chunk(
                        text=sec_body,
                        source=source,
                        section_header=sec_header,
                        chunk_index=chunk_index,
                        char_start=start,
                        char_end=start + len(sec_body),
                        token_count=sec_body_tokens,
                    )
                )
                chunk_index += 1
                body_words = sec_body.split()
                prev_tail_words, prev_tail_tok = _build_overlap_tail(body_words, overlap)
            else:
                # Split the body (no heading)
                _chunks, prev_tail_words, prev_tail_tok = _split_section(
                    sec_body, sec_header, source, chunk_index,
                    overlap, text, prev_tail_words, prev_tail_tok
                )
                chunks.extend(_chunks)
                chunk_index += len(_chunks)
            continue

        # Section body exceeds chunk_size — split by paragraph then by line
        _chunks, prev_tail_words, prev_tail_tok = _split_section(
            sec_body, sec_header, source, chunk_index,
            overlap, text, prev_tail_words, prev_tail_tok
        )
        chunks.extend(_chunks)
        chunk_index += len(_chunks)

    # Step 5: Final pass — recompute exact char_start/char_end from original text
    if chunks:
        final: list[Chunk] = []
        pos = 0
        for i, c in enumerate(chunks):
            idx = text.find(c.text, pos)
            if idx == -1:
                start = pos
            else:
                start = idx
            end = start + len(c.text)
            pos = end
            final.append(
                Chunk(
                    text=c.text,
                    source=c.source,
                    section_header=c.section_header,
                    chunk_index=i,
                    char_start=start,
                    char_end=end,
                    token_count=c.token_count,
                )
            )
        return final

    return []


def _split_section(
    sec_body: str,
    sec_header: str,
    source: str,
    start_chunk_index: int,
    overlap: int,
    original_text: str,
    prev_tail_words: list[str],
    prev_tail_tok: int,
) -> tuple[list[Chunk], list[str], int]:
    """Split a section body into token-safe chunks with overlap.

    Returns (chunks, final_tail_words, final_tail_tok_count).
    """
    chunks: list[Chunk] = []
    paras = _split_paragraphs(sec_body)
    chunk_index = start_chunk_index
    tail_words = list(prev_tail_words)
    tail_tok = prev_tail_tok

    for para in paras:
        if not para:
            continue
        para_tok = _token_count(para)

        if para_tok <= 700:
            # Try fitting overlap + para
            if tail_tok > 0 and tail_words:
                overlap_text = " ".join(tail_words)
                if tail_tok + para_tok <= 700:
                    chunk_text = overlap_text + "\n" + para
                else:
                    # Truncate overlap to fit
                    available = 700 - para_tok
                    overlap_parts: list[str] = []
                    overlap_t = 0
                    for w in reversed(tail_words):
                        w_t = _token_count(w) + 1
                        if overlap_t + w_t <= available:
                            overlap_parts.insert(0, w)
                            overlap_t += w_t
                        else:
                            break
                    if overlap_parts:
                        overlap_t -= 1  # remove trailing space
                    overlap_text = " ".join(overlap_parts)
                    chunk_text = overlap_text + "\n" + para if overlap_parts else para
                tok_count = _token_count(chunk_text)
            else:
                chunk_text = para
                tok_count = para_tok

            start = original_text.find(chunk_text)
            if start == -1:
                start = 0
            chunks.append(
                Chunk(
                    text=chunk_text,
                    source=source,
                    section_header=sec_header,
                    chunk_index=chunk_index,
                    char_start=start,
                    char_end=start + len(chunk_text),
                    token_count=tok_count,
                )
            )
            chunk_index += 1
            # Update tail from para
            para_words = para.split()
            tail_words, tail_tok = _build_overlap_tail(para_words, overlap)
        else:
            # Split by line
            lines = para.split("\n")
            current_lines: list[str] = []
            current_tok = 0

            for line in lines:
                line_tok = _token_count(line)
                if line_tok > 700:
                    # Flush current
                    if current_lines:
                        flush_text = "\n".join(current_lines)
                        flush_tok = current_tok
                        # Apply overlap
                        if tail_tok > 0 and tail_words:
                            ov = " ".join(tail_words)
                            if tail_tok + flush_tok <= 700:
                                flush_text = ov + "\n" + flush_text
                                flush_tok = _token_count(flush_text)
                            else:
                                # Truncate overlap
                                available = 700 - flush_tok
                                op: list[str] = []
                                ot = 0
                                for w in reversed(tail_words):
                                    wt = _token_count(w) + 1
                                    if ot + wt <= available:
                                        op.insert(0, w)
                                        ot += wt
                                    else:
                                        break
                                if op:
                                    ot -= 1
                                ov2 = " ".join(op)
                                flush_text = ov2 + "\n" + flush_text
                                flush_tok = _token_count(flush_text)
                        start = original_text.find(flush_text)
                        if start == -1:
                            start = 0
                        chunks.append(
                            Chunk(
                                text=flush_text,
                                source=source,
                                section_header=sec_header,
                                chunk_index=chunk_index,
                                char_start=start,
                                char_end=start + len(flush_text),
                                token_count=flush_tok,
                            )
                        )
                        chunk_index += 1
                        tail_words, tail_tok = _build_overlap_tail(flush_text.split(), overlap)
                        current_lines = []
                        current_tok = 0

                    # Split the long line by words
                    words = line.split()
                    word_chunk_lines: list[str] = []
                    word_chunk_tok = 0
                    for word in words:
                        w_t = _token_count(word)
                        if word_chunk_tok + w_t + 1 <= 700:
                            word_chunk_lines.append(word)
                            word_chunk_tok += w_t + 1
                        else:
                            if word_chunk_lines:
                                wc_text = " ".join(word_chunk_lines)
                                if tail_tok > 0 and tail_words:
                                    ov = " ".join(tail_words)
                                    if tail_tok + word_chunk_tok <= 700:
                                        wc_text = ov + "\n" + wc_text
                                        word_chunk_tok = _token_count(wc_text)
                                    else:
                                        available = 700 - word_chunk_tok
                                        op = []
                                        ot = 0
                                        for w in reversed(tail_words):
                                            wt = _token_count(w) + 1
                                            if ot + wt <= available:
                                                op.insert(0, w)
                                                ot += wt
                                            else:
                                                break
                                        if op:
                                            ot -= 1
                                        ov3 = " ".join(op)
                                        wc_text = ov3 + "\n" + wc_text
                                        word_chunk_tok = _token_count(wc_text)
                                start = original_text.find(wc_text)
                                if start == -1:
                                    start = 0
                                chunks.append(
                                    Chunk(
                                        text=wc_text,
                                        source=source,
                                        section_header=sec_header,
                                        chunk_index=chunk_index,
                                        char_start=start,
                                        char_end=start + len(wc_text),
                                        token_count=word_chunk_tok,
                                    )
                                )
                                chunk_index += 1
                                tail_words, tail_tok = _build_overlap_tail(wc_text.split(), overlap)
                            word_chunk_lines = [word]
                            word_chunk_tok = w_t + 1
                    # Flush remaining word chunk
                    if word_chunk_lines:
                        wc_text = " ".join(word_chunk_lines)
                        if tail_tok > 0 and tail_words:
                            ov = " ".join(tail_words)
                            if tail_tok + word_chunk_tok <= 700:
                                wc_text = ov + "\n" + wc_text
                                word_chunk_tok = _token_count(wc_text)
                            else:
                                available = 700 - word_chunk_tok
                                op = []
                                ot = 0
                                for w in reversed(tail_words):
                                    wt = _token_count(w) + 1
                                    if ot + wt <= available:
                                        op.insert(0, w)
                                        ot += wt
                                    else:
                                        break
                                if op:
                                    ot -= 1
                                ov4 = " ".join(op)
                                wc_text = ov4 + "\n" + wc_text
                                word_chunk_tok = _token_count(wc_text)
                        start = original_text.find(wc_text)
                        if start == -1:
                            start = 0
                        chunks.append(
                            Chunk(
                                text=wc_text,
                                source=source,
                                section_header=sec_header,
                                chunk_index=chunk_index,
                                char_start=start,
                                char_end=start + len(wc_text),
                                token_count=word_chunk_tok,
                            )
                        )
                        chunk_index += 1
                        tail_words, tail_tok = _build_overlap_tail(wc_text.split(), overlap)
                elif current_tok + line_tok + 1 <= 700:
                    current_lines.append(line)
                    current_tok += line_tok + 1
                else:
                    # Flush current, start new
                    flush_text = "\n".join(current_lines)
                    flush_tok = current_tok
                    if tail_tok > 0 and tail_words:
                        ov = " ".join(tail_words)
                        if tail_tok + flush_tok <= 700:
                            flush_text = ov + "\n" + flush_text
                            flush_tok = _token_count(flush_text)
                        else:
                            available = 700 - flush_tok
                            op = []
                            ot = 0
                            for w in reversed(tail_words):
                                wt = _token_count(w) + 1
                                if ot + wt <= available:
                                    op.insert(0, w)
                                    ot += wt
                                else:
                                    break
                            if op:
                                ot -= 1
                            ov5 = " ".join(op)
                            flush_text = ov5 + "\n" + flush_text
                            flush_tok = _token_count(flush_text)
                    start = original_text.find(flush_text)
                    if start == -1:
                        start = 0
                    chunks.append(
                        Chunk(
                            text=flush_text,
                            source=source,
                            section_header=sec_header,
                            chunk_index=chunk_index,
                            char_start=start,
                            char_end=start + len(flush_text),
                            token_count=flush_tok,
                        )
                    )
                    chunk_index += 1
                    tail_words, tail_tok = _build_overlap_tail(flush_text.split(), overlap)
                    current_lines = [line]
                    current_tok = line_tok + 1

            # Flush remaining
            if current_lines:
                flush_text = "\n".join(current_lines)
                flush_tok = current_tok
                if tail_tok > 0 and tail_words:
                    ov = " ".join(tail_words)
                    if tail_tok + flush_tok <= 700:
                        flush_text = ov + "\n" + flush_text
                        flush_tok = _token_count(flush_text)
                    else:
                        available = 700 - flush_tok
                        op = []
                        ot = 0
                        for w in reversed(tail_words):
                            wt = _token_count(w) + 1
                            if ot + wt <= available:
                                op.insert(0, w)
                                ot += wt
                            else:
                                break
                        if op:
                            ot -= 1
                        ov6 = " ".join(op)
                        flush_text = ov6 + "\n" + flush_text
                        flush_tok = _token_count(flush_text)
                start = original_text.find(flush_text)
                if start == -1:
                    start = 0
                chunks.append(
                    Chunk(
                        text=flush_text,
                        source=source,
                        section_header=sec_header,
                        chunk_index=chunk_index,
                        char_start=start,
                        char_end=start + len(flush_text),
                        token_count=flush_tok,
                    )
                )
                chunk_index += 1
                tail_words, tail_tok = _build_overlap_tail(flush_text.split(), overlap)

    return chunks, tail_words, tail_tok
