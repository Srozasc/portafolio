# Feature: Portafolio RAG

**Status**: Phase 0 in progress
**Started**: 2026-09-17
**Branch**: `dev` (Phase 0+ work)
**Sources**:
- Design: `docs/plans/2026-09-17-portafolio-rag-design.md`
- Impl plan: `docs/plans/2026-09-17-portafolio-rag-impl-plan.md`

## Goal

Bilingual (ES/EN) professional portfolio navigable by chatbot with RAG. Astro frontend + FastAPI backend (fork of HiRag15k) + ChromaDB.

**Audience**: technical recruiters filtering by stack.

## Strategy

- Monorepo with `apps/web/` (Astro) + `apps/api/` (FastAPI)
- Project content as `.md` files with YAML frontmatter (single source of truth)
- Two-step RAG: master index for listing → per-project collection for detail
- Backend host deferred to deploy phase (architecture is host-agnostic)

## Phase 0 — Setup (½ day) — DONE

Commit: see git log on `dev` (Phase 0 commit, SHA recorded at commit time).

Branch: `dev`. All work on `dev` until Phase 7 closes and PR to `main`.

Branch: `dev`. All work on `dev` until Phase 7 closes and PR to `main`.

- [ ] **T0.1** Create `dev` branch from `main` (work branch for solo-freelancer profile)
- [ ] **T0.2** Create monorepo skeleton: `apps/web/`, `apps/api/`, `scripts/`
- [ ] **T0.3** Create `apps/api/` skeleton (placeholder until HiRag15k is incorporated)
- [ ] **T0.4** Create `apps/web/` skeleton (placeholder until Astro is scaffolded)
- [ ] **T0.5** Incorporate HiRag15k into `apps/api/` as the backend base — DELEGATE to `gentle-ai-explore` for strategy, then `gentle-ai-worker` for execution
- [ ] **T0.6** Scaffold Astro in `apps/web/` with TypeScript + i18n — DELEGATE to `gentle-ai-worker`
- [ ] **T0.7** Verify: `apps/api/.venv/bin/python -m pytest -q` passes (HiRag15k 120 tests green) — DELEGATE to `gentle-ai-verify`
- [ ] **T0.8** Verify: `cd apps/web && pnpm dev` serves Astro page — DELEGATE to `gentle-ai-verify`

### Acceptance criteria Phase 0

- [ ] `dev` branch created and checked out
- [ ] `apps/web/`, `apps/api/`, `scripts/` directories exist
- [ ] HiRag15k code is present under `apps/api/` (fork strategy decided and documented)
- [ ] Astro project scaffolded in `apps/web/` with TypeScript strict and i18n config
- [ ] All HiRag15k tests pass when run from `apps/api/`
- [ ] Astro dev server serves a page on `localhost:4321`
- [ ] `.gitignore` continues to exclude `.venv/`, `node_modules/`, `data/chroma/`, `.env`
- [ ] Work-unit commit on `dev` with conventional commit message

### Commit (Phase 0)

`chore(setup): bootstrap monorepo with Astro and HiRag15k fork`

---

## Phase 1 — Data schema (1 day) — DONE

Commit: see git log on `dev` (Phase 1 commit, SHA recorded at commit time).

- [x] **T1.1** Enable Astro Content Layer experimental flag in `apps/web/astro.config.mjs`
- [x] **T1.2** Define Zod schema in `apps/web/src/content/config.ts` (bilingual fields)
- [x] **T1.3** Configure glob loader to read from `apps/api/data/projects/`
- [x] **T1.4-T1.5** Seed 5 example project .md files (bilingual, realistic content)
- [x] **T1.6** Add slug pattern validation ` /^proj-[a-z0-9-]+$/`
- [x] **T1.7-T1.8** Verify: `npm run build` green + invalid .md fails with clear error

### Acceptance criteria Phase 1

- [x] Astro Content Layer enabled via experimental flag
- [x] Zod schema validates all bilingual fields
- [x] glob loader points to `apps/api/data/projects/` (single source of truth)
- [x] 5 example projects seeded with realistic content (data-pipeline, rag-customer, cloud-migration, ml-scoring, realtime-fraud)
- [x] `npm run build` green (3 routes × 2 locales = 6 HTML files)
- [x] Sanity check: invalid slug rejected with clear error pointing to file:field:line
- [x] Work-unit commit on `dev`

### Decisions documented for future phases

- **Astro 4 convention used (`src/content/config.ts`), not Astro 5 (`src/content.config.ts`)**: Astro 4.16.19 only loads the former. Migration to Astro 5 later will be a single `git mv`.
- **Astro Content Layer is experimental in Astro 4.16 but stable in Astro 5**: acceptable risk for our schema/markdown use case.
- **Glob path correction**: `'./apps/api/data/projects/'` would have resolved to `apps/web/apps/api/data/projects/` (wrong). Worker used `'../api/data/projects/'` which resolves correctly. Documented in a comment in `src/content/config.ts`.
- **Build only generated 3 routes × 2 locales = 6 HTMLs (not project detail pages)**: expected — Phase 4 will add `src/pages/proyectos/[slug].astro`. The Content Layer is loaded but no consumer page yet.
- **No slug uniqueness validation**: would need a custom check (e.g., in a pre-build hook). Defer until needed.

### Commit (Phase 1)

`feat(data): define project schema and seed example projects`

---

## Phase 2 — RAG indexing (1 day) — IN PROGRESS

- [ ] **T2.1** Create `apps/api/backend/services/projects_service.py` with `ingest_all(projects_dir, force)` method
- [ ] **T2.2** Add PyYAML to `requirements.txt`; implement frontmatter parser (split on `---`, yaml.safe_load for header)
- [ ] **T2.3** Implement `build_index_entry(project)` → returns small chunk with title_es/en, summary_es/en, tags as document + metadata for `projects_index` collection
- [ ] **T2.4** Implement `build_project_chunks(project)` → use existing `chunk_markdown` on body (after frontmatter), add per-chunk metadata (slug, year, source)
- [ ] **T2.5** Wire to existing `VectorStore` (`apps/api/backend/rag/vector_store.py`): delete-then-upsert for both index and detail collections
- [ ] **T2.6** Create `apps/api/scripts/reindex.py` CLI entry point with `--force` flag and `--projects-dir` (defaults to `apps/api/data/projects/`)
- [ ] **T2.7** Add `apps/api/backend/api/routes/projects.py` with `POST /api/projects/reindex` endpoint (uses same service)
- [ ] **T2.8** Add `ReindexRequest` / `ReindexResponse` schemas to `apps/api/backend/api/schemas.py`
- [ ] **T2.9** Unit tests: frontmatter parsing, build_index_entry, build_project_chunks, slug validation, error handling for malformed .md files
- [ ] **T2.10** Integration tests with real ChromaDB in tmp_path: re-ingest 5 projects, verify `projects_index` has 5 entries, verify 5 per-project collections exist
- [ ] **T2.11** Idempotency test: re-running with `--force` recreates from scratch (no stale chunks)

### Acceptance criteria Phase 2

- [ ] `scripts/reindex.py` works against existing VectorStore wrapper (no rewrite)
- [ ] `projects_index` collection has one entry per project (5 entries after seeding)
- [ ] One collection per project in `data/chroma/projects_<slug>/` (5 collections, named `projects_<slug>` because ChromaDB disallows `/` in collection names)
- [ ] Re-running with `--force` is idempotent (no stale data)
- [ ] Malformed .md file (missing frontmatter, invalid slug) → clear error logged, doesn't abort the batch
- [ ] All existing HiRag15k tests still pass (124 + new ones)
- [ ] HTTP endpoint `POST /api/projects/reindex` works (file is ready; wiring into main.py is Phase 3)

### Decisions documented

- **Index collection `projects_index`**: one chunk per project, document is a brief text combining title+summary+tags, metadata has all structured fields for filtering (slug, year, tags as JSON string, etc.)
- **Detail collections `projects_<slug>`**: chunks of the body via existing `chunk_markdown`, metadata has slug/source/year/chunk_index
- **Body language**: stored as-is (Spanish in our seed projects). No language separation at index time — the bot can filter or surface both as needed in Phase 3+.
- **Force flag**: deletes the relevant collections (index + each project's detail) before re-ingesting, ensuring idempotency.
- **Collection naming**: `/` is NOT allowed in ChromaDB collection names, so `projects/proj-foo` becomes `projects_proj-foo`.

### Commit (Phase 2)

`feat(rag): add projects indexer with master and per-project collections`

---

## Phase 3 — Bot router (1-2 days) — IN PROGRESS

- [ ] **T3.1** Create `apps/api/backend/rag/project_router.py` with `route(question, history, lang) → RouteDecision` and the `RouteDecision` types
- [ ] **T3.2** Implement `RouteDecision` types: `LIST_PROJECTS`, `DETAIL_PROJECT(slug)`, `GENERAL`
- [ ] **T3.3** Routing logic: detect list intent (tech/stack/role mentions) vs detail (specific project by slug or name) vs general fallback
- [ ] **T3.4** Extend `apps/api/backend/services/chat_service.py` to handle each `RouteDecision`:
  - `LIST_PROJECTS`: query `projects_index`, generate prose + emit `{"projects":[...]}` at end
  - `DETAIL_PROJECT(slug)`: load `projects_<slug>`, generate prose from detail chunks
  - `GENERAL`: query `projects_index` for general overview (broad relevance)
- [ ] **T3.5** Update `apps/api/backend/rag/prompts.py` with bilingual system prompts (ES + EN variants of SYSTEM_PROMPT_TEMPLATE)
- [ ] **T3.6** Update the prompt to instruct the LLM to emit a `{"projects":[...]}` JSON block at the very end of listing responses, with explicit format and example
- [ ] **T3.7** Post-generation validation: parse the JSON block, validate slugs against known set, drop invalid entries; if parse fails, log warning and continue with prose only (graceful degradation)
- [ ] **T3.8** Multi-turn history support: accept `history` field from request (list of {role, content}), include last 6 turns in the prompt, prepend to user message
- [ ] **T3.9** Update `apps/api/backend/api/routes/chat.py` to accept new request schema (`lang`, `session_id`, `history`)
- [ ] **T3.10** Emit SSE event `{"type":"projects","items":[...]}` when projects are extracted; ensure ordering is content → projects → done
- [ ] **T3.11** Tests: unit for ProjectRouter; integration for chat endpoint with LIST/DETAIL/GENERAL routes; verify event ordering; verify bilingual prompts; verify history propagation
- [ ] **T3.12** Verify via curl that streaming works for all 3 routes

### Acceptance criteria Phase 3

- [ ] `ProjectRouter.route()` correctly classifies list vs detail vs general
- [ ] `chat_service` emits SSE events in order: `content` chunks → `projects` event → `done`
- [ ] Bilingual prompts work (lang=es uses Spanish system prompt, lang=en uses English)
- [ ] Multi-turn history (up to 6 turns) is included in prompt
- [ ] Invalid slugs in the LLM's JSON output are dropped without aborting
- [ ] All HiRag15k baseline tests still pass (124 + new ones)
- [ ] New tests cover LIST/DETAIL/GENERAL routing and bilingual prompts

### Decisions documented

- **Routing is heuristic** (not LLM-based): list intent detected by tech/stack keywords; detail intent by slug mention or previous project reference in history; general fallback otherwise. Saves LLM call per query.
- **JSON extraction by regex** at the end of the streamed prose: prompt instructs LLM to emit a final `===PROJECTS===` block with JSON; chat_service post-processor parses it and emits as `projects` event.
- **Graceful degradation**: if JSON extraction fails, the prose is still emitted; no `projects` event is sent; client falls back to chat-only mode.
- **Multi-turn window of 6 turns** per the design doc §6.
- **Bilingual prompts as separate templates** (not parameterized strings) — simpler to maintain than runtime string interpolation.

### Commit (Phase 3)

`feat(chat): add project-aware routing and bilingual streaming responses`

---

## Phase 4 — Astro UI (1-2 days) — IN PROGRESS

- [ ] **T4.1-T4.4** i18n config + Base layout + LangSwitcher (already done in Phase 0)
- [ ] **T4.5** Update `apps/web/src/pages/index.astro` with real landing content (hero, featured projects, chatbot CTA placeholder)
- [ ] **T4.6** Update `apps/web/src/pages/proyectos/index.astro` with real listing (getCollection projects sorted by year, ProjectCard grid)
- [ ] **T4.7** Create `apps/web/src/pages/proyectos/[slug].astro` detail page (bilingual sections: title, summary, role, stack, impact list, body markdown)
- [ ] **T4.8** Create `apps/web/src/components/ProjectCard.astro` component (compact: title, year, role, summary, tags)
- [ ] **T4.9** Update `apps/web/src/pages/sobre-mi.astro` with real bio content (bilingual sections: bio, skills, contact links)
- [ ] **T4.10** Extend `apps/web/src/i18n/es.json` and `en.json` with new strings for the new sections
- [ ] **T4.11** Extend `apps/web/src/styles/global.css` for project detail styling (metadata sidebar, impact list, etc.)
- [ ] **T4.12** Verify: `npm run build` green (3 base routes × 2 locales + 5 detail pages × 2 locales = 22 HTMLs expected)
- [ ] **T4.13** Verify: language switcher toggles between /es/... and /en/...; detail pages show correct locale

### Acceptance criteria Phase 4

- [ ] `npm run build` produces 22 HTML files (or close — depending on Astro deduplication)
- [ ] Landing page shows real hero, featured projects, chatbot CTA placeholder
- [ ] Projects listing page shows all 5 projects as ProjectCard grid, sorted by year descending
- [ ] Project detail page renders bilingual content correctly (ES and EN variants)
- [ ] Detail page metadata sidebar shows: year, role, stack, impact, links
- [ ] Detail page body renders the markdown content as HTML
- [ ] LangSwitcher toggles between /es/proyectos/... and /en/proyectos/...
- [ ] All routes return 200 status when serving
- [ ] `astro check` (typecheck) passes

### Decisions documented

- **Keep simple CSS, no Tailwind**: extends existing `global.css` with project-detail styles. Tailwind adds dependency overhead for a 5-project site.
- **ProjectCard reuses across listing and bot responses**: same component used by `/proyectos/index.astro` and will be reused by the chatbot in Phase 5.
- **Detail page metadata sidebar**: right-aligned column with structured fields (year, role, stack as tags, impact as list). Body markdown on the left.
- **No [slug].astro for i18n variants**: Astro's i18n routing handles `/proyectos/[slug]` and `/en/proyectos/[slug]` automatically based on the prefix. The component reads `Astro.currentLocale` to select ES/EN fields.

### Commit (Phase 4)

`feat(web): build static portfolio site with i18n and project pages`

---

## Phases 2-7 (deferred)

See `docs/plans/2026-09-17-portafolio-rag-impl-plan.md` for full task breakdown.

Summary:

| Phase | Goal | Effort | Status |
| --- | --- | --- | --- |
| 1 | Data: frontmatter schema, example projects, Content Collections | 1 day | DONE |
| 2 | RAG indexing: master index + per-project collections | 1 day | pending |
| 3 | Bot router: ProjectRouter, bilingual prompts, extended endpoints | 1-2 days | pending |
| 4 | Astro UI: landing, listing, detail pages, i18n, switcher | 1-2 days | pending |
| 5 | Chatbot component: SSE, prose + cards, multi-turn | 1 day | pending |
| 6 | Deploy: backend host setup, Cloudflare Tunnel, Vercel config | ½ day | pending |
| 7 | E2E + polish: Playwright tests, SEO, fallbacks, docs | 1 day | pending |

## Risks

See `docs/plans/2026-09-17-portafolio-rag-design.md` §10 for the full risk register. Highlights:

- Backend host decision deferred — re-evaluate at Phase 6
- ChromaDB persistence in 1 GB RAM environments (Oracle Micro) — swap + tuning if needed
- LLM structured output reliability — regex post-validation if needed

## Delegation plan

Per `el Gentleman` orchestrator rules:

- **gentle-ai-explore**: T0.5 (map HiRag15k, recommend fork strategy)
- **gentle-ai-worker**: T0.5 execution, T0.6 (scaffold Astro)
- **gentle-ai-verify**: T0.7, T0.8 (test + dev server verification)

Parent session keeps orchestration only: task tracking, decisions, commit orchestration, memory.

## Definition of done (this feature)

- All 8 phases complete
- All tests pass (backend unit + integration + frontend E2E)
- Site deployed and accessible via public URL
- Recruiter can chat, get project recommendations, click through to detail pages
- i18n works in both ES and EN
- README updated with live demo link
