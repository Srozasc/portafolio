# Feature: Portafolio RAG

**Status**: Phases 0–4 done; Phase 5 pending
**Started**: 2026-09-17
**Branch**: `dev` (work branch, all phases land here until PR to `main` at Phase 7)
**Sources**:

- Design: `docs/plans/2026-09-17-portafolio-rag-design.md`
- Impl plan: `docs/plans/2026-09-17-portafolio-rag-impl-plan.md`

## Commits landed on `dev`

| Phase | Commit SHA | Subject |
| --- | --- | --- |
| 0 | `9ce36c3` | `chore(setup): bootstrap monorepo with Astro and HiRag15k fork` |
| docs | `a7aae6f` | `docs(tasks): mark Phase 0 done and note deferred items` |
| 1 | `474a2fd` | `feat(data): define project schema and seed example projects` |
| 2 | `f7ee339` | `feat(rag): add projects indexer with master and per-project collections` |
| 3 | `f5f6381` | `feat(chat): add project-aware routing and bilingual streaming responses` |
| 4 | `250c43d` | `feat(web): build static portfolio site with i18n and project pages` |

Baseline verified before Phase 5: backend 201 pytest passing in ~30s; `astro build` direct (bypassing `pnpm` install hook) produces 8 HTML pages across ES + EN.

> **Note on acceptance criteria**: per-phase task checklists (`T0.x` … `T4.x`) are crossed off because the commits exist and the work landed. The granular `### Acceptance criteria Phase X` lists below stay **open** as pending human-verification checks (e.g. manual QA of the landing page, type-check `astro check`, smoke test of the reindex CLI). They will be crossed individually during the Phase 7 polish pass.

## Goal

Bilingual (ES/EN) professional portfolio navigable by chatbot with RAG. Astro frontend + FastAPI backend (fork of HiRag15k) + ChromaDB.

**Audience**: technical recruiters filtering by stack.

## Strategy

- Monorepo with `apps/web/` (Astro) + `apps/api/` (FastAPI)
- Project content as `.md` files with YAML frontmatter (single source of truth)
- Two-step RAG: master index for listing → per-project collection for detail
- Backend host deferred to deploy phase (architecture is host-agnostic)

## Phase 0 — Setup (½ day) — DONE

Commit: `9ce36c3`.

- [x] **T0.1** Create `dev` branch from `main` (work branch for solo-freelancer profile)
- [x] **T0.2** Create monorepo skeleton: `apps/web/`, `apps/api/`, `scripts/`
- [x] **T0.3** Create `apps/api/` skeleton (placeholder until HiRag15k is incorporated)
- [x] **T0.4** Create `apps/web/` skeleton (placeholder until Astro is scaffolded)
- [x] **T0.5** Incorporate HiRag15k into `apps/api/` as the backend base — DELEGATE to `gentle-ai-explore` for strategy, then `gentle-ai-worker` for execution
- [x] **T0.6** Scaffold Astro in `apps/web/` with TypeScript + i18n — DELEGATE to `gentle-ai-worker`
- [x] **T0.7** Verify: `apps/api/.venv/Scripts/python.exe -m pytest -q` passes (HiRag15k 120 tests green) — DELEGATE to `gentle-ai-verify`. **Note**: venv structure is `Scripts/` (Windows) not `bin/` (Unix). Use `.venv/Scripts/python.exe` in this environment.
- [x] **T0.8** Verify: `cd apps/web && astro dev` serves Astro page — DELEGATE to `gentle-ai-verify`. **Note**: see Phase 4 decision below about `pnpm` vs direct `astro` invocation.

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
- [x] **T1.6** Add slug pattern validation `/^proj-[a-z0-9-]+$/`
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

## Phase 2 — RAG indexing (1 day) — DONE

Commit: `f7ee339`.

- [x] **T2.1** Create `apps/api/backend/services/projects_service.py` with `ingest_all(projects_dir, force)` method
- [x] **T2.2** Add PyYAML to `requirements.txt`; implement frontmatter parser (split on `---`, yaml.safe_load for header)
- [x] **T2.3** Implement `build_index_entry(project)` → returns small chunk with title_es/en, summary_es/en, tags as document + metadata for `projects_index` collection
- [x] **T2.4** Implement `build_project_chunks(project)` → use existing `chunk_markdown` on body (after frontmatter), add per-chunk metadata (slug, year, source)
- [x] **T2.5** Wire to existing `VectorStore` (`apps/api/backend/rag/vector_store.py`): delete-then-upsert for both index and detail collections
- [x] **T2.6** Create `apps/api/scripts/reindex.py` CLI entry point with `--force` flag and `--projects-dir` (defaults to `apps/api/data/projects/`)
- [x] **T2.7** Add `apps/api/backend/api/routes/projects.py` with `POST /api/projects/reindex` endpoint (uses same service)
- [x] **T2.8** Add `ReindexRequest` / `ReindexResponse` schemas to `apps/api/backend/api/schemas.py`
- [x] **T2.9** Unit tests: frontmatter parsing, build_index_entry, build_project_chunks, slug validation, error handling for malformed .md files
- [x] **T2.10** Integration tests with real ChromaDB in tmp_path: re-ingest 5 projects, verify `projects_index` has 5 entries, verify 5 per-project collections exist
- [x] **T2.11** Idempotency test: re-running with `--force` recreates from scratch (no stale chunks)

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

## Phase 3 — Bot router (1-2 days) — DONE

Commit: `f5f6381`.

- [x] **T3.1** Create `apps/api/backend/rag/project_router.py` with `route(question, history, lang) → RouteDecision` and the `RouteDecision` types
- [x] **T3.2** Implement `RouteDecision` types: `LIST_PROJECTS`, `DETAIL_PROJECT(slug)`, `GENERAL`
- [x] **T3.3** Routing logic: detect list intent (tech/stack/role mentions) vs detail (specific project by slug or name) vs general fallback
- [x] **T3.4** Extend `apps/api/backend/services/chat_service.py` to handle each `RouteDecision`:
  - `LIST_PROJECTS`: query `projects_index`, generate prose + emit `{"projects":[...]}` at end
  - `DETAIL_PROJECT(slug)`: load `projects_<slug>`, generate prose from detail chunks
  - `GENERAL`: query `projects_index` for general overview (broad relevance)
- [x] **T3.5** Update `apps/api/backend/rag/prompts.py` with bilingual system prompts (ES + EN variants of SYSTEM_PROMPT_TEMPLATE)
- [x] **T3.6** Update the prompt to instruct the LLM to emit a `{"projects":[...]}` JSON block at the very end of listing responses, with explicit format and example
- [x] **T3.7** Post-generation validation: parse the JSON block, validate slugs against known set, drop invalid entries; if parse fails, log warning and continue with prose only (graceful degradation)
- [x] **T3.8** Multi-turn history support: accept `history` field from request (list of {role, content}), include last 6 turns in the prompt, prepend to user message
- [x] **T3.9** Update `apps/api/backend/api/routes/chat.py` to accept new request schema (`lang`, `session_id`, `history`)
- [x] **T3.10** Emit SSE event `{"type":"projects","items":[...]}` when projects are extracted; ensure ordering is content → projects → done
- [x] **T3.11** Tests: unit for ProjectRouter; integration for chat endpoint with LIST/DETAIL/GENERAL routes; verify event ordering; verify bilingual prompts; verify history propagation
- [x] **T3.12** Verify via curl that streaming works for all 3 routes

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

## Phase 4 — Astro UI (1-2 days) — DONE

Commit: `250c43d`.

- [x] **T4.1-T4.4** i18n config + Base layout + LangSwitcher (already done in Phase 0)
- [x] **T4.5** Update `apps/web/src/pages/index.astro` with real landing content (hero, featured projects, chatbot CTA placeholder)
- [x] **T4.6** Update `apps/web/src/pages/proyectos/index.astro` with real listing (getCollection projects sorted by year, ProjectCard grid)
- [x] **T4.7** Create `apps/web/src/pages/proyectos/[slug].astro` detail page (bilingual sections: title, summary, role, stack, impact list, body markdown)
- [x] **T4.8** Create `apps/web/src/components/ProjectCard.astro` component (compact: title, year, role, summary, tags)
- [x] **T4.9** Update `apps/web/src/pages/sobre-mi.astro` with real bio content (bilingual sections: bio, skills, contact links)
- [x] **T4.10** Extend `apps/web/src/i18n/es.json` and `en.json` with new strings for the new sections
- [x] **T4.11** Extend `apps/web/src/styles/global.css` for project detail styling (metadata sidebar, impact list, etc.)
- [x] **T4.12** Verify: `astro build` green (8 HTMLs — 3 base routes + 5 detail pages, Astro deduplicates across ES/EN). **Note**: see "pnpm build issue" decision below.
- [x] **T4.13** Verify: language switcher toggles between /es/... and /en/...; detail pages show correct locale

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
- **pnpm build issue (deferred from Phase 4, to be fixed in Phase 5 housekeeping)**: `pnpm build` fails on pnpm 11 because it auto-runs `pnpm install` with `onlyBuiltDependencies` defaulting to empty, so esbuild/sharp are blocked from running their install scripts. Workaround used so far: invoke `node_modules/.bin/astro build` directly, bypassing `pnpm`. The fix is to add `pnpm.onlyBuiltDependencies: ["esbuild", "sharp"]` to `apps/web/package.json` — tracked as Phase 5 prerequisite task.

### Commit (Phase 4)

`feat(web): build static portfolio site with i18n and project pages`

---

## Phase 5 — Chatbot component (1 day) — IN PROGRESS

Branch: `dev`. Sub-tasks tracked in `todo`.

- [ ] **T5.1** Confirm React island (already chosen; `@astrojs/react` 3.6.3 installed)
- [ ] **T5.2** Confirm `@astrojs/react` integration wired in `apps/web/astro.config.mjs`
- [ ] **T5.3** Create `apps/web/src/components/Chatbot.tsx` with message input + submit, message list (user + assistant bubbles), loading state
- [ ] **T5.4** Implement SSE client using `fetch` + `ReadableStream` (no external SSE lib)
- [ ] **T5.5** Handle SSE event types: `content` (append to assistant message), `projects` (render cards), `done` (close), `error` (show error)
- [ ] **T5.6** Maintain `session_id` in `sessionStorage` (UUID v4, lazy init)
- [ ] **T5.7** Maintain history in React state, cap at 6 turns; send with each request
- [ ] **T5.8** Detect user locale from URL (`/es/...` or `/en/...`) and send as `lang` field; react to locale change
- [ ] **T5.9** Add `Chatbot` to `apps/web/src/pages/index.astro` as an island (`client:load` or `client:visible`)
- [ ] **T5.10** Error handling: retry button on connection failure, fallback message when API down
- [ ] **T5.11** Render markdown safely (XSS-safe; decide approach in Phase 5 kickoff)
- [ ] **T5.12** Verify end-to-end chat works locally (Astro dev + FastAPI uvicorn on localhost)
- [ ] **T5.13** Verify cards link to correct `/proyectos/<slug>` pages
- [ ] **T5.14** Verify language switcher triggers new `lang` field in subsequent requests

### Acceptance criteria Phase 5

- [ ] Chat island mounted on `/` and `/<locale>/` (landing page)
- [ ] Full SSE flow works locally against running FastAPI
- [ ] Assistant message renders prose + project cards correctly
- [ ] Multi-turn conversation retains context (last 6 turns sent)
- [ ] Language switch propagates to bot on next request
- [ ] Cards link to correct project detail pages
- [ ] `session_id` persists across reloads within the same tab
- [ ] Connection failures show a retry button, not a crash
- [ ] No XSS via SSE content (markdown rendered safely)

### Decisions to document (during Phase 5)

- **Markdown rendering library** (TBD in kickoff): `react-markdown` vs raw text + line breaks
- **Backend URL config** (TBD in kickoff): `PUBLIC_API_URL` env var vs Astro proxy in dev
- **Island hydration**: `client:load` vs `client:visible` vs `client:idle`
- **Error UX shape**: inline error message + retry button vs toast
- **ProjectCard reuse**: same Astro component as the listing page (rendered inside React island via `set:html` is awkward — likely need a small React-native card component that mirrors the Astro one)

### Commit (Phase 5)

`feat(chat-ui): add interactive chatbot with SSE streaming and project cards`

---

## Phases 6-7 (pending)

See `docs/plans/2026-09-17-portafolio-rag-impl-plan.md` for full task breakdown.

Summary:

| Phase | Goal | Effort | Status |
| --- | --- | --- | --- |
| 1 | Data: frontmatter schema, example projects, Content Collections | 1 day | DONE |
| 2 | RAG indexing: master index + per-project collections | 1 day | DONE |
| 3 | Bot router: ProjectRouter, bilingual prompts, extended endpoints | 1-2 days | DONE |
| 4 | Astro UI: landing, listing, detail pages, i18n, switcher | 1-2 days | DONE |
| 5 | Chatbot component: SSE, prose + cards, multi-turn | 1 day | IN PROGRESS |
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
