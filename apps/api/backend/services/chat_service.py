"""Chat service: retrieve -> deflection-or-build-prompt -> stream.

Design: design.md Decision 3 / Module APIs / WU 2.2.
Orchestrates: collection resolution -> Retriever -> (deflection | LLM stream).
The central REQ-CHS-004 assertion is that `llm.stream_chat` is NEVER called
when the retriever returns zero hits above threshold.
"""

from __future__ import annotations

from typing import Iterator, NamedTuple

from backend.rag.llm_client import LLMClient, StreamError
from backend.rag.prompts import build_chat_system_prompt
from backend.rag.retriever import Retriever


# ---------------------------------------------------------------------------
# Stream event types (mirrors backend.api.schemas.StreamEvent for Phase 2)
# ---------------------------------------------------------------------------


class StreamEvent(dict):
    """SSE event payload shape.

    Three variants discriminated by the `type` field:
      - content: {"type": "content", "text": "<token delta>"}
      - done:    {"type": "done"}
      - error:   {"type": "error", "error": "<CODE>", "message": "<sanitised>"}

    Phase 3 will replace this with an import from backend.api.schemas.
    """

    pass


# ---------------------------------------------------------------------------
# Chunk-like adapter for build_chat_system_prompt
# ---------------------------------------------------------------------------


class _ChunkFromHit(NamedTuple):
    """Duck-types a Chunk for build_chat_system_prompt from a Hit."""

    section_header: str
    text: str


# ---------------------------------------------------------------------------
# Sentinel deflection text (locked per design doc §8 + AGENTS.md)
# ---------------------------------------------------------------------------

_DEFLECTION_TEXT = "No tengo información sobre eso."


# ---------------------------------------------------------------------------
# StreamEvent constructors
# ---------------------------------------------------------------------------


def _content(text: str) -> StreamEvent:
    return StreamEvent(type="content", text=text)


def _done() -> StreamEvent:
    return StreamEvent(type="done")


def _error(code: str, message: str) -> StreamEvent:
    return StreamEvent(type="error", error=code, message=message)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ChatService:
    """Orchestrates retrieval + streaming LLM response with deflection short-circuit."""

    def __init__(self, retriever: Retriever, llm: LLMClient) -> None:
        """Initialise the chat service.

        Args:
            retriever: Retriever instance for ChromaDB lookups.
            llm: LLMClient instance for streaming chat completions.
        """
        self._retriever = retriever
        self._llm = llm

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    @property
    def retriever(self) -> Retriever:
        """Expose retriever for diagnostic endpoints (read-only access)."""
        return self._retriever

    def stream_answer(
        self,
        question: str,
        collection: str | None,
    ) -> Iterator[StreamEvent]:
        """Stream an answer to the user's question.

        Algorithm:
          1. Resolve `collection` (explicit, single existing, or error).
          2. Retrieve top-K chunks above threshold via `self._retriever`.
          3. If hits is empty → yield deflection + done (NO LLM call).
          4. Else build system prompt from hits and stream LLM tokens.
          5. On StreamError: yield error event + done (no exception propagates).
          6. Always yield `done` sentinel via try/finally.

        Args:
            question: User's question string.
            collection: Explicit collection name, or None to auto-resolve.

        Yields:
            StreamEvent dicts (content / error / done).
        """
        # --- Step 1: resolve collection ---
        resolved, errors = self._resolve_collection(collection)
        if errors:
            yield from errors
            yield _done()
            return
        assert resolved is not None

        # --- Step 2: retrieve ---
        hits = self._retriever.retrieve(question, resolved)

        # --- Step 3: deflection short-circuit (REQ-CHS-004) ---
        if not hits:
            yield _content(_DEFLECTION_TEXT)
            yield _done()
            return

        # --- Step 4: build prompt from hits and stream LLM ---
        chunks_for_prompt = [
            _ChunkFromHit(
                section_header=h.metadata.get("section_header", ""),
                text=h.text,
            )
            for h in hits
        ]
        system_prompt = build_chat_system_prompt(chunks_for_prompt)

        # Stream tokens with error handling — always yields done
        yield from self._stream_with_error_handling(system_prompt, question)

    # ---------------------------------------------------------------------------
    # Private helpers
    # ---------------------------------------------------------------------------

    def _resolve_collection(
        self, collection: str | None
    ) -> tuple[str | None, list[StreamEvent]]:
        """Resolve the collection name.

        Returns (collection_name, error_events). error_events is non-empty
        when a validation error occurred; the caller must yield them and return.
        """
        # Access the store through the retriever (avoids circular import)
        store = self._retriever._store  # noqa: SLF001

        try:
            existing = store.list_collections()
        except Exception:
            return (None, [_error("VECTOR_STORE_ERROR", "VECTOR_STORE_ERROR")])

        if collection is not None:
            # Explicit name provided
            if collection not in existing:
                return (None, [_error("UNKNOWN_COLLECTION", "UNKNOWN_COLLECTION")])
            return (collection, [])

        # No override — must be exactly one existing collection
        if len(existing) == 0:
            return (None, [_error("UNKNOWN_COLLECTION", "UNKNOWN_COLLECTION")])
        if len(existing) > 1:
            return (None, [_error("AMBIGUOUS_COLLECTION", "AMBIGUOUS_COLLECTION")])
        return (existing[0], [])

    def _stream_with_error_handling(
        self, system: str, user: str
    ) -> Iterator[StreamEvent]:
        """Wrap llm.stream_chat with StreamError -> SSE error event handling.

        Always yields exactly one `done` sentinel, even if the consumer
        breaks early or the LLM raises mid-stream.

        Strips <think>...</think> reasoning blocks from the LLM output
        (some models emit them despite the system prompt forbidding
        them). The strategy:

        - We maintain a small "holdback" of up to `open_len - 1` chars
          that could still become the start of `<think>`.
        - When the buffer grows beyond that, we flush everything that
          cannot be the start of the tag, keeping only the last few
          chars back.
        - When `<think>` is detected, we drop everything up to (and
          including) the closing tag.
        - If the stream ends mid-think-block (LLM forgot to close), the
          buffered content is dropped silently rather than leaked.

        Note: text without `<` is forwarded with zero fragmentation —
        the holdback only activates around potential tag openers.
        """
        try:
            think_open = "<think>"
            think_close = "</think>"
            open_len = len(think_open)
            keep_back = open_len - 1  # max chars that could still form <think>
            holdback = ""  # content kept back as potential tag prefix
            inside_think = False

            def emit(text: str):
                if text:
                    yield _content(text)  # type: ignore[misc]

            for token in self._llm.stream_chat(system, user):
                if inside_think:
                    close_idx = token.find(think_close)
                    if close_idx >= 0:
                        token = token[close_idx + len(think_close):]
                        inside_think = False
                        holdback = ""
                        if not token:
                            continue
                    else:
                        continue

                combined = holdback + token

                if think_open in combined:
                    # Found the opening tag — flush content before it,
                    # then drop everything from the tag up to close.
                    open_idx = combined.find(think_open)
                    if open_idx > 0:
                        yield _content(combined[:open_idx])
                    rest = combined[open_idx + open_len:]
                    close_idx = rest.find(think_close)
                    if close_idx >= 0:
                        # Close tag also present — skip past it.
                        token = rest[close_idx + len(think_close):]
                        holdback = ""
                        if token:
                            yield _content(token)
                    else:
                        # No close yet — enter think mode.
                        inside_think = True
                        holdback = ""
                    continue

                # No complete <think> in `combined`. Buffer behaviour
                # depends on whether `<` is present:
                #
                # - No `<` anywhere: safe to forward everything, no
                #   fragmentation.
                # - `<` present: hold back a trailing window of
                #   `keep_back` chars (the last `<` plus everything
                #   after it) so we can detect a tag opener that
                #   spans token boundaries.
                if "<" not in combined:
                    if combined:
                        yield _content(combined)
                    holdback = ""
                elif len(combined) > keep_back:
                    # Find the last `<` and emit everything before it.
                    last_lt = combined.rfind("<")
                    # We need to keep the last `<` plus at most keep_back-1
                    # chars after it as the new holdback window.
                    flush_end = max(last_lt, len(combined) - keep_back)
                    flush = combined[:flush_end]
                    holdback = combined[flush_end:]
                    if flush:
                        yield _content(flush)
                else:
                    holdback = combined

            # End-of-stream: flush holdback unless inside an unclosed think.
            if holdback and not inside_think:
                yield _content(holdback)
        except StreamError as exc:
            # Sanitised: class name only (no URLs, body fragments, etc.)
            # Full exception is preserved on __cause__ for server-side logging.
            yield _error("LLM_ERROR", type(exc).__name__)
        finally:
            yield _done()
