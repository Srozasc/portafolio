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

## Phases 1-7 (deferred)

See `docs/plans/2026-09-17-portafolio-rag-impl-plan.md` for full task breakdown.

Summary:

| Phase | Goal | Effort | Status |
| --- | --- | --- | --- |
| 1 | Data: frontmatter schema, example projects, Content Collections | 1 day | pending |
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
- Recr