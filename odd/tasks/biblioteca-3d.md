# Biblioteca 3D — feature task

Branch: `feat/biblioteca-3d` (created from `main` at `08795b5`).
Base head note: `08795b5` is "Merge pull request #16 from Srozasc/feat/3d-library-experiment", so the prototype at `experiments/chat-3d-library.html` is already in `main`. No cherry-pick of `origin/feat/3d-library-experiment` is needed before implementation.

## Specs

S1: The feature carries the canonical label **"Modo Biblioteca 3D"** (verbatim from the user's task description: "a new 'Biblioteca 3D' feature"; candidate label "Modo Biblioteca 3D" surfaced by the user). The label appears on three surfaces: the new navbar link, the new hero CTA, and the page title. Verified clean slate: this string does not exist anywhere in `apps/web/src/i18n/es.json` or `apps/web/src/i18n/en.json` (grep for `biblioteca|Modo Biblioteca|Library|3D` returned no matches in either file). EN mirror wording is left to the translator's discretion but conventionally would be **"3D Library"**.

S2: Dedicated routes serve the 3D scene — **`/biblioteca-3d`** (ES, no locale prefix per `astro.config.mjs` `prefixDefaultLocale: false`) and **`/en/biblioteca-3d`** (EN mirror, explicit). Routes follow the same `explicit '/index.html' suffix` convention used in `apps/web/src/layouts/Base.astro` (lines 30–32 + inline comment "CloudFront + S3 do not auto-serve `index.html` for directory URLs (the Astro default trailing-slash URL style would otherwise 403 on the bucket with Block Public Access + OAC)"). The EN mirror must be an explicit Astro page because `astro.config.mjs` sets `fallback: { en: 'es' }`; without an explicit page, `/en/biblioteca-3d` would redirect visitors to the ES equivalent before the page even rendered.

S3: Three.js isolation, verbatim directive **`client:only="react"`** (user's exact words). The scene component is rendered only when the visitor enters `/biblioteca-3d` (or its EN mirror). Three.js MUST NOT enter the main bundle or the LCP path of `/`, `/proyectos/`, `/sobre-mi/`, or `/en/*`. Project metadata for the scene is **baked at build time** by calling `getCollection('projects')` from inside the Astro page (data source: `apps/web/src/content/config.ts` line 14, pattern `**/*.md` from `../api/data/projects/` — same source as the FastAPI backend RAG index). The scene does not call `/api/chat/stream-projects` or any other endpoint at runtime.

S4: A fourth link in the navbar of `apps/web/src/layouts/Base.astro`, appended after the existing `<li>` for `t.nav.about`. Current navbar items (verbatim from `t.nav.*` in `apps/web/src/i18n/es.json` lines 4–8): **"Inicio"**, **"Proyectos"**, **"Sobre mí"** — the new link sits next to them. URL helper is a new `bibliotecaPath` const inside the existing locale-aware block (Base.astro lines 30–32), following the same `locale === 'en' ? '/en/biblioteca-3d/index.html' : '/biblioteca-3d/index.html'` pattern used by `homePath`, `projectsPath`, `aboutPath`.

S5: A third CTA in the hero of `apps/web/src/pages/index.astro`, inside the existing `<p class="ctas">` (currently lines 27–28 holding **"Preguntale al bot"** = `t.home.cta.chat` and **"Ver proyectos"** = `t.home.cta.projects`). User said: a "tertiary button under the existing 'Preguntale al bot' + 'Ver proyectos' pair". New key `home.cta.biblioteca`, new CSS class `.cta.tertiary` (style block lives next to the existing `.cta.primary` / `.cta.secondary` rules around lines 47–63). URL helper is a new `bibliotecaHref` const, mirroring the existing `projectsHref` pattern (index.astro line 13).

S6: Chatbot FAB reuse. The `Chatbot` component at `apps/web/src/components/Chatbot.tsx` is mounted globally by `Base.astro` with `<Chatbot client:load transition:persist>` (Base.astro lines 121–123, with explanatory comment on lines 116–120 about persistence across View Transitions). Because it lives in the layout, it is **already on every page including `/biblioteca-3d`**, with zero wiring work. The chat continues to use `/api/chat/stream-projects` as before — no duplicate RAG client is created (matches user non-goal).

S7: **NO persistence layer** (user's exact rule: "NO persistence layer. Every visit lands on the standard site by default"). The `/biblioteca-3d` page performs zero `localStorage` / `sessionStorage` / `cookie` / `IndexedDB` reads or writes. No "remember me in 3D mode" preference. The nav link and hero CTA are plain `<a>` tags — no client-side preference state.

S8: **NO backend changes** (user's exact rule: "NO backend changes. Reuse the existing SSE endpoint /api/chat/stream-projects and the projects Content Collection"). `apps/api/` is not touched. The 3D scene receives its project list as a serialization-time prop from the Astro page (data source: `getCollection('projects')`, defined in `apps/web/src/content/config.ts`). The chat's SSE call (already wired inside `Chatbot.tsx`, never modified) continues to hit `/api/chat/stream-projects` unchanged.

S9: **Do not add localStorage / sessionStorage for the 3D mode entry choice** (verbatim user non-goal). This restates S7 with the specific API names; the implementation must not introduce either storage for any "user chose 3D once, land there next visit" semantics.

S10: **i18n keys come from the existing i18n JSON files** (verbatim rule). New keys live in `apps/web/src/i18n/es.json` and `apps/web/src/i18n/en.json`. Shape mirrors existing objects: e.g. `nav.biblioteca`, `home.cta.biblioteca` (sibling of `home.cta.chat` / `home.cta.projects` / `home.cta.all_projects`), and a new `biblioteca3d.{title,subtitle}` block (parallel to existing `proyectos.title/subtitle/empty` in `apps/web/src/i18n/es.json` lines 35–51).

S11: **Do not modify apps/web/src/components/Chatbot.tsx logic** (verbatim user non-goal). The component's existing props, RAG wiring, SSE handling, onboarding tutorial modal (lines 856–864 reference locale-aware fallbacks in Chatbot.tsx), welcome flow, and chat history are all left as-is. If a layout-side adjustment is needed (e.g. FAB visually overlaps the 3D canvas), it is handled in a parent Astro file, not in Chatbot.tsx.

S12: **Do not add anything to apps/api/** (verbatim user non-goal). No new endpoints, no schema changes, no RAG reindex, no new env vars.

S13: **Do not translate prototype content; i18n keys come from the existing i18n JSON files** (verbatim rule). The HTML prototype at `experiments/chat-3d-library.html` (2958 lines, `PROJECTS_CATALOG` literal at line 1070) is a self-contained reference document. Its internal Spanish strings stay Spanish. Only the **app-facing surface labels** (nav link, hero CTA, page title, document `<title>` tag) get a translated EN entry; scene-UX strings (loading, error, controls, scene legend) may live in the prototype language only.

S14: **No test infrastructure is wired for apps/web.** A single repo-wide grep for `vitest|playwright|jest|@testing-library|cypress` returned exactly four hits — none of them in `apps/web`: two matches inside `apps/api/data/projects/proj-safegateway.md` referencing `pnpm vitest run tests/unit/routing/matcher.test.ts` (the **API** project has vitest; **web** does not), and `.gitignore` lines 58–59 listing `.playwright/` and `playwright-report/` (historic leftovers, no current playwright install). `apps/web/package.json` has no `test` script and no test-framework dependency. TDD cannot run end-to-end on the web package without scope-expansion to install a runner; see T11.

## Tasks

T1: i18n key conflict scan — **explore** — covers S1, S10. Three grep runs (this session) on `apps/web/src/i18n/es.json`, `apps/web/src/i18n/en.json`, and `apps/web/package.json` for `biblioteca|Modo Biblioteca|Library|3D` and `three|@react-three`. All returned **no matches**. Done; recorded here for traceability.

T2: Author this feature document at `odd/tasks/biblioteca-3d.md` — **inline** — covers S1–S14. Single-file doc, ≤ 200 lines. Done in this session.

T3: Add new i18n keys for "Biblioteca 3D" — **implement-via-worker, PR slice #1 ("i18n(web): biblioteca-3d labels")** — covers S1, S10, S13. Edit `apps/web/src/i18n/es.json` and `apps/web/src/i18n/en.json`. Add `nav.biblioteca` (sibling of `nav.home|projects|about|language`), `home.cta.biblioteca` (sibling of `home.cta.chat|projects|all_projects`), and a `biblioteca3d.title|subtitle` block. ES value "Modo Biblioteca 3D" per S1; EN value "3D Library" by convention (see S1 note). Run `pnpm --filter portafolio-web run check` after; expect zero type errors.

T4: Add navbar link — **implement-via-worker, PR slice #2 ("feat(web/nav): biblioteca-3d link")** — covers S1, S4. Edit `apps/web/src/layouts/Base.astro`. (a) Add `bibliotecaPath` const next to `aboutPath` (lines 30–32), locale-aware with explicit `/index.html` suffix. (b) Add a fourth `<li>` inside `<ul class="nav-links">`, after the existing `<li>` for `t.nav.about`. No other changes to Base.astro.

T5: Add hero CTA — **implement-via-worker, PR slice #3 ("feat(web/home): biblioteca-3d hero CTA")** — covers S1, S5, S7, S9. Edit `apps/web/src/pages/index.astro`. (a) Add `bibliotecaHref` const next to `projectsHref` / `aboutHref` (line 13–14). (b) Add a third `<a class="cta tertiary" href={bibliotecaHref}>{t.home.cta.biblioteca}</a>` inside the existing `<p class="ctas">` (after lines 27–28). (c) Add a `.cta.tertiary` CSS class in the existing `<style>` block, visually distinct from `.cta.primary` (solid) and `.cta.secondary` (border) — e.g. muted text + arrow. Plain `<a>` only — no client JS for persistence (S7, S9).

T6: Create the ES route page — **implement-via-worker, PR slice #4 ("feat(web/page): biblioteca-3d route")** — covers S2, S3, S6, S7, S8. NEW file `apps/web/src/pages/biblioteca-3d.astro`. Wraps `<Base title={t.biblioteca3d.title} description={...}>`. At build time, fetchs `getCollection('projects')` and projects the same slim shape already used in Base.astro (`{slug, title_es, title_en, summary_es, summary_en, year, tags}`), exposes it to the scene via `<Scene3D client:only="react" projects={projectsForScene} locale={locale} />` (T8's component). NO `localStorage` / `sessionStorage` access (S7, S9). Chatbot FAB arrives via Base.astro (S6). `apps/web/src/pages/en/biblioteca-3d.astro` is created in T7 and chained in this slice.

T7: Create the EN mirror — **implement-via-worker, chained into PR slice #4 (no separate PR)** — covers S2. NEW file `apps/web/src/pages/en/biblioteca-3d.astro`. Thin locale-aware copy of T6: imports `en.json`, sets `<html lang="en">` via the same `Astro.currentLocale ?? 'en'` pattern used elsewhere. Without this page, `/en/biblioteca-3d` would redirect to `/biblioteca-3d` because of `fallback: { en: 'es' }` (S2).

T8: Implement Scene3D React component + new deps — **implement-via-worker, PR slice #5 ("feat(web/scene): three-fiber biblioteca-3d")** — covers S3, S8. (a) Add dependencies to `apps/web/package.json`: `three`, `@react-three/fiber`, `@react-three/drei`, and dev-deps `@types/three`. (b) NEW file `apps/web/src/components/Scene3D.tsx`: `Canvas` from `@react-three/fiber`, drei primitives (`OrbitControls`, `Text`, `Float`, `Stars` as the prototype uses). Renders the projects passed via props (no fetches — props come from the Astro page at T6 / T7). Pure presentation — no API calls, no storage, no Chatbot import.

T9: FAB visual handling on `/biblioteca-3d` — **implement-via-worker, chained into PR slice #4** — covers S6, S11. ZERO changes to `apps/web/src/components/Chatbot.tsx`. The fix is a CSS-only rule in `biblioteca-3d.astro`'s `<style>` block that shifts the persistent FAB container when its renders below the 3D canvas (selector to be confirmed by the implementer — if Base.astro does not expose a route-scoped hook, add a `data-route="biblioteca-3d"` attribute to `<body>` from inside the page; that touch on Base.astro is allowed because it does not change Chatbot logic, only adds an HTML attribute hook).

T10: Verify bundle isolation — **implement-via-worker, part of PR slice #5 verification ("build: confirm three is route-scoped")** — covers S3. Run `pnpm --filter portafolio-web build`. Inspect `apps/web/dist/_astro/*.js` chunk list (and the `import.meta.glob` graph) to confirm: (a) `three` appears only in chunks that load on the `biblioteca-3d` route (typically identified by filename or the route's HTML referencing the chunk), (b) the shared entry chunks for `/`, `/proyectos/`, `/sobre-mi/`, `/en/*` do not import `three`. Attach the observed chunk filenames as PR evidence.

T11: Test infrastructure decision — **interaction_required** — covers S14. Three options for the parent to approve:
   - **A. Skip TDD**, rely on manual smoke test (`pnpm dev` → visit `/biblioteca-3d`, click a card, verify Three.js renders + Chatbot works). Fastest, but loses regression protection.
   - **B. Add Vitest to apps/web** (install + minimal `vitest.config.ts` covering the slim project-shape projection used by T6). Adds ~30 lines of config; covers S14 as ongoing.
   - **C. Defer tests to a follow-up PR** after the feature ships. Pick today; implement the chosen path in slice #5.
   The parent must pick A, B, or C before T8 merges. Until then, T8 carries a "testing decision pending" note in its PR body.

## Log

L1: "@experiments/chat-3d-library.html quiero que revises esta interfaz que hice. quiero que analises que tan dificil puede ser integrarla a la app" — first user message for this feature.

L2: User retry: "vuelve a intentarlo" — captured (no behavioral change; planning carries on).

L3: User retry: "intentalo ahora" — captured (no behavioral change; planning carries on).

L4: User continuation: "continua" — captured (no behavioral change; planning carries on).

L5: User decision: "si, me hace sentido, aunque creo que la parte de persistencia no la agregaria" — captured as non-goal S9 (no `localStorage` / `sessionStorage` for the 3D entry choice) and reinforced as S7 (no persistence layer). The persistence-related work that *could* have appeared (a "remember me in 3D mode" preference, a per-visitor 3D-on flag, a persistence-honored default route) is explicitly out of scope.

L6: User decision (ask_user_question #1 — placement of the new CTA): "navbar+hero" — captured as S4 (fourth navbar link in `apps/web/src/layouts/Base.astro`) and S5 (third hero CTA in `apps/web/src/pages/index.astro`). The CTA is NOT placed in the projects listing, the about page, the Chatbot, or the footer.

L7: User decision (ask_user_question #2 — shape of the entry): "dedicated route" — captured as S2 (`/biblioteca-3d` + `/en/biblioteca-3d`). Rejected alternatives: a modal overlay, an inline mode toggle on the home page, a hash-router route under `/`, a `/proyectos/?view=3d` query-string variant. The dedicated route is the only entry shape.

L8: User decision (ask_user_question #3 — chat strategy inside the 3D mode): "reuse Chatbot" — captured as S6 (Chatbot FAB reused, mounted globally via Base.astro's `transition:persist`) and S11 (no changes to `apps/web/src/components/Chatbot.tsx`, no duplicate RAG client). Rejected alternatives: building a new in-canvas chat, stripping the SSE wiring down to a fetch, or skipping the chat entirely.

Evidence observed during planning (this session):

- `git status` on `main` showed a clean tracked tree; only unrelated untracked files present (`1.png`, `docs/diagrams/cd-workflow.*`, `odd/tasks/{hardening-ci-cd,media-baja-ci-cd}.md`, `scripts/aws/*`). Preserved untouched. Branch created with `git checkout -b feat/biblioteca-3d main`; HEAD on new branch is `08795b5`, which is the merge commit for PR #16 (`feat/3d-library-experiment`) — therefore `experiments/chat-3d-library.html` is already in `main`, no cherry-pick needed.
- `grep -ri 'biblioteca|Modo Biblioteca|Library|3D' apps/web/src/i18n/es.json` → no matches.
- `grep -ri 'biblioteca|Modo Biblioteca|Library|3D' apps/web/src/i18n/en.json` → no matches.
- `grep 'three|@react-three' apps/web/package.json` → no matches. Confirms clean dependency surface for T8.
- Single repo-wide grep `vitest|playwright|jest|@testing-library|cypress` returned no test wiring in `apps/web`; only matches are inside `apps/api/data/projects/proj-safegateway.md` (API project, not web) and historical `.gitignore` lines 58–59. Captured as S14.
- Read of `apps/web/src/layouts/Base.astro` lines 30–32 confirms `prefixDefaultLocale: false` + the explicit `/index.html`-suffix pattern (with CloudFront/S3 compatibility comment).
- Read of `apps/web/src/layouts/Base.astro` lines 116–130 confirms `<Chatbot client:load transition:persist>` and its prop shape; no work is needed for S6 beyond visual repositioning.
- Read of `apps/web/src/i18n/es.json` confirms the `home.cta.*` shape used by S5's new key and the `nav.*` shape used by S4's new key.
- Read of `apps/web/src/content/config.ts` lines 13–14 confirms single source-of-truth: `../api/data/projects/` glob loader matches `apps/api/data/projects/` — same source the FastAPI RAG index consumes (S8).
- Read of `apps/web/astro.config.mjs` confirms `fallback: { en: 'es' }` is active → S2 requires an explicit EN page.
- Read of `experiments/chat-3d-library.html` line 1070 (PROJECTS_CATALOG literal) and total length 2958 lines confirms prototype is a fully self-contained reference doc; no code from it is meant to be lifted directly. Per S13, prototype strings stay Spanish.

L9: Implementation closed. 4 work-unit commits landed on `feat/biblioteca-3d`:

  - `506e744` i18n(web): add 'Modo Biblioteca 3D' labels — covers T3 (S1, S10, S13). 16 lines.
  - `f9f036c` feat(web/nav): add Biblioteca 3D link to global nav — covers T4 (S1, S4). 2 lines.
  - `b85ea58` feat(web/home): add Biblioteca 3D tertiary CTA in hero — covers T5 (S1, S5, S7, S9). 13 lines.
  - `5dbf330` feat(web): add /biblioteca-3d route with isolated Three.js scene — covers T6, T7, T8, T9, T10, T11 (S2, S3, S6, S7, S8, S11, S14). 531 authored lines (lock file excluded).

Total feature authored lines: 562 across 4 commits. Past the ~400-line threshold for a single feature → the feature is closed at HEAD `5dbf330`; further work would land as a follow-up branch.

L10: Verification snapshot (this session):
  - `pnpm run check` (cwd apps/web): exit 0, 14 files, 0 errors / 0 warnings / 0 hints.
  - `pnpm run test` (cwd apps/web): exit 0, 1 file, 2 tests passed.
  - `pnpm run build` (worker session, evidence re-verified locally): exit 0, 7 pages built. Bundle isolation via `grep 'Three.js Authors' apps/web/dist/_astro/*.js` returned exactly one chunk (`Scene3D.*.js`), and `grep -l 'Scene3D' dist/*/index.html` returned only `dist/biblioteca-3d/index.html` and `dist/en/biblioteca-3d/index.html`. `/`, `/proyectos/`, `/sobre-mi/` are clean.

L11: Hard-constraints check:
  - ✅ No `localStorage` / `sessionStorage` / `cookie` / `IndexedDB` access in new files.
  - ✅ `apps/api/` untouched.
  - ✅ `apps/web/src/components/Chatbot.tsx` untouched (`git diff HEAD~4 -- apps/web/src/components/Chatbot.tsx` is empty).
  - ✅ Empty-state branch for `getCollection('projects').length === 0` lives in two places (page-level for graceful render fallback, Scene3D-level for defensive rendering).

L12: Push and PR pending user OK per git-mentor skill. Branch `feat/biblioteca-3d` ahead of `origin/main` by 4 commits.
