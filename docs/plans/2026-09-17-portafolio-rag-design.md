# Portafolio RAG — Design Doc

**Date**: 2026-09-17
**Status**: Approved
**Author**: Sebastián Rozas + el Gentleman (brainstorming session)
**Repo**: `D:/desarrollo/workspace/2027/portafolio/`
**Reuses**: `D:/desarrollo/2027/HiRag15k/` (backend base)

---

## 1. Vision

A bilingual (ES/EN) professional portfolio website where visitors chat with a bot that knows the user's full career. The visitor asks by stack ("Python", "AWS", "cloud architecture") and the bot returns a conversational answer plus clickable project cards. Each card links to a pre-rendered project detail page.

The portfolio differentiates from the typical "static list of projects" by letting recruiters filter and explore through natural language — exactly how they already think ("show me your React work", "what did you do with AWS in the last 2 years?").

**Primary audience**: technical recruiters and hiring managers who filter by stack and seniority.

## 2. Confirmed decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Audience: Technical recruiters / hiring managers | Formal tone, focus on verifiable skills and measurable impact |
| 2 | Language: ES + EN bilingual with switcher | i18n real, content duplicated per language |
| 3 | Project format: Single MD + YAML frontmatter | Single source of truth, parseable metadata, easy to author |
| 4 | RAG indexing: Master index + per-project collections | Two-step bot reasoning: list → detail |
| 5 | Stack: Astro (frontend) + FastAPI (backend, fork of HiRag15k) | Pre-rendered pages + interactive chat, SSG with islands |
| 6 | Bot response format: Hybrid (prose + structured list at the end) | Conversational UX with clickable cards |
| 7 | Backend hosting: **Deferred to deploy time** | See §7 |
| 8 | Frontend hosting: Vercel (free tier) | Native Astro support, automatic deploys, CDN global |

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│ Vercel — Astro 4.x (SSG + islands)                                │
│  - Pre-rendered project detail pages                              │
│  - i18n ES/EN built-in                                            │
│  - <Chatbot /> island (React or Solid)                            │
│  - LangSwitcher in header                                         │
└────────────────────────────┬─────────────────────────────────────┘
                             │ SSE (cross-origin)
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ Backend host (TBD — see §7)                                       │
│                                                                   │
│  ┌────────────────┐    ┌──────────────────┐    ┌──────────────┐ │
│  │ /api/chat/     │───▶│ RouterService    │───▶│ ChromaDB     │ │
│  │ stream         │    │ (decide route)   │    │              │ │
│  └────────────────┘    └────────┬─────────┘    │ - index      │ │
│                                  │              │ - project/   │ │
│                                  ▼              │   <slug>     │ │
│                        ┌────────────────┐       └──────────────┘ │
│                        │ Retriever +    │                         │
│                        │ LLM Client     │                         │
│                        └────────────────┘                         │
│                                                                   │
│  Exposed via Cloudflare Tunnel (no open ports, auto SSL)         │
└──────────────────────────────────────────────────────────────────┘
```

## 4. Repository structure

```
portafolio/
├── apps/
│   ├── web/                          # Astro (Vercel)
│   │   ├── src/
│   │   │   ├── pages/
│   │   │   │   ├── index.astro       # landing + chat
│   │   │   │   ├── proyectos/
│   │   │   │   │   ├── index.astro   # listing
│   │   │   │   │   └── [slug].astro  # detail (pre-rendered)
│   │   │   │   └── sobre-mi.astro
│   │   │   ├── components/
│   │   │   │   ├── Chatbot.tsx       # island
│   │   │   │   ├── ProjectCard.astro
│   │   │   │   └── LangSwitcher.astro
│   │   │   ├── i18n/{es,en}.json
│   │   │   └── content.config.ts     # Content Collections schema
│   │   ├── public/
│   │   └── astro.config.mjs
│   │
│   └── api/                          # FastAPI (backend host)
│       ├── backend/                  # Fork of HiRag15k
│       │   ├── api/routes/
│       │   │   ├── chat.py           # extended with project routing
│       │   │   ├── projects.py       # /api/projects/* (reindex)
│       │   │   └── health.py
│       │   ├── rag/
│       │   │   ├── vector_store.py   # ChromaDB (unchanged)
│       │   │   ├── project_router.py # NEW: list vs detail
│       │   │   ├── retriever.py      # extended with metadata filter
│       │   │   ├── llm_client.py
│       │   │   └── prompts.py        # NEW: bilingual prompts
│       │   └── services/
│       │       ├── chat_service.py   # extended
│       │       └── projects_service.py # NEW: reindex
│       ├── data/
│       │   ├── projects/             # source of truth .md files
│       │   │   └── proj-*.md
│       │   └── chroma/               # gitignored
│       ├── tests/                    # extended
│       └── requirements.txt
│
├── scripts/
│   ├── add_project.py                # interactive CLI
│   ├── reindex.py                    # rebuild ChromaDB
│   └── deploy.sh                     # portable deploy script
│
├── docs/
│   ├── plans/
│   │   ├── 2026-09-17-portafolio-rag-design.md     # this doc
│   │   └── 2026-09-17-portafolio-rag-impl-plan.md  # implementation plan
│   └── deploy/
│       └── <host>.md                 # deploy guide (per host)
│
├── .gitignore
└── README.md
```

**Single source of truth**: `.md` files live in `apps/api/data/projects/`. Astro reads them via Content Collections pointing at that path (synchronized at build time).

## 5. Project format

```markdown
---
slug: proj-data-pipeline
title_es: Pipeline de datos en tiempo real
title_en: Real-time data pipeline
year: 2024
role_es: Tech Lead
role_en: Tech Lead
client: Banco X (NDA)
tags: [python, aws, kafka, spark, data-engineering, senior]
stack_es: [Python, AWS (Kinesis, Lambda, S3), Kafka, Spark, Terraform]
stack_en: [Python, AWS (Kinesis, Lambda, S3), Kafka, Spark, Terraform]
summary_es: Pipeline that processes 50M events/day with < 5s latency and reduces costs 40% vs. previous solution.
summary_en: Pipeline processing 50M events/day with < 5s latency and 40% cost reduction vs. previous solution.
impact_es:
  - Reduced latency from 30 minutes to < 5 seconds
  - Saved ~$15K USD/month in infrastructure
  - Processes 50M events/day with 99.95% uptime
impact_en:
  - Reduced latency from 30 minutes to < 5 seconds
  - Saved ~$15K USD/month in infrastructure
  - Processes 50M events/day with 99.95% uptime
links:
  repo: null
  demo: null
---

## Contexto / Context

[Bilingual sections separated by headers. The bot decides which language to surface based on user locale.]

## Decisiones técnicas / Technical decisions

## Lecciones aprendidas / Lessons learned
```

## 6. Bot flow

### End-to-end example

**Visitor**: *"¿Qué proyectos hiciste con Python y AWS en los últimos 2 años?"*

1. **Astro (Vercel)** receives the query, the `Chatbot` island POSTs to `https://api.tudominio.com/api/chat/stream`
2. **Cloudflare Tunnel** routes to **FastAPI on the backend host**
3. **RouterService** receives the query:
   - Detects it's a "listing" query (no specific project mentioned)
   - Loads `projects_index` (ChromaDB collection with metadata of all projects)
   - Retrieves top-5 projects by relevance (filter: `tags contains "python" AND "aws" AND year >= 2025`)
4. **LLMClient** generates streaming response:
   - Prose: "En los últimos 2 años trabajé en 3 proyectos que combinan Python y AWS..."
   - At the end, an event `{"type":"projects","items":[...]}` with the 3 projects
5. **Chatbot (React island)** receives the stream:
   - Renders the prose as markdown
   - Renders the list as clickable `<ProjectCard>` components
   - On click → navigates to `/proyectos/proj-data-pipeline`

**Visitor (turn 2)**: *"Contame más del primero"*

1. The `Chatbot` sends the conversation history (6 turns max in the prompt)
2. **RouterService** detects a specific project reference ("el primero" → resolves to slug)
3. Loads `projects/proj-data-pipeline` (detail collection)
4. **LLMClient** responds with project detail
5. Renders as markdown

### API contract

#### `POST /api/chat/stream`

**Request**:
```json
{
  "question": "¿Qué proyectos hiciste con Python y AWS?",
  "lang": "es",
  "session_id": "uuid-v4",
  "history": [
    {"role":"user","content":"Hola"},
    {"role":"assistant","content":"¡Hola! ¿En qué puedo ayudarte?"}
  ]
}
```

**Response** (SSE events):
- `{"type":"content","text":"..."}` — prose in chunks (streaming)
- `{"type":"projects","items":[{"slug":"...","title":"...","summary":"...","relevance":0.92}]}` — structured list at the end
- `{"type":"done"}` — close
- `{"type":"error","code":"...","message":"..."}` — error

#### `POST /api/projects/reindex`

Re-ingest all `.md` files into ChromaDB.

**Request**: `{"force": false}`
**Response**: `{"ok": true, "indexed_projects": 12, "duration_ms": 3400}`

#### `GET /api/projects`

List metadata of all projects (used by Astro Content Collections).

**Response**: `{"projects": [{slug, title_es, title_en, year, tags, ...}]}`

## 7. Hosting — deferred decision

The backend hosting is deferred until the deploy phase. Candidates to evaluate:

| Option | Cost | Pros | Cons |
|---|---|---|---|
| **Hetzner CX22** (FSN1) | €4.68/mo | 4 vCPU, 8 GB RAM, 100 GB SSD, predictable | Not free |
| **AWS Free Tier** | Free 12mo, then ~$8-10/mo | Familiar, generous free tier | Free expires, then costs add up |
| **Oracle Cloud Ampere A1** (Always Free) | $0 | Up to 4 OCPU + 24 GB RAM free forever | Capacity hard to get |
| **Fly.io / Railway / Render** | Free tier or $5/mo hobby | Easy deploys | Less generous than Oracle |
| **Self-host on existing infra** | $0 | Zero new deps | Depends on what user already has |

**Decision criteria at deploy time**:
- Concurrent traffic expected (portfolio is low-traffic, so any option handles it)
- User preference on free vs. paid
- Setup complexity vs. operational burden

The architecture is **host-agnostic**: any Linux with Python 3.11 + ChromaDB runs it. The deploy script (`scripts/deploy.sh`) is portable.

## 8. Default recommendations

These are assumed unless the user changes them:

- **Multi-turn**: 6 turns of history in the prompt. `session_id` stored in `sessionStorage`. Enough context without bloating tokens.
- **CLI `add-project`**: Python script that prompts for slug, title ES/EN, tags, year, stack, summary → creates `apps/api/data/projects/<slug>.md` from a skeleton.
- **Analytics**: none initially. Add Plausible self-hosted or Umami later if needed (both free, GDPR-friendly).
- **Repo**: likely public (open source is good for a dev portfolio; recruiters look at it). If NDAs are sensitive, private repo with sanitized detail pages.
- **SSL**: Cloudflare Tunnel (no open ports, automatic SSL).
- **Backups**: daily cron copying `./data/chroma/` to Object Storage (Hetzner or Cloudflare R2 free tier).

## 9. Architecture decisions record (ADR)

### ADR-001: Why Astro + FastAPI over Next.js fullstack

- **Context**: Need a website with pre-rendered project pages + an interactive chatbot component.
- **Decision**: Astro 4.x for the site + FastAPI as a separate backend.
- **Consequences**:
  - Astro's content collections let us treat `.md` files with frontmatter as a first-class type-safe data source.
  - Astro's islands architecture means only the chat component ships JS — rest is pure HTML/CSS.
  - FastAPI is the same stack as HiRag15k, so reuse is ~95%.
  - The downside: two deploy targets, two domains (or one with `/api/*` proxy).
  - Alternative considered: Next.js App Router would unify but would require rewriting the entire RAG layer in TS.

### ADR-002: Why master index + per-project collections

- **Context**: Bot needs to both list projects and describe a specific project.
- **Decision**: One `projects_index` collection with metadata + one collection per project.
- **Consequences**:
  - Two-step reasoning: index lookup → load detail collection. Predictable and testable.
  - Index collection stays small (one chunk per project, just metadata) → fast.
  - Detail collections are loaded on-demand → bounded memory.
  - The downside: more collections to manage (~10-50 for a portfolio).
  - Alternative considered: single collection with metadata filters — would require complex `where` clauses and less reliable relevance ranking.

### ADR-003: Why hybrid response (prose + structured list)

- **Context**: Bot must return both conversational UX and clickable cards.
- **Decision**: Stream prose, then emit a `{"type":"projects"}` event at the end.
- **Consequences**:
  - Visitor reads conversational answer ("I have 3 projects combining Python and AWS...").
  - Then sees clickable cards linking to detail pages.
  - Frontend renders both natively (markdown for prose, cards for list).
  - The downside: the LLM must be instructed to emit the structured event in a specific format (JSON block at the end).
  - Alternative considered: pure JSON response would be less conversational; pure markdown with embedded links would require parsing the stream.

## 10. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| ChromaDB corruption | Bot breaks | Daily backup to Object Storage + restore script |
| Backend host down | Bot unreachable | External healthcheck + alert + auto-restart |
| OpenAI API rate limit | Bot degraded | Fallback to canonical deflection + user-facing message |
| Embedding costs uncontrolled | Surprise bills | Cache embeddings + rate limit per IP |
| LLM hallucinates projects | Misleading output | Post-generation validation: list of valid slugs |
| i18n incomplete | Broken UX | Astro build fails if a required locale field is missing |
| Open source repo with NDA content | Legal risk | Repo private OR sanitized detail pages OR no NDA projects at all |

## 11. Estimated timeline

| Phase | Content | Estimated effort |
|---|---|---|
| 0 | Setup: fork HiRag15k as `apps/api`, scaffold Astro in `apps/web` | ½ day |
| 1 | Data: frontmatter schema, 3-5 example projects, Content Collections | 1 day |
| 2 | Indexing: `reindex.py`, master index + per-project collections | 1 day |
| 3 | Bot router: `ProjectRouter`, bilingual prompts, extended endpoints | 1-2 days |
| 4 | UI Astro: landing, listing, detail (static), i18n, switcher | 1-2 days |
| 5 | Chatbot component: SSE, render prose + cards, multi-turn | 1 day |
| 6 | Deploy: backend host setup, Cloudflare Tunnel, Vercel config | ½ day |
| 7 | E2E + polish: Playwright tests, error fallbacks, docs | 1 day |
| **Total** | | **~6-8 days of focused work** |

## 12. Open questions (revisit before deploy)

1. Backend host: pick from candidates in §7 based on actual needs.
2. Domain: which TLD? (`.com`, `.dev`, `.es`, `.io`, `.me`)
3. Recruiter contact: include email / LinkedIn in footer? CTA in chat?
4. Example projects: which 3-5 to seed initially?
5. Spanish vs. English voice: who's the primary visitor language? (impacts bot prompt tuning)

## 13. References

- HiRag15k base: `D:/desarrollo/2027/HiRag15k/` — FastAPI + ChromaDB + SSE chat
- HiRag15k design doc: `D:/desarrollo/2027/HiRag15k/docs/plans/2026-07-01-hirag15k-design.md`
- Astro docs: https://docs.astro.build/en/guides/content-collections/
- ChromaDB docs: https://docs.trychroma.com/
- Conventional commits: https://www.conventionalcommits.org/
