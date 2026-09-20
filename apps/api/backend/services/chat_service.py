"""Chat service: retrieve -> deflection-or-build-prompt -> stream.

Design: design.md Decision 3 / Module APIs / WU 2.2.
Orchestrates: collection resolution -> Retriever -> (deflection | LLM stream).
The central REQ-CHS-004 assertion is that `llm.stream_chat` is NEVER called
when the retriever returns zero hits above threshold.

Phase 3 extends the service with ``chat_projects_stream`` for the
projects-aware router (LIST / DETAIL / GENERAL). The legacy
``stream_answer`` path is preserved unchanged.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import NamedTuple

from backend.rag.llm_client import LLMClient, StreamError
from backend.rag.prompts import build_chat_system_prompt, build_portfolio_chat_system_prompt
from backend.rag.project_router import ProjectRouter, RouteKind
from backend.rag.query_expansion import expand_query
from backend.rag.retriever import Retriever
from backend.rag.vector_store import Hit, VectorStore
from backend.services.projects_service import ProjectsService


# ---------------------------------------------------------------------------
# Stream event types (mirrors backend.api.schemas.StreamEvent for Phase 2)
# ---------------------------------------------------------------------------


class StreamEvent(dict):
    """SSE event payload shape.

    Phase 1 variants (existing):
      - content: {"type": "content", "text": "<token delta>"}
      - done:    {"type": "done"}
      - error:   {"type": "error", "error": "<CODE>", "message": "<sanitised>"}

    Phase 3 additions:
      - projects:{"type": "projects", "items": [{"slug", "title", "summary", "relevance"}, ...]}
    """


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
# Phase 3: projects JSON block parsing
# ---------------------------------------------------------------------------

PROJECTS_BLOCK_RE = re.compile(
    r"===PROJECTS===\s*(\[.*?\])\s*===END===",
    re.DOTALL,
)


def _extract_projects_block(prose: str) -> list[dict] | None:
    """Parse a trailing ===PROJECTS=== JSON block from `prose`.

    Returns the parsed JSON array of project items, or None if the block
    is missing or malformed. The block is delimited EXACTLY as:
        ===PROJECTS===
        [{"slug": "...", ...}]
        ===END===

    Non-list payloads (e.g. an object instead of an array) also return None.
    """
    if not prose:
        return None
    match = PROJECTS_BLOCK_RE.search(prose)
    if not match:
        return None
    try:
        items = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(items, list):
        return None
    return items


# ---------------------------------------------------------------------------
# StreamEvent constructors
# ---------------------------------------------------------------------------


def _content(text: str) -> StreamEvent:
    return StreamEvent(type="content", text=text)


def _done() -> StreamEvent:
    return StreamEvent(type="done")


def _error(code: str, message: str) -> StreamEvent:
    return StreamEvent(type="error", error=code, message=message)


def _projects(items: list[dict]) -> StreamEvent:
    return StreamEvent(type="projects", items=items)


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
    # Phase 3 public API: project-aware streaming
    # ---------------------------------------------------------------------------

    def chat_projects_stream(
        self,
        *,
        question: str,
        lang: str = "es",
        history: list[dict] | None = None,
        session_id: str | None = None,
        project_slug: str | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream a project-aware answer (Phase 3 router).

        Algorithm:
          1. Discover known project slugs from the ChromaDB store
             (collections matching `projects_*` minus `projects_index`).
          2. Build a ProjectRouter with the known slugs.
          3. Classify the question -> RouteDecision (LIST / DETAIL / GENERAL).
             The optional ``project_slug`` is forwarded as
             ``current_project_slug`` so the router defaults to DETAIL on
             that project when the question is ambiguous.
          4. Resolve the source collection:
             - DETAIL: `projects_<slug>` (per-project body chunks)
             - LIST or GENERAL: `projects_index` (master one-per-project)
          5. Embed + query the collection. Threshold 0.0 so we don't
             accidentally drop the index's own matches.
          6. Build the system prompt from the hits (prepending a project
             context block if ``project_slug`` was provided) and prepend a
             history window (last 6 turns) to the user message.
          7. Stream the LLM, accumulating prose to parse the trailing
             ===PROJECTS=== JSON block at the end.
          8. Emit a `projects` event with the resolved card items, then `done`.

        Args:
            question: User's question (non-empty).
            lang: "es" (default) or "en" — selects the system prompt template.
            history: Optional list of {"role": "user"|"assistant", "content": "..."}
                of recent turns (most recent last). Used for pronoun resolution
                in DETAIL intent and prepended to the LLM message.
            session_id: Optional client-provided session id (currently unused).
            project_slug: Optional slug of the project the visitor is currently
                viewing (Phase 5.5 project-aware chat bubble). When provided
                AND in the discovered known slugs, the router uses it as a
                fallback hint for ambiguous questions and the system prompt
                includes a "current context" block telling the LLM to default
                to that project.

        Yields:
            StreamEvent dicts: content / projects / done / error.
        """
        # Local access (avoids circular import / exposes internals via the same
        # pattern the legacy code uses).
        store: VectorStore = self._retriever._store  # noqa: SLF001
        embedder = self._retriever._embedder

        # 1. Discover known slugs
        known_slugs = self._discover_project_slugs(store)
        known_slugs_set = set(known_slugs)

        # 2. Build router
        router = ProjectRouter(known_slugs)

        # 3. Route (history is already a list[dict] | None). The
        #    project_slug is forwarded as a router hint; if it's None or
        #    not in known_slugs the router ignores it and falls through
        #    to GENERAL as before.
        decision = router.route(
            question,
            history,
            current_project_slug=project_slug,
        )

        # 4. Resolve source collection + retrieval top_k
        history_list = history or []
        if decision.kind == RouteKind.DETAIL_PROJECT:
            assert decision.slug is not None
            # Inline ProjectsService.detail_collection_name(slug) — the
            # implementation only formats the name (no instance state needed),
            # so we avoid constructing a ProjectsService here.
            collection = f"{ProjectsService.DETAIL_COLLECTION_PREFIX}_{decision.slug}"
            top_k = 4
            forced_slug = decision.slug
        else:
            # LIST_PROJECTS and GENERAL both query the master index.
            collection = ProjectsService.INDEX_COLLECTION
            top_k = 10  # was 6; bumped to give short-query expansion more headroom
            forced_slug = None

        # 5. Retrieve chunks (short queries get keyword-expanded first so the
        #    OpenAI embedder has enough context to match chunks — see
        #    backend.rag.query_expansion).
        expanded_question = expand_query(question)
        try:
            hits = self._query_store(
                store=store,
                embedder=embedder,
                question=expanded_question,
                collection=collection,
                top_k=top_k,
                threshold=self._retriever.threshold,
            )
        except Exception:
            yield _error("VECTOR_STORE_ERROR", "VECTOR_STORE_ERROR")
            yield _done()
            return

        # 6. Build the system prompt from the hits (bilingual). If the
        #    caller passed a project_slug that is in known_slugs, also
        #    inject a "current context" block telling the LLM to default
        #    to that project on ambiguous questions. The title is looked
        #    up from the index metadata when a hit happens to be the
        #    matching slug's entry; otherwise we fall back to the slug
        #    itself (DETAIL routes query a detail collection that may
        #    not carry the title field, so this is the safe default).
        chunks_for_prompt = [
            _ChunkFromHit(
                section_header=h.metadata.get("section_header", ""),
                text=h.text,
            )
            for h in hits
        ]
        project_context: dict | None = None
        if project_slug and project_slug in known_slugs_set:
            title_field = "title_en" if lang == "en" else "title_es"
            resolved_title: str | None = None
            for h in hits:
                if h.metadata.get("slug") == project_slug:
                    resolved_title = (
                        h.metadata.get(title_field)
                        or h.metadata.get("title_es")
                        or None
                    )
                    break
            project_context = {
                "slug": project_slug,
                "title": resolved_title or project_slug,
            }
        system_prompt = build_portfolio_chat_system_prompt(
            chunks_for_prompt,
            lang=lang,
            project_context=project_context,
        )

        # 7. Build the user message with history (last 6 turns).
        user_message = self._build_user_with_history(
            question=question,
            history=history_list,
            max_turns=6,
        )

        # 8. Stream the LLM, accumulating prose and buffering the optional
        #    ===PROJECTS=== ... ===END=== JSON block so it never reaches the
        #    visitor's screen. The LLM is instructed to emit the block at the
        #    END of its response; we let the visible prose stream through
        #    normally and flush only up to the marker, then stop yielding
        #    content chunks (the cards are surfaced via the `projects` SSE
        #    event instead).
        raw_prose_parts: list[str] = []
        has_error = False
        flushed_chars = 0  # chars of `raw_prose_parts` already streamed to client
        block_consumed = False

        for event in self._stream_with_error_handling(
            system=system_prompt,
            user=user_message,
        ):
            if event.get("type") == "content":
                text = event.get("text", "")
                raw_prose_parts.append(text)
                accumulated = "".join(raw_prose_parts)
                if not block_consumed and "===PROJECTS===" in accumulated:
                    # Marker just appeared. Flush the visible prose up to the
                    # marker (anything after is the JSON block — discard).
                    visible = accumulated.split("===PROJECTS===", 1)[0]
                    tail = visible[flushed_chars:]
                    if tail:
                        yield _content(tail)
                    flushed_chars = len(visible)
                    block_consumed = True
                elif not block_consumed:
                    # No marker yet — stream the chunk through.
                    yield event
                    flushed_chars += len(text)
                # If block_consumed: drop the chunk silently.
            elif event.get("type") == "error":
                yield event
                has_error = True
                break
            elif event.get("type") == "done":
                # Don't forward the inner done; we emit our own after projects.
                break

        if has_error:
            yield _done()
            return

        # 9. Parse the projects JSON block from the accumulated prose.
        full_prose = "".join(raw_prose_parts)
        llm_items = _extract_projects_block(full_prose)

        # 10. Build the project cards.
        cards = _build_project_cards(
            llm_items=llm_items,
            hits=hits,
            lang=lang,
            forced_slug=forced_slug,
            known_slugs=set(known_slugs),
        )

        if cards:
            yield _projects(cards)

        yield _done()

    # ---------------------------------------------------------------------------
    # Phase 3 helpers
    # ---------------------------------------------------------------------------

    @staticmethod
    def _discover_project_slugs(store: VectorStore) -> list[str]:
        """Return project slugs found in ChromaDB collections.

        Convention: detail collections are named ``projects_<slug>``; the
        master collection ``projects_index`` is excluded. We extract the
        slug after the ``projects_`` prefix and validate it matches the
        Phase 1 slug pattern (``proj-<...>``).
        """
        prefix = ProjectsService.DETAIL_COLLECTION_PREFIX + "_"
        index_name = ProjectsService.INDEX_COLLECTION
        slugs: list[str] = []
        for name in store.list_collections():
            if name == index_name:
                continue
            if not name.startswith(prefix):
                continue
            slug = name[len(prefix):]
            # Validate slug shape (defensive — the indexer already enforces this).
            if re.fullmatch(r"proj-[a-z0-9-]+", slug):
                slugs.append(slug)
        return slugs

    @staticmethod
    def _query_store(
        *,
        store: VectorStore,
        embedder,
        question: str,
        collection: str,
        top_k: int,
        threshold: float,
    ) -> list[Hit]:
        """Embed `question` and query `collection`, returning hits above `threshold`.

        Returns an empty list if the collection does not exist (ChromaDB
        raises ValueError on unknown collection). Any other exception is
        re-raised so the caller can emit a VECTOR_STORE_ERROR.
        """
        try:
            embedding = embedder.embed([question])[0]
        except Exception:
            raise

        try:
            return store.query(
                name=collection,
                embedding=embedding,
                top_k=top_k,
                threshold=threshold,
            )
        except ValueError:
            # Unknown collection -> empty hit list (caller may still try
            # to emit something or treat as no-hits).
            return []

    @staticmethod
    def _build_user_with_history(
        *,
        question: str,
        history: list[dict],
        max_turns: int,
    ) -> str:
        """Build the LLM user message by prepending the last `max_turns` turns.

        Format:
            <history as a transcript, oldest first>
            ---
            Current question: <question>

        The transcript uses simple "User:" / "Assistant:" labels. If a turn
        has a non-string or missing content, it is skipped silently.
        """
        recent = history[-max_turns:] if history else []
        parts: list[str] = []
        for turn in recent:
            if not isinstance(turn, dict):
                continue
            role = turn.get("role")
            content = turn.get("content", "")
            if not isinstance(content, str) or not content.strip():
                continue
            if role == "user":
                parts.append(f"User: {content.strip()}")
            elif role == "assistant":
                parts.append(f"Assistant: {content.strip()}")

        if parts:
            transcript = "\n".join(parts)
            return f"{transcript}\n---\nCurrent question: {question}"
        return question

    # ---------------------------------------------------------------------------
    # Legacy private helpers (kept for stream_answer)
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


# ---------------------------------------------------------------------------
# Module-level helpers (used by chat_projects_stream + tests)
# ---------------------------------------------------------------------------


def _build_project_cards(
    *,
    llm_items: list[dict] | None,
    hits: list[Hit],
    lang: str,
    forced_slug: str | None,
    known_slugs: set[str],
) -> list[dict]:
    """Build the cards for the SSE `projects` event.

    Priority:
      1. If `forced_slug` (DETAIL route): always emit exactly one card for
         that slug with relevance=1.0; metadata is pulled from the first
         matching index hit (if available) or from the detail chunk itself.
      2. If the LLM emitted a parseable ===PROJECTS=== JSON block, use
         those items (filtered to known_slugs; invalid shapes dropped).
      3. Otherwise, fall back to the top-N `hits` (LIST/GENERAL): build
         cards from the index metadata with relevance = hit.score.

    Cards are dicts ready for the SSE payload:
        {"slug": str, "title": str, "summary": str, "relevance": float}
    """
    title_field = "title_en" if lang == "en" else "title_es"
    summary_field = "summary_en" if lang == "en" else "summary_es"

    # 1. Forced slug (DETAIL route)
    if forced_slug is not None:
        # Build title/summary from the hits metadata (which is index metadata
        # if we routed through it, or use a slug-only fallback otherwise).
        title = forced_slug
        summary = ""
        for h in hits:
            if h.metadata.get("slug") == forced_slug:
                title = h.metadata.get(title_field) or h.metadata.get("title_es") or forced_slug
                summary = h.metadata.get(summary_field) or h.metadata.get("summary_es") or ""
                break
        return [
            {
                "slug": forced_slug,
                "title": title,
                "summary": summary,
                "relevance": 1.0,
            }
        ]

    # 2. LLM-emitted items
    if llm_items:
        cards: list[dict] = []
        for item in llm_items:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug")
            if not isinstance(slug, str) or slug not in known_slugs:
                continue
            title = item.get("title")
            if not isinstance(title, str):
                title = slug
            summary = item.get("summary")
            if not isinstance(summary, str):
                summary = ""
            relevance_raw = item.get("relevance", 0.0)
            try:
                relevance_f = float(relevance_raw)
            except (TypeError, ValueError):
                relevance_f = 0.0
            cards.append(
                {
                    "slug": slug,
                    "title": title,
                    "summary": summary,
                    "relevance": relevance_f,
                }
            )
        if cards:
            return cards

    # 3. Fallback from hits (LIST / GENERAL with no LLM block)
    cards = []
    for h in hits[:5]:  # cap at 5 cards
        slug = h.metadata.get("slug")
        if not isinstance(slug, str):
            continue
        title = h.metadata.get(title_field) or h.metadata.get("title_es") or slug
        summary = h.metadata.get(summary_field) or h.metadata.get("summary_es") or ""
        score = h.score
        try:
            score_f = float(score)
        except (TypeError, ValueError):
            score_f = 0.0
        cards.append(
            {
                "slug": slug,
                "title": title,
                "summary": summary,
                "relevance": score_f,
            }
        )
    return cards
