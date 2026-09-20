"""Heuristic project router: classify user questions into LIST/DETAIL/GENERAL.

See Phase 3 design doc §3 (ProjectRouter).
Pure text classification: NO LLM call, NO ChromaDB access. The router only
inspects the question text and (for detail) the conversation history to
resolve pronouns like 'el primero'.

Routing priority:
  1. Explicit slug mention in question -> DETAIL_PROJECT
  2. Pronoun in question + previous slug in history -> DETAIL_PROJECT
  3. List intent (tech/stack keywords) -> LIST_PROJECTS
  4. Otherwise -> GENERAL (queries projects_index broadly)

The router does NOT call ChromaDB. ChromaDB queries happen in chat_service.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class RouteKind(str, Enum):
    """High-level intent classification for a user question."""

    LIST_PROJECTS = "LIST_PROJECTS"
    DETAIL_PROJECT = "DETAIL_PROJECT"
    GENERAL = "GENERAL"


@dataclass
class RouteDecision:
    """Result of ProjectRouter.route().

    Attributes:
        kind: One of RouteKind.LIST_PROJECTS / DETAIL_PROJECT / GENERAL.
        slug: For DETAIL_PROJECT: the resolved slug (e.g. "proj-data-pipeline").
              For other kinds: None.
        tech_hint: For LIST_PROJECTS: an extracted tech keyword (e.g. "python")
              used to log intent. The actual filtering uses the index's own
              relevance ranking, not this hint.
        reason: Human-readable string for logs/debug.
    """

    kind: RouteKind
    slug: str | None = None
    tech_hint: str | None = None
    reason: str = ""
    extra: dict = field(default_factory=dict)


class ProjectRouter:
    """Heuristic router for the projects-aware chatbot.

    Classifies a user question into LIST_PROJECTS / DETAIL_PROJECT / GENERAL
    using only text inspection (no LLM call, no vector store access).

    The router is deterministic and stateless beyond the constructor's
    `known_slugs` set. The same (question, history) inputs always produce
    the same RouteDecision.
    """

    # Slug pattern: proj- followed by lowercase letters, digits, or dashes.
    # Matches project slugs in apps/api/data/projects/proj-*.md.
    SLUG_PATTERN = r"proj-[a-z0-9-]+"

    # Tech/stack keywords that signal LIST intent.
    # Includes both ES and EN terms because users mix languages in tech questions.
    LIST_TOKENS: set[str] = {
        # ES tech
        "python", "aws", "kafka", "spark", "rag", "openai", "llm",
        "terraform", "kubernetes", "docker", "ml", "data", "cloud",
        "fraud", "real-time", "fintech", "banco",
        # EN tech (Spanish is OK in tech context)
        "react", "typescript", "node", "postgres", "redis",
        "data-engineering", "data engineering", "devops", "mlops",
        # Generic list signals (ES + EN)
        "qué proyectos", "que proyectos", "lista", "list", "show me",
        "tienes", "tenés", "have", "do you have", "qué hiciste", "what did",
        "what have", "all your", "todos tus", "all your projects",
        "qué proyectos tienes", "que proyectos tienes",
        "qué proyectos hiciste", "que proyectos hiciste",
        "what projects", "what have you done", "show me projects",
    }

    # Pronouns that signal detail intent (referring to a previous project).
    DETAIL_PRONOUNS: set[str] = {
        "el primero", "el segundo", "el tercero", "el último", "el anterior",
        "the first", "the second", "the third", "the last", "the previous",
        "that one", "este", "ese",
    }

    def __init__(self, known_slugs: list[str]) -> None:
        """Initialise the router with the set of known project slugs.

        Args:
            known_slugs: Project slugs that exist in the database, e.g.
                ["proj-data-pipeline", "proj-rag-customer"]. Slugs not in
                this set are ignored even if they appear in a question.
        """
        self._known_slugs: set[str] = set(known_slugs)

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    def route(
        self,
        question: str,
        history: list[dict] | None = None,
        current_project_slug: str | None = None,
    ) -> RouteDecision:
        """Classify the user's question.

        Args:
            question: The user's current message.
            history: Optional list of {"role": "user"|"assistant", "content": "..."}
                of recent turns (most recent last). Used for pronoun resolution
                in DETAIL intent.
            current_project_slug: Optional slug of the project the visitor is
                currently viewing (e.g. via the chat bubble's project-aware
                state). Used as a fallback hint: when the question is
                ambiguous (no explicit slug mention, no pronoun, no list-intent
                keywords), route to DETAIL_PROJECT(current_project_slug).
                If current_project_slug is None or not in self._known_slugs,
                this step is a no-op (the router falls through to GENERAL).

        Returns:
            RouteDecision with kind=LIST_PROJECTS / DETAIL_PROJECT(slug) /
            GENERAL. Always returns a decision; never raises.
        """
        # Normalise question text
        q = (question or "").strip().lower()

        # Empty question -> general (we don't try to guess intent from nothing)
        if not q:
            return RouteDecision(kind=RouteKind.GENERAL, reason="empty question")

        # 1. Check for explicit slug mention (highest priority for DETAIL)
        slug = self._extract_slug(question)
        if slug and slug in self._known_slugs:
            return RouteDecision(
                kind=RouteKind.DETAIL_PROJECT,
                slug=slug,
                reason=f"slug '{slug}' found in question",
            )

        # 2. Check history for previously mentioned projects (pronoun resolution)
        if history:
            resolved = self._resolve_pronoun(question, history)
            if resolved:
                return RouteDecision(
                    kind=RouteKind.DETAIL_PROJECT,
                    slug=resolved,
                    reason=f"pronoun '{q}' resolved to '{resolved}' via history",
                )

        # 3. Check for list intent
        if self._is_list_question(q):
            tech_hint = self._extract_tech_hint(q)
            return RouteDecision(
                kind=RouteKind.LIST_PROJECTS,
                tech_hint=tech_hint,
                reason=f"list intent detected, tech_hint={tech_hint}",
            )

        # 4. Project-context fallback. If the visitor is currently viewing a
        # specific project (passed by the frontend) and the question is
        # ambiguous (none of the above classifications fired), default to
        # DETAIL on that project. This makes the chat feel "stuck to"
        # whatever page the visitor is on. Explicit slug mentions (step 1)
        # and pronouns (step 2) and list-intent (step 3) still win.
        if current_project_slug and current_project_slug in self._known_slugs:
            return RouteDecision(
                kind=RouteKind.DETAIL_PROJECT,
                slug=current_project_slug,
                reason=(
                    f"ambiguous question; defaulting to current project "
                    f"'{current_project_slug}'"
                ),
            )

        # 5. Fallback: general overview (queries projects_index broadly)
        return RouteDecision(kind=RouteKind.GENERAL, reason="fallback general overview")

    # ---------------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------------

    def _extract_slug(self, text: str) -> str | None:
        """Return the first slug-shaped token in `text`, or None.

        Looks for `proj-<slug>` substrings. Returns the first match.
        The caller checks membership in `_known_slugs`.
        """
        if not text:
            return None
        match = re.search(self.SLUG_PATTERN, text.lower())
        if match:
            return match.group(0)
        return None

    def _is_list_question(self, text_lower: str) -> bool:
        """Return True if `text_lower` matches any list-intent keyword.

        The input MUST be already lower-cased and stripped.
        Checks both full-phrase and per-word membership: a single tech keyword
        like 'python' or 'aws' counts as list intent.
        """
        if not text_lower:
            return False

        # 1. Direct substring match on multi-word phrases
        for token in self.LIST_TOKENS:
            if (" " in token or "-" in token) and token in text_lower:
                return True

        # 2. Word-boundary match on single-word tech keywords
        # Use regex to avoid partial matches (e.g. "pythonic" matching "python")
        for token in self.LIST_TOKENS:
            if " " not in token and "-" not in token:
                # word-boundary search
                pattern = r"(?:^|\b)" + re.escape(token) + r"(?:\b|$)"
                if re.search(pattern, text_lower):
                    return True

        return False

    def _extract_tech_hint(self, text_lower: str) -> str | None:
        """Return the first matching tech keyword (lowercase) in `text_lower`, or None.

        Prefers *tech* keywords (single-word or multi-word tech nouns) over
        generic list-intent phrases ("qué proyectos", "what projects").
        Searches the text for tech tokens first and only falls back to
        generic list phrases when no tech keyword matches.

        Returns the earliest match in `text_lower` among the chosen
        candidate set.
        """
        if not text_lower:
            return None

        # Generic list phrases — only used when no tech keyword matches.
        generic_tokens: set[str] = {
            "qué proyectos", "que proyectos", "lista", "list", "show me",
            "tienes", "tenés", "have", "do you have", "qué hiciste", "what did",
            "what have", "all your", "todos tus", "all your projects",
            "qué proyectos tienes", "que proyectos tienes",
            "qué proyectos hiciste", "que proyectos hiciste",
            "what projects", "what have you done", "show me projects",
        }

        tech_tokens: set[str] = {
            "python", "aws", "kafka", "spark", "rag", "openai", "llm",
            "terraform", "kubernetes", "docker", "ml", "data", "cloud",
            "fraud", "real-time", "fintech", "banco",
            "react", "typescript", "node", "postgres", "redis",
            "data-engineering", "data engineering", "devops", "mlops",
        }

        best_pos: int | None = None
        best_token: str | None = None

        def _search(token: str) -> tuple[int, str] | None:
            if " " in token or "-" in token:
                idx = text_lower.find(token)
                return (idx, token) if idx >= 0 else None
            pattern = r"(?:^|\b)" + re.escape(token) + r"(?:\b|$)"
            match = re.search(pattern, text_lower)
            return (match.start(), token) if match else None

        for token in tech_tokens:
            hit = _search(token)
            if hit is None:
                continue
            pos, tok = hit
            if best_pos is None or pos < best_pos:
                best_pos = pos
                best_token = tok

        if best_token is not None:
            return best_token

        # Fall back to generic list phrases
        for token in generic_tokens:
            hit = _search(token)
            if hit is None:
                continue
            pos, tok = hit
            if best_pos is None or pos < best_pos:
                best_pos = pos
                best_token = tok

        return best_token

    def _resolve_pronoun(self, question: str, history: list[dict]) -> str | None:
        """Walk history backwards to find the most recently mentioned slug.

        Only resolves if the question contains a DETAIL_PRONOUN substring
        (case-insensitive). Walks the history most-recent-first looking
        for a slug-shaped token that is in `_known_slugs`. Returns the
        slug, or None if no pronoun / no slug in history / no known slug.
        """
        q_lower = (question or "").lower()
        has_pronoun = any(p in q_lower for p in self.DETAIL_PRONOUNS)
        if not has_pronoun:
            return None

        # Walk history most-recent-first
        for turn in reversed(history):
            content = turn.get("content", "") if isinstance(turn, dict) else ""
            if not isinstance(content, str):
                continue
            slug = self._extract_slug(content)
            if slug and slug in self._known_slugs:
                return slug

        return None
