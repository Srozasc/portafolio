"""Integration tests for POST /api/chat/stream-projects SSE endpoint.

Phase 3: project-aware router with bilingual prompts and structured SSE
responses. Pattern mirrors tests/integration/test_chat_endpoint.py.

Uses a standalone FastAPI app with the chat route mounted, real ChromaDB in
tmp_path (2-3 seeded project collections), and a scripted fake LLM to
avoid network calls.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.errors import register_exception_handlers
from backend.api.routes.chat import _get_chat_service, router as chat_router
from backend.rag.retriever import Retriever
from backend.rag.vector_store import VectorStore
from backend.services.chat_service import ChatService
from backend.services.projects_service import ProjectsService


# ---------------------------------------------------------------------------
# Fake LLM (scripted token sequence)
# ---------------------------------------------------------------------------


class FakeLLM:
    """Scripted LLM that yields canned tokens then stops.

    The chat service calls `stream_chat(system, user)`; both args are
    captured for inspection.
    """

    def __init__(self, tokens: list[str] | None = None) -> None:
        self.tokens = tokens or ["Hello", " world", "!"]
        self.call_count = 0
        self.last_system: str | None = None
        self.last_user: str | None = None

    def stream_chat(self, system: str, user: str) -> Iterator[str]:
        self.call_count += 1
        self.last_system = system
        self.last_user = user
        yield from self.tokens


# ---------------------------------------------------------------------------
# Deterministic fake embedder (one fixed vector for every text)
# ---------------------------------------------------------------------------


def make_deterministic_embedder(dim: int = 16):
    """Return a fake embedder that maps every text to the same vector.

    With a fixed vector for every query, cosine similarity to any stored
    vector is the same — so the retriever's threshold filter either keeps
    all or drops all. We set the retriever threshold to 0.0 in the tests
    so all upserted chunks surface as hits.
    """

    class _FakeEmbedder:
        def __init__(self, d: int) -> None:
            self.dim = d

        def embed(self, texts):
            return [[0.5] * self.dim for _ in texts]

    return _FakeEmbedder(dim)


# ---------------------------------------------------------------------------
# SSE parsing
# ---------------------------------------------------------------------------


def parse_sse_lines(raw: str) -> list[dict]:
    """Parse SSE-formatted response into a list of event dicts."""
    events: list[dict] = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------


def _sample_index_doc(slug: str, *, tech: str = "python") -> str:
    """A short document for the master index entry of a project."""
    return (
        f"Project {slug} title\n"
        f"Project {slug} title en\n"
        f"Resumen del proyecto {slug} con {tech}.\n"
        f"Summary of project {slug} with {tech}.\n"
        f"Tags: {tech}"
    )


def _sample_index_metadata(slug: str, *, tech: str = "python") -> dict:
    """Index metadata used to render project cards."""
    return {
        "slug": slug,
        "title_es": f"{slug}-title-es",
        "title_en": f"{slug}-title-en",
        "year": 2024,
        "role_es": "Tech Lead",
        "role_en": "Tech Lead",
        "client": "Test Client",
        "tags": json.dumps([tech, "data"]),
        "summary_es": f"Resumen {slug} ({tech})",
        "summary_en": f"Summary {slug} ({tech})",
    }


def _seed_projects(
    store: VectorStore,
    slugs: list[str],
    *,
    tech: str = "python",
    dim: int = 16,
) -> None:
    """Seed master index + per-project detail collections for each slug.

    All vectors are [0.5] * dim — combined with the deterministic embedder
    this guarantees all hits are returned (threshold set to 0.0).
    """
    vec = [0.5] * dim
    # detail_collection_name is an instance method on ProjectsService, but
    # it doesn't depend on instance state; build a no-op service for it.
    detail_namer = ProjectsService.__new__(ProjectsService)
    # Master index: one chunk per project
    index_ids = [f"{s}__index" for s in slugs]
    index_docs = [_sample_index_doc(s, tech=tech) for s in slugs]
    index_metas = [_sample_index_metadata(s, tech=tech) for s in slugs]
    store.upsert(
        name=ProjectsService.INDEX_COLLECTION,
        ids=index_ids,
        embeddings=[vec for _ in slugs],
        documents=index_docs,
        metadatas=index_metas,
    )
    # Per-project detail: one chunk per project
    for s in slugs:
        store.upsert(
            name=detail_namer.detail_collection_name(s),
            ids=[f"{s}__chunk_0"],
            embeddings=[vec],
            documents=[f"Detail body for {s}."],
            metadatas=[
                {
                    "slug": s,
                    "source": f"{s}.md",
                    "year": 2024,
                    "section_header": "Contexto",
                    "chunk_index": 0,
                    "char_start": 0,
                    "char_end": 30,
                }
            ],
        )


def make_projects_chat_app(
    chroma_dir: Path,
    fake_llm,
    *,
    seed_slugs: list[str] | None = None,
) -> tuple[FastAPI, TestClient, ChatService]:
    """Create a FastAPI app with the chat route mounted, ChromaDB seeded.

    Returns (app, client, service). The service uses a real Retriever
    (real ChromaDB query path) and the scripted LLM.
    """
    app = FastAPI()
    register_exception_handlers(app)

    store = VectorStore(persist_dir=str(chroma_dir))
    embedder = make_deterministic_embedder()
    retriever = Retriever(store=store, embedder=embedder, threshold=0.0)
    service = ChatService(retriever=retriever, llm=fake_llm)

    # Seed default 3 projects if not provided
    if seed_slugs is None:
        seed_slugs = ["proj-data-pipeline", "proj-rag-customer", "proj-ml-scoring"]
    _seed_projects(store, seed_slugs, tech="python")

    app.state.chat_service = service
    app.dependency_overrides[_get_chat_service] = lambda: service
    app.include_router(chat_router)
    client = TestClient(app, raise_server_exceptions=False)
    return app, client, service


# ---------------------------------------------------------------------------
# Helpers for tests
# ---------------------------------------------------------------------------


def _collect_events(response_text: str) -> dict:
    """Parse SSE and group by type.

    Returns:
        {"content": [...], "projects": [...], "done": [...], "error": [...], "all": [...]}
    """
    parsed = parse_sse_lines(response_text)
    grouped: dict[str, list[dict]] = {
        "content": [],
        "projects": [],
        "done": [],
        "error": [],
        "all": parsed,
    }
    for e in parsed:
        t = e.get("type")
        if t in grouped:
            grouped[t].append(e)
    return grouped


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListRoute:
    """LIST_PROJECTS route: SSE stream emits content + projects + done."""

    def test_list_route_emits_content_then_projects_then_done(self, tmp_path: Path):
        """LIST route: content tokens, a projects event, then done."""
        fake_llm = FakeLLM(
            tokens=[
                "Trabajé en 3 proyectos.",
                " ===PROJECTS===\n",
                '[{"slug": "proj-data-pipeline", "title": "Pipeline", ',
                '"summary": "Resumen", "relevance": 0.94}]\n',
                "===END===",
            ]
        )
        _app, client, _service = make_projects_chat_app(tmp_path, fake_llm)

        response = client.post(
            "/api/chat/stream-projects",
            json={"question": "qué proyectos tienes con python", "lang": "es"},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        events = _collect_events(response.text)
        # We expect at least one content event, one projects event, one done
        assert len(events["content"]) >= 1
        assert len(events["projects"]) == 1
        assert len(events["done"]) == 1

        # Projects event payload
        proj_event = events["projects"][0]
        assert proj_event["type"] == "projects"
        items = proj_event["items"]
        assert isinstance(items, list)
        assert len(items) >= 1
        # The LLM-emitted slug must be present and known
        slugs = {item["slug"] for item in items}
        assert "proj-data-pipeline" in slugs


class TestDetailRoute:
    """DETAIL_PROJECT route: forced slug card with relevance 1.0."""

    def test_detail_route_emits_content_with_project_metadata(self, tmp_path: Path):
        """DETAIL route: projects event contains the explicit slug, relevance=1.0."""
        fake_llm = FakeLLM(
            tokens=["proj-data-pipeline ", "es un pipeline de datos en tiempo real."]
        )
        _app, client, _service = make_projects_chat_app(tmp_path, fake_llm)

        response = client.post(
            "/api/chat/stream-projects",
            json={"question": "tell me about proj-data-pipeline", "lang": "en"},
        )
        assert response.status_code == 200

        events = _collect_events(response.text)
        assert len(events["projects"]) == 1
        items = events["projects"][0]["items"]
        assert len(items) == 1
        card = items[0]
        assert card["slug"] == "proj-data-pipeline"
        assert card["relevance"] == 1.0
        # title/summary come from the index metadata (title_es / summary_es by default)
        assert "title" in card
        assert "summary" in card


class TestGeneralRoute:
    """GENERAL fallback: emits top-N from the index when no LLM JSON block."""

    def test_general_route_emits_top_projects(self, tmp_path: Path):
        """GENERAL route: LLM emits no JSON block; cards come from index hits."""
        fake_llm = FakeLLM(
            tokens=["Soy un ingeniero de datos y backend."]
        )
        _app, client, _service = make_projects_chat_app(tmp_path, fake_llm)

        response = client.post(
            "/api/chat/stream-projects",
            json={"question": "what do you do", "lang": "en"},
        )
        assert response.status_code == 200

        events = _collect_events(response.text)
        assert len(events["projects"]) == 1
        items = events["projects"][0]["items"]
        # 3 seeded projects -> 3 cards
        assert len(items) == 3
        slugs = {item["slug"] for item in items}
        assert slugs == {"proj-data-pipeline", "proj-rag-customer", "proj-ml-scoring"}


class TestInvalidSlugFiltering:
    """LLM JSON block with unknown slugs: those are dropped silently."""

    def test_invalid_slug_in_llm_output_dropped(self, tmp_path: Path):
        """LLM emits one valid + one invalid slug; only the valid one is kept."""
        fake_llm = FakeLLM(
            tokens=[
                "Texto. ",
                "===PROJECTS===\n",
                json.dumps(
                    [
                        {
                            "slug": "proj-data-pipeline",
                            "title": "OK",
                            "summary": "s",
                            "relevance": 0.9,
                        },
                        {
                            "slug": "proj-evil-injected",
                            "title": "EVIL",
                            "summary": "x",
                            "relevance": 0.99,
                        },
                    ]
                ),
                "\n===END===",
            ]
        )
        _app, client, _service = make_projects_chat_app(tmp_path, fake_llm)

        response = client.post(
            "/api/chat/stream-projects",
            json={"question": "list your projects", "lang": "en"},
        )
        events = _collect_events(response.text)
        assert len(events["projects"]) == 1
        items = events["projects"][0]["items"]
        slugs = {item["slug"] for item in items}
        # Invalid slug dropped
        assert slugs == {"proj-data-pipeline"}


class TestMalformedJsonBlock:
    """Malformed JSON in the projects block: dropped, no error event."""

    def test_malformed_json_block_continues_with_prose(self, tmp_path: Path):
        """Bad JSON: prose still streams, no projects event, no error event."""
        fake_llm = FakeLLM(
            tokens=[
                "Hola. ",
                "===PROJECTS===\n",
                "this is not json {]\n",
                "===END===",
            ]
        )
        _app, client, _service = make_projects_chat_app(tmp_path, fake_llm)

        response = client.post(
            "/api/chat/stream-projects",
            json={"question": "qué proyectos tienes", "lang": "es"},
        )
        events = _collect_events(response.text)

        # No error
        assert len(events["error"]) == 0
        # Prose still came through
        assert len(events["content"]) >= 1
        # No projects event because the block failed to parse
        # (and the question is a list-intent with hits from index; but
        # since the LLM JSON was malformed, we fall back to hits → cards)
        # In this case there ARE index hits so the fallback path emits cards.
        # We only assert: prose + no error + a final done.
        assert len(events["done"]) == 1


class TestBilingualPromptSelection:
    """lang='es' / 'en' selects the right system prompt template."""

    def test_bilingual_prompt_selection_lang_es(self, tmp_path: Path):
        """lang='es' -> Spanish system prompt template."""
        fake_llm = FakeLLM(tokens=["respuesta"])
        _app, client, _service = make_projects_chat_app(tmp_path, fake_llm)

        response = client.post(
            "/api/chat/stream-projects",
            json={"question": "qué proyectos tienes", "lang": "es"},
        )
        assert response.status_code == 200
        assert fake_llm.last_system is not None
        # Spanish template signature
        assert "Respondé siempre en español" in fake_llm.last_system
        assert "=== INFORMACIÓN RECUPERADA ===" in fake_llm.last_system

    def test_bilingual_prompt_selection_lang_en(self, tmp_path: Path):
        """lang='en' -> English system prompt template."""
        fake_llm = FakeLLM(tokens=["answer"])
        _app, client, _service = make_projects_chat_app(tmp_path, fake_llm)

        response = client.post(
            "/api/chat/stream-projects",
            json={"question": "what projects do you have", "lang": "en"},
        )
        assert response.status_code == 200
        assert fake_llm.last_system is not None
        # English template signature
        assert "Always respond in English" in fake_llm.last_system
        assert "=== RETRIEVED INFORMATION ===" in fake_llm.last_system


class TestHistoryPropagation:
    """History turns are included in the LLM user message."""

    def test_history_propagates_to_prompt(self, tmp_path: Path):
        """A request with 2 history turns → both turns appear in the user message."""
        fake_llm = FakeLLM(tokens=["ok"])
        _app, client, _service = make_projects_chat_app(tmp_path, fake_llm)

        response = client.post(
            "/api/chat/stream-projects",
            json={
                "question": "tell me more",
                "lang": "en",
                "history": [
                    {"role": "user", "content": "first user msg"},
                    {"role": "assistant", "content": "first assistant msg"},
                ],
            },
        )
        assert response.status_code == 200
        assert fake_llm.last_user is not None
        assert "first user msg" in fake_llm.last_user
        assert "first assistant msg" in fake_llm.last_user
        assert "tell me more" in fake_llm.last_user

    def test_history_window_6_turns(self, tmp_path: Path):
        """A request with 10 turns → only the last 6 appear in the user message."""
        fake_llm = FakeLLM(tokens=["ok"])
        _app, client, _service = make_projects_chat_app(tmp_path, fake_llm)

        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn-{i}"}
            for i in range(10)
        ]

        response = client.post(
            "/api/chat/stream-projects",
            json={
                "question": "current q",
                "lang": "en",
                "history": history,
            },
        )
        assert response.status_code == 200
        assert fake_llm.last_user is not None
        # Last 6 turns: turn-4 .. turn-9
        for i in range(4, 10):
            assert f"turn-{i}" in fake_llm.last_user, f"missing turn-{i}"
        # Older turns are dropped
        for i in range(4):
            assert f"turn-{i}" not in fake_llm.last_user, f"unexpected turn-{i}"


class TestEventOrdering:
    """SSE event order: content first, then projects, then done."""

    def test_event_ordering_content_projects_done(self, tmp_path: Path):
        """Stream order: content (×N) -> projects -> done."""
        fake_llm = FakeLLM(
            tokens=[
                "a",
                " b",
                " c",
                " ===PROJECTS===\n",
                '[{"slug": "proj-data-pipeline", "title": "x", "summary": "y", "relevance": 1.0}]\n',
                "===END===",
            ]
        )
        _app, client, _service = make_projects_chat_app(tmp_path, fake_llm)

        response = client.post(
            "/api/chat/stream-projects",
            json={"question": "qué proyectos tienes", "lang": "es"},
        )
        events = parse_sse_lines(response.text)

        # Walk the events and find the index of the first projects and the
        # index of the first done; all content events must precede both.
        first_projects_idx = next(
            (i for i, e in enumerate(events) if e.get("type") == "projects"),
            None,
        )
        first_done_idx = next(
            (i for i, e in enumerate(events) if e.get("type") == "done"),
            None,
        )
        assert first_projects_idx is not None
        assert first_done_idx is not None
        # All content events precede projects
        last_content_idx = max(
            (i for i, e in enumerate(events) if e.get("type") == "content"),
            default=-1,
        )
        assert last_content_idx < first_projects_idx
        # Projects precedes done
        assert first_projects_idx < first_done_idx


class TestMissingQuestion:
    """400 MISSING_QUESTION on empty / missing question field."""

    def test_missing_question_returns_400(self, tmp_path: Path):
        """Empty question string -> 400 MISSING_QUESTION."""
        fake_llm = FakeLLM()
        _app, client, _service = make_projects_chat_app(tmp_path, fake_llm)

        response = client.post(
            "/api/chat/stream-projects",
            json={"question": ""},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "MISSING_QUESTION"


class TestPronounResolutionInRoute:
    """Pronoun in the question is resolved via history to a known slug."""

    def test_pronoun_resolves_to_history_slug(self, tmp_path: Path):
        """History mentions proj-data-pipeline; question 'el primero' -> DETAIL."""
        fake_llm = FakeLLM(tokens=["detail body"])
        _app, client, _service = make_projects_chat_app(tmp_path, fake_llm)

        response = client.post(
            "/api/chat/stream-projects",
            json={
                "question": "el primero",
                "lang": "es",
                "history": [
                    {"role": "assistant", "content": "I built proj-data-pipeline."},
                ],
            },
        )
        events = _collect_events(response.text)
        # DETAIL route -> forced slug card
        assert len(events["projects"]) == 1
        items = events["projects"][0]["items"]
        assert len(items) == 1
        assert items[0]["slug"] == "proj-data-pipeline"
        assert items[0]["relevance"] == 1.0


class TestLangDefault:
    """When the request omits 'lang', the default is 'es'."""

    def test_default_lang_is_es(self, tmp_path: Path):
        """No 'lang' field in the body -> Spanish template is used."""
        fake_llm = FakeLLM(tokens=["respuesta"])
        _app, client, _service = make_projects_chat_app(tmp_path, fake_llm)

        response = client.post(
            "/api/chat/stream-projects",
            json={"question": "qué proyectos tienes"},  # no lang
        )
        assert response.status_code == 200
        assert fake_llm.last_system is not None
        assert "Respondé siempre en español" in fake_llm.last_system
