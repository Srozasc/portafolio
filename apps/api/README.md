# apps/api — Portafolio RAG backend

FastAPI + ChromaDB backend (forked from HiRag15k). Powers the chatbot that answers questions about projects.

## Status

- **Phase 0**: incorporated from HiRag15k. All 120 tests should pass.
- **Phase 1-3**: will add master index + per-project collections + ProjectRouter (see [impl plan](../../docs/plans/2026-09-17-portafolio-rag-impl-plan.md)).

## Setup (local dev)

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
# Edit .env and set LLM_API_KEY (and EMBEDDING_API_KEY if using OpenAI)
```

## Run tests

```bash
.venv\Scripts\python -m pytest -q
```

## Run dev server

```bash
.venv\Scripts\python -m uvicorn backend.main:app --reload
```

## Endpoints (current HiRag15k MVP)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Demo frontend (will be replaced by Astro) |
| `GET` | `/api/health` | System status |
| `POST` | `/api/ingest` | Index a Markdown file |
| `POST` | `/api/chat/stream` | Chat with SSE streaming |

## What's next

See [impl plan §Phase 3](../../docs/plans/2026-09-17-portafolio-rag-impl-plan.md#phase-3--bot-router-1-2-days) for the upcoming bot routing extension.

## Source / lineage

Forked from HiRag15k via `cp -r` on 2026-09-17. The original HiRag15k repo is at `D:/desarrollo/2027/HiRag15k/` and remains the source of truth for the upstream RAG pattern. When we modify backend code, we do so in this fork — there is no automatic sync.

For reference, HiRag15k's design doc is at `D:/desarrollo/2027/HiRag15k/docs/plans/2026-07-01-hirag15k-design.md`.
