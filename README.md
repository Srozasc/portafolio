# Portafolio RAG

Professional portfolio navigable by chatbot with RAG. Visitors ask by stack (Python, AWS, etc.) and the bot returns conversational answers plus clickable project cards linking to pre-rendered detail pages.

## Status

🚧 **In design phase** — see [design doc](docs/plans/2026-09-17-portafolio-rag-design.md) and [implementation plan](docs/plans/2026-09-17-portafolio-rag-impl-plan.md).

## Architecture

- **Frontend**: Astro 4.x (SSG with islands) hosted on Vercel
- **Backend**: FastAPI (fork of [HiRag15k](https://example.com/HiRag15k)) on a Linux host with ChromaDB
- **Bot**: Two-step RAG — list (master index) → detail (per-project collection)
- **i18n**: Bilingual ES/EN with switcher

## Repo structure

```text
apps/
├── web/    # Astro frontend
└── api/    # FastAPI backend (fork of HiRag15k)
scripts/    # CLI tools (add_project, reindex, deploy)
docs/       # Plans, deploy guides
```

## Documentation

- [Design doc](docs/plans/2026-09-17-portafolio-rag-design.md)
- [Implementation plan](docs/plans/2026-09-17-portafolio-rag-impl-plan.md)

## Quickstart (local dev — coming in Phase 0)

```bash
# Backend
cd apps/api
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/reindex.py
.venv/bin/python -m uvicorn backend.main:app --reload

# Frontend
cd apps/web
pnpm install
pnpm dev
```

## License

TBD
