# Portafolio RAG — Implementation Plan

**Companion to**: `2026-09-17-portafolio-rag-design.md`
**Date**: 2026-09-17
**Status**: Approved, ready to start
**Estimated total effort**: 6-8 days of focused work

---

## Overview

The implementation is split into **8 phases**, each producing a working slice of the system. Each phase ends with a work-unit commit and a verified outcome.

**Branch strategy** (from `git-mentor`, profile `solo-freelancer`):

- `main` — production
- `dev` — work branch (default for all phases below)

All commits follow conventional commits in English (no `Co-Authored-By`).

---

## Phase 0 — Setup (½ day)

**Goal**: Bootstrap the monorepo, fork HiRag15k, scaffold Astro.

### Tasks

- [ ] **T0.1** Initialize git in `D:/desarrollo/workspace/2027/portafolio/` with `main` as default
- [ ] **T0.2** Create `.gitignore` (Python, Astro, ChromaDB, .env, etc.)
- [ ] **T0.3** Create `README.md` with project overview, setup commands, link to design docs
- [ ] **T0.4** Create directory structure: `apps/`, `apps/web/`, `apps/api/`, `scripts/`, `docs/`
- [ ] **T0.5** Clone HiRag15k into `apps/api/` as the backend base
- [ ] **T0.6** Initialize Astro project in `apps/web/` with TypeScript and i18n
- [ ] **T0.7** Verify: `apps/api/.venv/bin/python -m pytest -q` passes (HiRag15k's 120 tests still green)
- [ ] **T0.8** Verify: `cd apps/web && pnpm dev` serves the Astro default page

### Acceptance criteria

- Repo has clean `main` branch with one commit
- Astro dev server runs on `localhost:4321`
- FastAPI dev server runs on `localhost:8000` with all HiRag15k tests passing
- `.gitignore` excludes `.venv`, `node_modules`, `dist`, `.astro`, `data/chroma/`, `.env`

### Commit

`chore(setup): bootstrap monorepo with Astro and HiRag15k fork`

---

## Phase 1 — Data schema (1 day)

**Goal**: Define the project frontmatter schema, write 3-5 example projects, wire Content Collections.

### Tasks

- [ ] **T1.1** Define TypeScript schema in `apps/web/src/content.config.ts` matching the design doc §5
- [ ] **T1.2** Create Zod schema with validation for all required fields (slug, title_es, title_en, year, tags, stack, summary)
- [ ] **T1.3** Define Astro collection pointing to `../api/data/projects/` (single source of truth)
- [ ] **T1.4** Create 3-5 example `.md` files in `apps/api/data/projects/` with realistic content (bilingual)
- [ ] **T1.5** Write example content covering different stacks: data engineering, web fullstack, cloud architecture
- [ ] **T1.6** Add slug pattern validation (`/^proj-[a-z0-9-]+$/`)
- [ ] **T1.7** Verify: `pnpm build` in `apps/web/` succeeds and reads the example projects
- [ ] **T1.8** Verify: invalid `.md` (missing slug) fails the build with clear error

### Acceptance criteria

- Astro Content Collections reads `.md` files from `apps/api/data/projects/`
- 3-5 projects are listed in `pnpm dev` page (placeholder UI for now)
- Invalid `.md` causes build failure with line number

### Commit

`feat(data): define project schema and seed example projects`

---

## Phase 2 — RAG indexing (1 day)

**Goal**: Implement the script that ingests projects into ChromaDB with master index + per-project collections.

### Tasks

- [ ] **T2.1** Create `apps/api/backend/services/projects_service.py` with `ingest_all(force: bool)` method
- [ ] **T2.2** Implement YAML frontmatter parser (use `python-frontmatter` or `pyyaml`)
- [ ] **T2.3** Implement `build_index_entry(project)` → returns a small chunk with title, summary, tags (this goes into `projects_index` collection)
- [ ] **T2.4** Implement `build_project_chunks(project)` → splits body into chunks with metadata (this goes into `projects/<slug>` collection)
- [ ] **T2.5** Wire to existing ChromaDB vector store (HiRag15k's `rag/vector_store.py`)
- [ ] **T2.6** Create `apps/api/scripts/reindex.py` CLI entry point with `--force` flag
- [ ] **T2.7** Add unit tests for `projects_service` (mock ChromaDB)
- [ ] **T2.8** Add integration test that re-indexes the 3-5 example projects and verifies collections
- [ ] **T2.9** Verify: `python scripts/reindex.py` creates `projects_index` collection with N entries and N per-project collections
- [ ] **T2.10** Verify: re-running with `--force` re-creates from scratch (idempotent)

### Acceptance criteria

- `reindex.py` works against HiRag15k's existing ChromaDB wrapper (no rewrite)
- `projects_index` collection has one entry per project
- One collection per project in `data/chroma/projects/<slug>/`
- All tests pass

### Commit

`feat(rag): add projects indexer with master and per-project collections`

---

## Phase 3 — Bot router (1-2 days)

**Goal**: Extend HiRag15k's chat endpoint with project-aware routing (list vs. detail).

### Tasks

- [ ] **T3.1** Create `apps/api/backend/rag/project_router.py` with `route(question, history) → RouteDecision` class
- [ ] **T3.2** Implement `RouteDecision` types: `LIST_PROJECTS`, `DETAIL_PROJECT(slug)`, `GENERAL` (fallback to index)
- [ ] **T3.3** Implement routing logic:
  - Detect "list" intent: question mentions tech/stack/role but no specific project name
  - Detect "detail" intent: question references a specific project by name/slug
  - Fallback to LIST if intent is unclear
- [ ] **T3.4** Extend `chat_service.py` to handle `RouteDecision`:
  - `LIST_PROJECTS` → query `projects_index`, generate prose + structured list event
  - `DETAIL_PROJECT(slug)` → load `projects/<slug>` collection, generate prose
  - `GENERAL` → query `projects_index` for general overview
- [ ] **T3.5** Create `apps/api/backend/rag/prompts.py` with bilingual system prompts (ES/EN)
- [ ] **T3.6** Update prompt to instruct LLM to emit a `{"projects":[...]}` JSON block at the end of listing responses
- [ ] **T3.7** Implement post-generation validation: parse the JSON block, validate slugs against known set, drop invalid
- [ ] **T3.8** Add multi-turn history support: accept `history` field from request, prepend to prompt
- [ ] **T3.9** Update `api/routes/chat.py` to accept new request schema (lang, session_id, history)
- [ ] **T3.10** Add SSE event type `projects` to the stream
- [ ] **T3.11** Write tests:
  - Unit tests for `ProjectRouter.route()` (mock LLM)
  - Unit tests for prompt formatting
  - Integration tests for `chat_service` with LIST/DETAIL/GENERAL routes
  - Integration tests for SSE event ordering
- [ ] **T3.12** Verify: `curl` against `/api/chat/stream` returns both content and projects events

### Acceptance criteria

- Bot correctly routes between list and detail intents
- Response stream emits `content` events followed by `projects` events
- Multi-turn history (up to 6 turns) is included in prompt
- Bilingual prompts work (lang field selects prompt language)
- All HiRag15k existing tests still pass

### Commit

`feat(chat): add project-aware routing and bilingual streaming responses`

---

## Phase 4 — Astro UI (1-2 days)

**Goal**: Build the static site — landing, project listing, project detail pages — with i18n.

### Tasks

- [ ] **T4.1** Configure `astro.config.mjs` with i18n ES/EN, content collections, integrations
- [ ] **T4.2** Create `apps/web/src/i18n/es.json` and `en.json` with UI strings (nav, buttons, labels)
- [ ] **T4.3** Create `apps/web/src/layouts/Base.astro` with header, footer, lang switcher
- [ ] **T4.4** Create `apps/web/src/components/LangSwitcher.astro`
- [ ] **T4.5** Create `apps/web/src/pages/index.astro` (landing with hero + intro to bot)
- [ ] **T4.6** Create `apps/web/src/pages/proyectos/index.astro` (project listing using Content Collections)
- [ ] **T4.7** Create `apps/web/src/pages/proyectos/[slug].astro` (project detail with bilingual sections, metadata sidebar, impact list)
- [ ] **T4.8** Create `apps/web/src/components/ProjectCard.astro` (used in listing and bot responses)
- [ ] **T4.9** Create `apps/web/src/pages/sobre-mi.astro` (about page, optional but nice)
- [ ] **T4.10** Add static styles (CSS or Tailwind — decide in T4.0; recommended: Tailwind via `@astrojs/tailwind`)
- [ ] **T4.11** Verify: `pnpm build` produces a static site with all pages
- [ ] **T4.12** Verify: language switcher toggles between `/es/...` and `/en/...`
- [ ] **T4.13** Verify: detail pages show bilingual content correctly

### Acceptance criteria

- Site builds static (`dist/` folder)
- All project detail pages exist (one per project `.md`)
- Language switcher works
- i18n strings are present in both `es.json` and `en.json`
- Visually clean and responsive (mobile + desktop)

### Commit

`feat(web): build static portfolio site with i18n and project pages`

---

## Phase 5 — Chatbot component (1 day)

**Goal**: Build the interactive chat island that talks to the backend via SSE.

### Tasks

- [ ] **T5.1** Decide island framework: React or Solid (recommended: React for ecosystem maturity)
- [ ] **T5.2** Add `@astrojs/react` integration (if React)
- [ ] **T5.3** Create `apps/web/src/components/Chatbot.tsx` with:
  - Message input + submit
  - Message list (user + assistant bubbles)
  - Loading state during streaming
- [ ] **T5.4** Implement SSE client using `fetch` + `ReadableStream` (no external SSE lib needed)
- [ ] **T5.5** Handle three event types: `content` (append to message), `projects` (render cards), `done` (close stream), `error` (show error)
- [ ] **T5.6** Maintain `session_id` in `sessionStorage`
- [ ] **T5.7** Maintain history in React state (up to 6 turns, sent with each request)
- [ ] **T5.8** Detect user locale from URL (`/es/...` or `/en/...`) and send as `lang` field
- [ ] **T5.9** Add `Chatbot` to `pages/index.astro` as an island
- [ ] **T5.10** Add error handling: retry button on connection failure, fallback message
- [ ] **T5.11** Add input sanitization (no XSS via SSE content; render markdown safely with a sanitizer)
- [ ] **T5.12** Verify: end-to-end chat works locally (Astro dev + FastAPI on localhost)
- [ ] **T5.13** Verify: cards in bot response link to correct `/proyectos/<slug>` pages
- [ ] **T5.14** Verify: language switcher triggers a new `lang` field in subsequent requests

### Acceptance criteria

- Chat works locally with full SSE flow
- Bot response renders prose + cards correctly
- Multi-turn conversation retains context
- Language switch propagates to bot
- Cards link to correct pages

### Commit

`feat(chat-ui): add interactive chatbot with SSE streaming and project cards`

---

## Phase 6 — Deploy setup (½ day)

**Goal**: Prepare for deployment (host decision deferred, but the setup is portable).

### Tasks

- [ ] **T6.1** Create `scripts/deploy.sh` with portable steps:
  - Pull latest code
  - `pip install -r requirements.txt`
  - Run `python scripts/reindex.py`
  - Restart systemd service
- [ ] **T6.2** Create `apps/api/systemd/portafolio.service` for systemd management
- [ ] **T6.3** Create `docs/deploy/generic-linux.md` with step-by-step guide for any Linux host
- [ ] **T6.4** Create Cloudflare Tunnel config (`cloudflared`) for SSL without open ports
- [ ] **T6.5** Document required env vars in `.env.example` (LLM_API_KEY, EMBEDDING_API_KEY, etc.)
- [ ] **T6.6** Add CORS config in FastAPI for Vercel domain
- [ ] **T6.7** Configure Vercel:
  - Build command: `cd apps/web && pnpm build`
  - Output directory: `apps/web/dist`
  - Root directory: `apps/web`
  - Environment variable: `PUBLIC_API_URL` pointing to backend host
- [ ] **T6.8** Verify: Vercel preview deploy succeeds
- [ ] **T6.9** Document the deployment process in `docs/deploy/`

### Acceptance criteria

- `scripts/deploy.sh` works on any fresh Ubuntu 22.04+ host
- Vercel auto-deploys from `main` branch
- Cloudflare Tunnel is documented as the recommended exposure method
- CORS allows Vercel domain

### Commit

`chore(deploy): add portable deploy script and Vercel config`

---

## Phase 7 — E2E + polish (1 day)

**Goal**: Production-ready quality with tests, error handling, and docs.

### Tasks

- [ ] **T7.1** Install Playwright in `apps/web/`
- [ ] **T7.2** Write E2E test: visitor lands, opens chat, asks about Python, sees cards, clicks one, sees detail page
- [ ] **T7.3** Write E2E test: language switcher changes UI and bot language
- [ ] **T7.4** Add fallback content: if API is down, show static project listing + message
- [ ] **T7.5** Add rate limiting per IP in FastAPI (simple in-memory counter is fine for portfolio)
- [ ] **T7.6** Add healthcheck endpoint `/api/health` already exists; verify it returns useful info
- [ ] **T7.7** External healthcheck setup (UptimeRobot or Healthchecks.io — document only)
- [ ] **T7.8** Add robots.txt and sitemap.xml
- [ ] **T7.9** Add Open Graph and Twitter card meta tags to detail pages
- [ ] **T7.10** Add favicon and meta images
- [ ] **T7.11** Write `README.md` updates with screenshots, demo link, deploy instructions
- [ ] **T7.12** Final test pass: all backend + frontend + e2e tests green

### Acceptance criteria

- All tests pass (backend unit + integration + frontend e2e)
- Site is SEO-friendly (meta tags, sitemap, robots)
- Site has graceful fallback when API is down
- README is complete with setup + deploy instructions
- Site is ready for production deploy

### Commit

`chore(polish): add e2e tests, seo meta, fallbacks, and final docs`

---

## Cross-phase concerns

### Documentation to keep updated

- `README.md` — top-level entry point
- `docs/plans/2026-09-17-portafolio-rag-design.md` — design doc (frozen after Phase 0)
- `docs/plans/2026-09-17-portafolio-rag-impl-plan.md` — this plan
- `docs/deploy/<host>.md` — deploy guide per host (created in Phase 6)
- `apps/api/README.md` — backend-specific docs (forked from HiRag15k)
- `apps/web/README.md` — frontend-specific docs

### Testing strategy

- **Backend**: Inherit HiRag15k's pytest conventions. Use real ChromaDB in `tmp_path`. Mock LLM via stub `LLMClient`. Tests live next to code (`tests/unit/`, `tests/integration/`).
- **Frontend**: Astro components are tested via build (no separate unit tests for now). E2E via Playwright against a running stack.
- **No live network calls in tests** — same constraint as HiRag15k.

### Security checklist

- [ ] No API keys in the repo (use `.env`, gitignored)
- [ ] CORS restricted to known origins
- [ ] User-supplied markdown rendered safely (no XSS via SSE content)
- [ ] Rate limiting on chat endpoint
- [ ] Cloudflare Tunnel exposes backend without opening ports
- [ ] Dependencies pinned to ranges (not exact pins, but bounded)

### Performance budget

- Initial page load: < 100 KB JS (Astro islands are tiny)
- Detail page: static HTML, < 50 KB
- Chat first response: < 2 s (P50), < 5 s (P95)
- ChromaDB query: < 200 ms (P95) for index, < 500 ms for detail

---

## Definition of done (per phase)

A phase is "done" when:

1. All tasks in the phase are checked off
2. All tests in scope pass
3. The work-unit commit is made with a clear conventional commit message
4. The README or relevant docs are updated to reflect any new commands/setup
5. The user can run the demo (or relevant slice) locally

---

## Risks per phase

| Phase | Risk | Mitigation |
| --- | --- | --- |
| 1 | Frontmatter validation too strict, breaks later | Start permissive, tighten gradually |
| 2 | ChromaDB chunking loses context | Tune `CHUNK_SIZE` and add section-aware splitter if needed |
| 3 | LLM doesn't emit structured JSON reliably | Use OpenAI's structured output mode or regex post-validation |
| 4 | i18n adds too much friction | Use simple `_es` / `_en` field naming, not nested locales |
| 5 | SSE parsing edge cases (chunked across packets) | Use a battle-tested parser or implement carefully with newline buffering |
| 6 | Backend host setup is fiddly | Document every step; use Cloudflare Tunnel to avoid nginx + certbot |
| 7 | E2E tests are flaky | Use Playwright's retry, isolate to CI later |

---

## After Phase 7

- Decide backend host (see design doc §7) and run `scripts/deploy.sh`
- Configure domain DNS to point to Vercel (frontend) and Cloudflare Tunnel (backend)
- Monitor healthcheck for 1 week before announcing publicly
- Iterate based on analytics (if added later)

---

## Backlog (not in scope for v1)

- Analytics (Plausible / Umami)
- RSS feed of project updates
- Public API for embedding project data in other sites
- Admin UI to add projects without writing `.md` by hand
- Project gallery / image carousel in detail pages
- Testimonials / recommendations section
- Skills graph visualization

These can be added in v2 once v1 is stable and deployed.
