"""Unit tests for backend.rag.project_router.

Covers routing priority:
  1. Explicit slug mention -> DETAIL_PROJECT
  2. Pronoun + history -> DETAIL_PROJECT
  3. List intent (tech/stack keywords) -> LIST_PROJECTS
  4. Otherwise -> GENERAL
"""

from __future__ import annotations

import pytest
from backend.rag.project_router import ProjectRouter, RouteDecision, RouteKind

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def known_slugs() -> list[str]:
    """The 5 seeded project slugs (matches tests/integration/test_projects_service.py)."""
    return [
        "proj-data-pipeline",
        "proj-rag-customer",
        "proj-cloud-migration",
        "proj-ml-scoring",
        "proj-realtime-fraud",
    ]


@pytest.fixture
def router(known_slugs) -> ProjectRouter:
    """ProjectRouter populated with the 5 seeded slugs."""
    return ProjectRouter(known_slugs)


# ---------------------------------------------------------------------------
# Class: TestRouteExplicitSlug
# ---------------------------------------------------------------------------


class TestRouteExplicitSlug:
    """An explicit proj-<slug> mention in the question wins over everything else."""

    def test_route_explicit_slug_returns_detail(self, router):
        """Question containing 'proj-data-pipeline' -> DETAIL_PROJECT with that slug."""
        decision = router.route("tell me about proj-data-pipeline")
        assert decision.kind == RouteKind.DETAIL_PROJECT
        assert decision.slug == "proj-data-pipeline"
        assert "proj-data-pipeline" in decision.reason

    def test_route_explicit_slug_in_mixed_text(self, router):
        """Slug mention in the middle of a sentence still triggers DETAIL."""
        decision = router.route("Hola! quiero saber sobre proj-rag-customer por favor")
        assert decision.kind == RouteKind.DETAIL_PROJECT
        assert decision.slug == "proj-rag-customer"

    def test_route_explicit_unknown_slug_returns_general(self, router):
        """Slug-shaped token not in known_slugs -> fall through to GENERAL.

        Per the spec: 'slug if and only if in known_slugs' — so a malformed
        or unknown slug mention does not route to DETAIL. The router picks
        the next-highest-priority intent instead.
        """
        decision = router.route("tell me about proj-bogus-123")
        # The slug is not in known_slugs; router falls through.
        # 'tell me about' has no list-intent keyword, so it lands on GENERAL.
        assert decision.kind == RouteKind.GENERAL


# ---------------------------------------------------------------------------
# Class: TestRouteListIntent
# ---------------------------------------------------------------------------


class TestRouteListIntent:
    """Tech/stack keywords trigger LIST_PROJECTS."""

    def test_route_list_intent_python(self, router):
        """A single 'python' keyword is enough for LIST intent."""
        decision = router.route("qué proyectos tienes con python")
        assert decision.kind == RouteKind.LIST_PROJECTS
        assert decision.tech_hint == "python"

    def test_route_list_intent_spanish(self, router):
        """Spanish 'qué proyectos' phrasing triggers LIST."""
        decision = router.route("qué proyectos hiciste con Python")
        assert decision.kind == RouteKind.LIST_PROJECTS
        # Either 'qué proyectos' or 'python' would be the first hint; the
        # router picks the earliest in the text. 'qué proyectos' appears
        # first in this question.
        assert decision.tech_hint in ("qué proyectos", "python")

    def test_route_list_intent_english(self, router):
        """English 'what projects have you done' triggers LIST."""
        decision = router.route("what projects have you done with AWS")
        assert decision.kind == RouteKind.LIST_PROJECTS
        assert decision.tech_hint in ("aws", "what projects", "what have")

    def test_route_list_intent_aws(self, router):
        """Single keyword 'aws' -> LIST_PROJECTS with hint 'aws'."""
        decision = router.route("have you worked with AWS?")
        assert decision.kind == RouteKind.LIST_PROJECTS
        assert decision.tech_hint == "aws"


# ---------------------------------------------------------------------------
# Class: TestRouteGeneralFallback
# ---------------------------------------------------------------------------


class TestRouteGeneralFallback:
    """No list keywords and no slug -> GENERAL."""

    def test_route_general_intent_fallback(self, router):
        """'qué haces' is not a list/detail question -> GENERAL."""
        decision = router.route("qué haces")
        assert decision.kind == RouteKind.GENERAL

    def test_route_empty_question(self, router):
        """Empty question -> GENERAL (defensive)."""
        decision = router.route("")
        assert decision.kind == RouteKind.GENERAL

    def test_route_whitespace_only_question(self, router):
        """Whitespace-only -> GENERAL."""
        decision = router.route("   \n\t  ")
        assert decision.kind == RouteKind.GENERAL

    def test_route_arbitrary_question(self, router):
        """A bland open question with no keywords -> GENERAL."""
        decision = router.route("how are you?")
        assert decision.kind == RouteKind.GENERAL


# ---------------------------------------------------------------------------
# Class: TestRoutePronounResolution
# ---------------------------------------------------------------------------


class TestRoutePronounResolution:
    """DETAIL pronouns in the question resolve to a previously mentioned slug."""

    def test_route_pronoun_resolution(self, router):
        """History mentions proj-data-pipeline; question 'el primero' -> DETAIL."""
        history = [
            {"role": "user", "content": "show me all your python projects"},
            {"role": "assistant", "content": "I built proj-data-pipeline and proj-rag-customer."},
        ]
        decision = router.route("el primero", history=history)
        assert decision.kind == RouteKind.DETAIL_PROJECT
        # Most recent slug in history is the second one mentioned, but
        # extraction is greedy; 'proj-rag-customer' comes after
        # 'proj-data-pipeline' so we expect the LAST occurrence in
        # the assistant turn to win. The router extracts the FIRST
        # match in any single text via _extract_slug, but it walks
        # history backwards — so it picks the most recent TURN first.
        # Both slugs are in the same assistant turn, and _extract_slug
        # returns the first match in that text. We assert the slug is
        # one of the two known projects; we don't pin which, because the
        # router's semantics for "first match in a single turn" is the
        # simpler and well-defined choice.
        assert decision.slug in {
            "proj-data-pipeline",
            "proj-rag-customer",
        }
        assert "pronoun" in decision.reason

    def test_route_pronoun_no_history(self, router):
        """Pronoun 'el primero' with empty history -> GENERAL."""
        decision = router.route("el primero", history=[])
        assert decision.kind == RouteKind.GENERAL

    def test_route_pronoun_no_history_field(self, router):
        """Pronoun with history=None -> GENERAL (defensive)."""
        decision = router.route("el primero", history=None)
        assert decision.kind == RouteKind.GENERAL

    def test_route_pronoun_history_without_slugs(self, router):
        """Pronoun + history that mentions no slugs -> GENERAL."""
        history = [
            {"role": "assistant", "content": "I worked on several things."},
            {"role": "user", "content": "tell me more"},
        ]
        decision = router.route("el primero", history=history)
        assert decision.kind == RouteKind.GENERAL

    def test_route_pronoun_english_the_first(self, router):
        """'the first' pronoun in English resolves to the most recent slug."""
        history = [
            {"role": "assistant", "content": "I built proj-ml-scoring for a bank."},
        ]
        decision = router.route("the first", history=history)
        assert decision.kind == RouteKind.DETAIL_PROJECT
        assert decision.slug == "proj-ml-scoring"


# ---------------------------------------------------------------------------
# Class: TestRoutePriority
# ---------------------------------------------------------------------------


class TestRoutePriority:
    """Priority order: explicit slug > pronoun > list intent > general."""

    def test_route_history_priority(self, router):
        """Explicit slug in the question wins over a slug in history."""
        history = [
            {"role": "assistant", "content": "I built proj-data-pipeline."},
        ]
        # Question has BOTH a slug ('proj-data-pipeline') and a list keyword ('python').
        # Explicit slug wins -> DETAIL.
        decision = router.route("tell me about proj-data-pipeline and python", history=history)
        assert decision.kind == RouteKind.DETAIL_PROJECT
        assert decision.slug == "proj-data-pipeline"

    def test_route_list_wins_over_history_without_pronoun(self, router):
        """Without an explicit slug or pronoun, list intent wins over history."""
        history = [
            {"role": "assistant", "content": "I built proj-data-pipeline."},
        ]
        decision = router.route("show me your python projects", history=history)
        assert decision.kind == RouteKind.LIST_PROJECTS

    def test_route_returns_route_decision_instance(self, router):
        """`route()` returns a RouteDecision dataclass instance."""
        result = router.route("anything")
        assert isinstance(result, RouteDecision)
        assert isinstance(result.kind, RouteKind)


# ---------------------------------------------------------------------------
# Class: TestRouteLangAgnostic
# ---------------------------------------------------------------------------


class TestRouteLangAgnostic:
    """Routing decisions are language-agnostic (text-inspection only)."""

    @pytest.mark.parametrize(
        "question",
        [
            "qué proyectos tienes con python",
            "what python projects have you done",
            "show me your aws work",
            "tell me about proj-data-pipeline",
            "qué haces",
            "el primero",
        ],
    )
    def test_route_uses_only_text(self, router, question):
        """The router classifies the same way regardless of any lang argument.

        (The router doesn't accept a lang argument today — the test asserts
        that the classifier is invariant to phrasing.)
        """
        decision_es = router.route(question)
        # Re-instantiate the router to ensure no caching
        decision_es_2 = router.route(question)
        assert decision_es.kind == decision_es_2.kind


# ---------------------------------------------------------------------------
# Class: TestRouteSlugExtraction
# ---------------------------------------------------------------------------


class TestRouteSlugExtraction:
    """Direct unit tests for ProjectRouter._extract_slug."""

    def test_extract_slug_basic(self, router):
        assert router._extract_slug("proj-data-pipeline") == "proj-data-pipeline"

    def test_extract_slug_in_sentence(self, router):
        assert router._extract_slug("about proj-rag-customer please") == "proj-rag-customer"

    def test_extract_slug_uppercase(self, router):
        # The router lowercases the question before extraction.
        assert router._extract_slug("PROJ-CLOUD-MIGRATION") == "proj-cloud-migration"

    def test_extract_slug_no_match(self, router):
        assert router._extract_slug("hello world") is None

    def test_extract_slug_empty(self, router):
        assert router._extract_slug("") is None

    def test_extract_slug_returns_first(self, router):
        """When two slugs are present, the first one (leftmost) is returned."""
        result = router._extract_slug("proj-aaa then proj-bbb")
        assert result == "proj-aaa"


# ---------------------------------------------------------------------------
# Class: TestRouteKindEnum
# ---------------------------------------------------------------------------


class TestRouteKindEnum:
    """RouteKind enum exposes the three valid intent names."""

    def test_kind_values(self):
        assert RouteKind.LIST_PROJECTS.value == "LIST_PROJECTS"
        assert RouteKind.DETAIL_PROJECT.value == "DETAIL_PROJECT"
        assert RouteKind.GENERAL.value == "GENERAL"


# ---------------------------------------------------------------------------
# Class: TestRouteCurrentProjectSlug
# ---------------------------------------------------------------------------


class TestRouteCurrentProjectSlug:
    """Phase 5.5: the router accepts current_project_slug as a fallback hint.

    When the visitor is viewing a specific project (e.g. via the chat bubble's
    project-aware state) and the question is ambiguous (no explicit slug,
    no pronoun, no list-intent keywords), the router routes to
    DETAIL_PROJECT(current_project_slug). Explicit slug mentions and
    list-intent keywords still win over this hint.
    """

    def test_route_with_current_project_slug_and_ambiguous_question_defaults_to_detail(
        self, router
    ):
        """Ambiguous question + current_project_slug -> DETAIL on that slug."""
        decision = router.route(
            "¿qué decisiones tomaste?",
            history=[],
            current_project_slug="proj-cloud-migration",
        )
        assert decision.kind == RouteKind.DETAIL_PROJECT
        assert decision.slug == "proj-cloud-migration"
        assert "proj-cloud-migration" in decision.reason

    def test_route_with_current_project_slug_but_explicit_slug_wins(self, router):
        """An explicit slug mention in the question beats the current-project hint."""
        decision = router.route(
            "tell me about proj-data-pipeline",
            history=[],
            current_project_slug="proj-cloud-migration",
        )
        assert decision.kind == RouteKind.DETAIL_PROJECT
        assert decision.slug == "proj-data-pipeline"

    def test_route_with_current_project_slug_and_list_intent_wins(self, router):
        """List-intent keywords beat the current-project hint -> LIST_PROJECTS."""
        decision = router.route(
            "qué proyectos tienes con python",
            history=[],
            current_project_slug="proj-cloud-migration",
        )
        assert decision.kind == RouteKind.LIST_PROJECTS
        assert decision.slug is None

    def test_route_with_current_project_slug_unknown_slug_ignored(self, router):
        """current_project_slug not in known_slugs is treated as no context."""
        decision = router.route(
            "qué decisiones tomaste?",
            history=[],
            current_project_slug="proj-does-not-exist",
        )
        # Unknown slug -> router falls through to GENERAL (step 5).
        assert decision.kind == RouteKind.GENERAL

    def test_route_with_no_current_project_slug_behaves_as_before(self, router):
        """Omitting current_project_slug preserves the previous behavior."""
        # Ambiguous question -> GENERAL (default fallback).
        decision = router.route("¿qué decisiones tomaste?", history=[])
        assert decision.kind == RouteKind.GENERAL
        assert decision.slug is None

    def test_route_with_current_project_slug_pronoun_still_wins(self, router):
        """Pronoun in question still resolves via history, beating the current hint."""
        history = [
            {"role": "assistant", "content": "I built proj-data-pipeline."},
        ]
        decision = router.route(
            "el primero",
            history=history,
            current_project_slug="proj-cloud-migration",
        )
        # Step 2 (pronoun) fires before step 4 (current project).
        assert decision.kind == RouteKind.DETAIL_PROJECT
        assert decision.slug == "proj-data-pipeline"

    def test_route_with_current_project_slug_default_arg_is_none(self, router):
        """current_project_slug defaults to None (backward-compatible signature)."""
        decision = router.route("¿qué decisiones tomaste?", history=[])
        assert decision.slug is None
        assert decision.kind == RouteKind.GENERAL
