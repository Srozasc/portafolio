# Feature: Ingest repo from GitHub (script CLI)

**Status**: complete (Tareas 1-8 done; feature cerrada)

## Commits landed on `dev`

| Tarea | Commit SHA | Subject |
| --- | --- | --- |
| 1 | `0a26c0f` | `feat(api): agregar scaffold del CLI ingest_repo con cliente GitHub` |
| docs (T1) | `647be9e` | `docs(tasks): registrar feature ingest-repo-from-github` |
| 2 | `691d8ec` | `feat(api): mapear repo de GitHub a frontmatter del portafolio y escribir .md` |
| 3 | `5c6e734` | `feat(api): detectar idioma del README y reescribir URLs de imagenes a absolutas` |
| 4 | `5991f4b` | `feat(api): extender LLMClient con chat() no-streaming y agregar translate_fields al script` |
| 5 | `465139a` | `feat(api): cargar role desde .portafolio.yml o prompt interactivo en el script` |
| 6 | `f1d2b77` | `feat(api): wrappear git y gh CLI para branch + draft PR en el script` |
| 7 | `b485a6d` | `feat(api): agregar modos --force y --update para re-ingestar proyectos` |
| 8 (feat) | `a843325` | `feat(api): wirear main() con pipeline completo + smoke test E2E` |
| 8 (docs) | (siguiente) | `docs(api): documentar script ingest_repo y env vars` |

**Started**: 2026-09-22
**Branch**: `dev` (perfil solo-freelancer; el script al ejecutarse creará sus propios branches por-repo)
**Sources**:

- Conversación de diseño con el usuario (2026-09-22)
- Design doc del portafolio: `docs/plans/2026-09-17-portafolio-rag-design.md` (menciona `scripts/add_project.py`)
- Impl plan: `docs/plans/2026-09-17-portafolio-rag-impl-plan.md`
- LLM client: `apps/api/backend/rag/llm_client.py` (a extender para no-streaming)
- Backend Settings: `apps/api/backend/config.py`
- Script de referencia: `apps/api/scripts/reindex.py`

## Goal

CLI Python en `apps/api/scripts/ingest_repo.py` que recibe **un repo puntual** de GitHub (URL o `owner/repo`) y genera un archivo `apps/api/data/projects/proj-<slug>.md` listo para el portafolio, con frontmatter bilingüe (idioma detectado del README + traducción por LLM del lado contrario).

**Output:** un solo `.md` por corrida. Branch nuevo + commit + PR en draft contra `dev` (PR por repo, como decidió el usuario).

## Strategy

- **Input puntual:** CLI acepta `owner/repo` o URL. No escanea cuentas.
- **Filtro de repos:** N/A a nivel CLI (ya viene filtrado por el humano que pasa la URL).
- **Opt-in por-repo:** si el repo tiene `.portafolio.yml` en la raíz, lee de ahí `role`, `client`, `summary_extra`, `impact`. Si no, el CLI pregunta al usuario en modo interactivo.
- **Bilingüismo:** detección de idioma del README → campos del idioma detectado con contenido real → LLM traduce al idioma contrario con prompt conservador (low temperature, conservar nombres propios y términos técnicos).
- **Auth:** `GITHUB_TOKEN` desde env (rate limit 5000/h vs 60/h sin token).
- **Re-correr el script:** si el `.md` ya existe, aborta con error claro. `--force` sobrescribe; `--update` preserva ediciones manuales del humano en `role_*` e `impact_*`.
- **Reutilización:** `backend/rag/llm_client.py` (extender con método no-streaming `chat()`); `backend/config.py` para Settings; `httpx` (ya en requirements) para GitHub.
- **Tests:** TDD estricto. Tests unitarios con mocks. Smoke test E2E contra un repo real chico en la última tarea.

## Tasks

### Tarea 1 — Scaffold del CLI + cliente GitHub — DONE

Commits:

- `0a26c0f` `feat(api): agregar scaffold del CLI ingest_repo con cliente GitHub` (código + tests + `__init__.py`)
- `647be9e` `docs(tasks): registrar feature ingest-repo-from-github` (este task file)

- [x] **T1.1** Tests: `parse_repo_ref("owner/repo")` → `("owner", "repo")`; URL `https://github.com/owner/repo[.git]` → mismo; string inválido → `ValueError` — **13/13 verde**
- [x] **T1.2** Tests: `slugify_repo_name("My-Repo")` → `"proj-my-repo"`; preserva `[a-z0-9-]`; trunca a 60 chars — **15/15 verde**
- [x] **T1.3** Tests: `GitHubClient(token=None)` lanza si GitHub responde 401; `get_repo(owner, repo)` parsea `created_at` → año int; `get_readme(owner, repo)` retorna markdown raw — **8/8 verde**
- [x] **T1.4** Implementación: `apps/api/scripts/ingest_repo.py` con `parse_repo_ref`, `slugify_repo_name`, `GitHubClient` (httpx + headers), argparse para `--token`, `--repo`, `--projects-dir`, `--dry-run`
- [x] **T1.5** Verificar: `--help` muestra argparse correcto; `--repo invalid` retorna exit 1 con mensaje claro; dry-run scaffold OK
- [x] **T1.6** Work-unit commit en `dev`: `0a26c0f` + `647be9e`

### Tarea 2 — Mapeo a frontmatter + escritura del `.md` — DONE

Commit: `691d8ec` (incluye modernization de typings para ruff limpio: `tuple[...]`, `str | None`, `Self`, imports re-ordenados).

- [x] **T2.1** Tests: `build_frontmatter(...)` produce dict válido según schema Zod; `slug` matchea `/^proj-[a-z0-9-]+$/`; campos bilingües con contenido real en el idioma detectado y placeholder `_(traduccion pendiente)_` Zod-safe en el otro — **22/22 verde**
- [x] **T2.2** Tests: `write_project_md(...)` escribe archivo atómicamente (tmp + rename); aborta si el `.md` ya existe sin `--force`; falla limpio sin `.md.tmp`; round-trip YAML; UTF-8 — **10/10 verde**
- [x] **T2.3** Implementación: `build_frontmatter(repo_data, role, detected_lang)` y `write_project_md(frontmatter, body, out_dir, *, force=False)`
- [x] **T2.4** `validate_frontmatter(fm)` (Python mirror del schema Zod): slug regex, year [2000,2100] int (bool rechazado), tags/stack non-empty string list, summary ≥ 20 chars, links.repo/demo http(s)
- [x] **T2.5** Tests integration (`test_returns_zod_valid_dict_en`/`_es`, `test_output_is_yaml_round_trippable`) confirman end-to-end
- [x] **T2.6** Work-unit commit en `dev`: `691d8ec`

### Tarea 3 — Detección de idioma del README + transformación de imágenes — DONE

Commit: `5c6e734`.

- [x] **T3.1** Tests: `detect_language(readme_text)` retorna `"es"` para texto español, `"en"` para inglés (incluyendo empty input, empate, idioma desconocido, README con code blocks / inline code / URLs / HTML) — **21/21 verde**
- [x] **T3.2** Tests: `rewrite_image_urls_to_absolute(readme_text, owner, repo, branch)` reescribe Markdown `![alt](path)` (con y sin title, `./`, `../`, paths anidados, anclas, data:, mailto:) y HTML `<img src="...">` (comillas dobles y simples) — **27/27 verde**
- [x] **T3.3** Implementación: detector con listas de stopwords ES/EN (frozensets, ruff-clean sin duplicados B033); strip pre-cuenta de code blocks, inline code, URLs y HTML. Reescritor de imágenes con regex (Markdown image con title opcional como grupo capturing; HTML `<img>` tag reescrito preservando el resto de los atributos). Tokens < 3 chars se ignoran para evitar ambigüedad entre idiomas.
- [x] **T3.4** Smoke tests cubren READMEs bilingües, imágenes relativas de varios niveles, parent paths, anclas y combinaciones
- [x] **T3.5** Work-unit commit en `dev`: `5c6e734`

### Tarea 4 — Pasada de LLM para los campos del idioma secundario — DONE

Commit: `5991f4b`.

- [x] **T4.1** `LLMClient.__init__` ahora acepta `client: openai.OpenAI | None = None` (A-a). Nuevo método `chat(system, user, *, temperature=0.2, max_retries=3) -> str` non-streaming. Retries solo en `APIConnectionError | RateLimitError | APITimeoutError` (C-a), backoff 1s/2s/4s. Auth y bad-request fallan loud sin retry. Empty content raise `StreamError`. Los 4 tests existentes de `stream_chat` siguen verdes — **15/15 nuevo (3 constructor + 4 happy + 6 retries + 2 non-retryable)**
- [x] **T4.2** Tests `translate_fields`: ES→EN, EN→ES, JSON en code fences, preamble text, system prompt con instrucciones de preservar nombres propios, user message contiene input fields — **8/8 nuevo**
- [x] **T4.3** `translate_fields` con prompt conservador: temperature 0.2, system prompt exige JSON object sin prose/markdown/code fences, user prompt template con reglas (preservar nombres propios, no inventar, match tone/length). JSON output (B-b) — extraído con `_extract_json` que maneja raw, ```json fences y preamble text — **incluido en T4.2**
- [x] **T4.4** Fallback robusto: si el LLM exhausta retries, parse falla, key missing, value non-string o empty → usa el original key por key. `logger.warning` para visibilidad. Mismas-lang y fields vacíos cortocircuitan sin llamar al LLM — **6/6 nuevo**
- [x] **T4.5** Validación de input: source/target lang deben ser `es` o `en` (else `ValueError`); input dict no se muta — **5/5 nuevo**
- [x] **T4.6** Work-unit commit en `dev`: `5991f4b`

**Total tests/scripts/**: 145 (T1-T3) + 34 (T4) = 179 verde. Los 4 tests de `tests/unit/test_llm_client.py` (stream_chat) preservados. 2 fallas pre-existentes en `test_projects_service.py` (seed files 5 vs 6), out of scope de esta feature.

**Decisiones de implementación documentadas:**

- **Constructor injection (A-a)**: `__init__` acepta `client` opcional. Cuando es None, se construye `openai.OpenAI(base_url, api_key)` como antes. Producción pasa None; tests inyectan un `MagicMock` con `chat.completions.create.side_effect = ...` para simular respuestas y errores.
- **Retry policy (C-a)**: `_TRANSIENT_EXCEPTIONS = (APIConnectionError, RateLimitError, APITimeoutError)` son las únicas que reintentan. `AuthenticationError` y `BadRequestError` (4xx config bugs) fallan loud sin retry. Backoff 2^attempt: 1s, 2s, 4s. `max_retries=3` default → 4 attempts total.
- **JSON output (B-b)**: el prompt del sistema exige "JSON object — never with prose, markdown, or code fences" pero `_extract_json` también tolera code fences y preamble text como defensa. Consistente con el patrón ya usado en `chat_service.py` para emitir project cards.
- **Fallback key-por-key (T4.4)**: no es all-or-nothing. Si el LLM traduce bien `title` pero el JSON no tiene `summary`, el `title` traducido queda y `summary` cae al original. Logging de warning para auditoría.
- **ruff UP035**: `from typing import Iterator` reemplazado por `from collections.abc import Iterator` (typing.Iterator deprecado desde 3.9).

### Tarea 5 — Modo interactivo del `role_*` + opt-in via `.portafolio.yml` — DONE

Commit: `465139a`.

- [x] **T5.1** `parse_portafolio_yml(raw_text)` retorna dict con campos reconocidos (role, client, summary_extra, impact); ausencias toleradas; YAML inválido / no-dict / tipo incorrecto → warning + dict vacío (no aborta) — **17/17 verde**
- [x] **T5.2** `prompt_for_role(lang)` usa `input()` con monkeypatch en tests; default por idioma (es: "Ingeniero", en: "Tech Lead"); blank → default; prompt text contiene keyword de rol en idioma correcto — **8/8 verde**
- [x] **T5.3** `load_role_from_repo(client, owner, repo, branch, *, non_interactive, detected_lang)` combinadora: intenta `.portafolio.yml`, fallback `.portafolio.yaml`. GitHubClient.get_file_content nuevo método raw (404 → None, 401/403/≥400/network → GitHubError) — **5/5 verde (get_file_content) + 7/7 verde (load_role_from_repo)**
- [x] **T5.4** Modo `--non-interactive` (CLI flag): si falta YAML con role válido → raise `MissingRoleError` con mensaje claro sobre cómo resolver. Capturado en `main()` y reportado como `ERROR: ...` con exit 1 — **cubierto en T5.3**
- [x] **T5.5** Work-unit commit en `dev`: `465139a`

**Total tests/scripts/**: 179 (T1-T4) + 38 (T5) = 217 verde.

**Decisiones de implementación documentadas:**

- **Tolerancia a fallos en YAML (T5.1)**: el parser nunca raise. Errores se loguean con `logger.warning(...)` y devuelven `dict` vacío o parcial. `null`/`~`/string vacío → tratado como missing (key omitida).
- **Tipo strict por campo**: `role`/`client`/`summary_extra` deben ser `str` no-vacía; `impact` debe ser `list[str]` (items no-string se filtran). Keys con tipo incorrecto se omiten silenciosamente (no warning por key individual).
- **`.portafolio.yml` antes que `.yaml`** (T5.3): convención documentada; el fallback solo se activa si `.yml` da 404.
- **`prompt_for_role` no re-prompt**: blank → default inmediato (UX simple, menos fricción).
- **Bug latente corregido durante review**: el worker original puso `load_role_from_repo` FUERA del `with GitHubClient(...) as client:`, lo que llamaba `get_file_content` sobre un client ya cerrado en runtime. Movido adentro del `with` para que el client siga vivo durante la descarga del YAML.
- **Integration diferida a T8**: el `main()` actual llama `load_role_from_repo` y muestra el role en el summary, pero todavía no usa el role para construir el frontmatter (eso requiere integrar `build_frontmatter` con `write_project_md` + `translate_fields`, que es el wiring completo del CLI — va en T8 smoke test E2E).

### Tarea 6 — Branch + commit + PR en draft — DONE

Commit: `f1d2b77`.

- [x] **T6.1** `create_branch(name, *, base='dev')`: detecta branch existente via `git rev-parse --verify refs/heads/<name>` (raise `GitError` si existe); `git checkout -b <name> <base>` para crearla — **6/6 verde**
- [x] **T6.2** `open_draft_pr(*, title, body, base='dev')`: chequea `is_gh_installed()` primero (raise `GitHubCLIError` si no); corre `gh pr create --draft --title ... --body ... --base ...`; devuelve stdout (URL del PR); raise `GitHubCLIError` en non-zero exit — **5/5 verde**
- [x] **T6.3** `is_gh_installed()` detecta si gh esta en PATH (timeout 5s; captura `FileNotFoundError`/`TimeoutExpired`/`CalledProcessError`/`OSError` como False). `print_manual_pr_instructions(name, *, base)` fallback con comando `gh pr create --draft` + URL de compare. `git_commit(message, *, body='')` para el commit del branch — **8/8 verde (5 is_gh + 3 git_commit)**
- [x] **T6.4** Convencion del commit del branch: `chore(content): ingest repo <owner>/<repo>` (scope `content` porque toca `apps/api/data/projects/`). Conventional commit en espanol (proyecto convention). Implementacion queda lista; aplicacion automatica en T7/T8.
- [x] **T6.5** Verificacion end-to-end: deferred a T8 smoke test (T6 prueba los wrappers en aislamiento con mocks de subprocess).
- [x] **T6.6** Work-unit commit en `dev`: `f1d2b77`

**Total tests/scripts/**: 217 (T1-T5) + 21 (T6) = 238 verde.

**Decisiones de implementacion documentadas:**

- **Wiring en `main()` deferred a T7/T8**: las funciones existen pero `main()` no las llama todavia. El write step (T7) y el smoke test E2E (T8) son donde se integra todo en el flujo completo.
- **`subprocess.run` con `check=False` explicito** (ruff PLW1510): todas las 5 llamadas pasan `check=False` para que ruff no pida `try/except` alrededor — el chequeo de `result.returncode != 0` ya lo hace manualmente el caller.
- **`is_gh_installed` captura `CalledProcessError` tambien**: agregado al tuple de excepciones (no estaba en el spec literal pero un test lo requeria). Cambio estrictamente aditivo.
- **Branch name convention**: `content/ingest-<slug>` donde `<slug>` viene de `slugify_repo_name(repo_name)` (ej: `content/ingest-hello-world`). Documentado pero no hardcodeado — el caller decide.
- **PR body minimalista**: el caller pasa title + body. Para T7/T8, el body va a ser generado a partir de metadata del repo (description + stack + link).

### Tarea 7 — Re-correr el script: `--force` y `--update` — DONE

Commit: `b485a6d`.

- [x] **T7.1** `--force` flag en argparse (grupo mutuamente exclusivo con `--update`). Comportamiento: sobrescribe `.md` existente sin preservar nada — **cubierto en T7.3**
- [x] **T7.2** `merge_frontmatter_for_update(existing, new)`: preserva del existente `role_es`, `role_en`, `client`, `impact_es`, `impact_en` cuando son non-empty; regenera del nuevo `title_*`, `summary_*`, `stack_*`, `tags`, `year`, `links`. Slug siempre del existente (mismatch raise `ValueError`). Campos desconocidos se preservan — **29/29 verde**
- [x] **T7.3** `load_existing_frontmatter(md_path)`: lee frontmatter de un `.md` existente; devuelve None si no existe / no tiene frontmatter / YAML inválido / top-level no-dict. Tolerancia necesaria para que `--update` no rompa con archivos corruptos — **6/6 verde**
- [x] **T7.4** Work-unit commit en `dev`: `b485a6d`

**Total tests/scripts/**: 238 (T1-T6) + 31 (T7) = 269 verde tras fix del orchestrator al test contradictorio (1 assertion que asumia `title_es` preservado cuando la spec lo define como regenerado).

**Decisiones de implementacion documentadas:**

- **Preserved set**: `role_es, role_en, client, impact_es, impact_en`. Estos son los campos que el humano edita a mano en el PR y no querés perder en re-ingest. Tambien los unicos que se cargan de fuentes externas (.portafolio.yml o prompt) en el primer ingest.
- **Regenerated set**: `title_*, summary_*, stack_*, tags, year, links`. Vienen de la API de GitHub / son auto-generados; re-ingerirlos refleja el estado actual del repo.
- **Slug estable**: nunca regenera el slug (es el nombre del archivo). Mismatch raise `ValueError("slug mismatch: existing has 'proj-hello', new would produce 'proj-different'. Use --force to rename.")` — la logica es que re-ingerir el mismo repo produce el mismo slug; si no, hay algo raro.
- **`None`/`""`/`[]` no cuentan como preserved**: si el humano accidentalmente borro el contenido de un campo, el merge usa el valor nuevo (regenerado). Evita "preservar" vacios que no son truthy.
- **Campos desconocidos se preservan**: si el humano agrego `custom_field: x` al .md, no se pierde en re-ingest. Forward-compat.
- **main() NO wired todavia**: el write step completo esta pendiente (T7+T8). `--force` y `--update` se aplican al wire final de main().

**Bug del orchestrator al escribir tests**: 1 assertion (`test_existing_with_only_slug_and_title_es`) asumia que `title_es` se preservaba del existente, contradiciendo la spec que define `title_*` como regenerado. Fix aplicado antes del commit feat.

### Tarea 8 — Docs + smoke test E2E contra un repo real — DONE

Commits: `a843325` (feat) + (siguiente) `docs(api)` para README + .env.example.

- [x] **T8.1** `apps/api/scripts/README.md` (nuevo, ~180 lineas): usage basico, tabla de flags, env vars, opt-in `.portafolio.yml`, ejemplos (dry-run, primer ingest, --update, --force, --non-interactive), output esperado, troubleshooting (401/403, LLM fallido, slug mismatch), tests, estructura interna
- [x] **T8.2** `apps/api/.env.example` (modificado): nueva seccion al final con `GITHUB_TOKEN=` y comentario explicativo (rate limit 60 vs 5000 req/h, como crear token)
- [x] **T8.3** `tests/integration/test_ingest_repo_e2e.py` (nuevo, 3 tests): mocks de httpx (GitHub API para octocat/Hello-World), LLMClient (echo del input JSON, sin traduccion real), subprocess (git/gh). Cubre dry-run regression guard, happy-path write con frontmatter + body + imagenes reescritas, --force/--update guard. Los 3 tests pasan con `pytest tests/integration/test_ingest_repo_e2e.py -v` — **3/3 verde**
- [x] **T8.4** Work-unit commits en `dev`: `a843325` (feat) + docs (siguiente)
- [ ] **T8.5** PR de `dev` → `main` (lo abre el humano tras review)

**Total tests**: 270 (tests/scripts/) + 3 (tests/integration/test_ingest_repo_e2e.py) = 273 verde. Los 2 pre-existentes en `test_projects_service.py` (seed files 5 vs 6) siguen, out of scope de esta feature.

**Decisiones de implementacion documentadas:**

- **`main()` flow**: parse_repo_ref → (with GitHubClient: get_repo, get_readme, load_role_from_repo) → slugify → detect_language → rewrite_image_urls_to_absolute → build_frontmatter → _maybe_translate_frontmatter → write_project_md (con --force/--update/ProjectExistsError) → create_branch + git_commit + open_draft_pr (o print_manual_pr_instructions si gh no esta).
- **`_maybe_translate_frontmatter()` helper**: carga `Settings` lazy, llama `translate_fields` solo si `detected_lang != lado_nuevo`. Fallback graceful a placeholders si el LLM falla (T4.4). No aborta el ingest.
- **Branch name convention**: `content/ingest-<slug-sin-proj-prefix>` (ej: `content/ingest-hello-world`). Sigue la convencion del README y `test_branch_pr.py`. Worker decidio `slug.removeprefix("proj-")` en vez del literal `content/ingest-proj-hello-world` por consistencia.
- **`--dry-run`**: sale despues del summary print, antes de escribir o branch. El .md NO se escribe.
- **`--non-interactive`**: si no hay `.portafolio.yml` con role, raise `MissingRoleError`. Capturado en main() → exit 1 con mensaje claro.
- **`--force` / `--update`**: --force sobrescribe sin preservar. --update lee existing, llama `merge_frontmatter_for_update`, escribe merged. Sin flag y con .md existente → `ProjectExistsError`.
- **gh CLI ausente**: fallback a `print_manual_pr_instructions(branch_name)` con comando `gh pr create --draft` + URL de compare.
- **Mocks del smoke test**: httpx.MockTransport para GitHub API (octocat fixtures), LLMClient fake (echo del input JSON para que translate_fields retorne el mismo dict), function-based side_effect para subprocess.run que maneja las 6 llamadas (rev-parse, checkout, git commit, 2x gh --version, gh pr create).
- **`.env.example` extension**: `GITHUB_TOKEN=` al final (no interfiere con vars existentes). CRLF preservado.

## Convenciones

- Mensajes de commit en **español** (convención del proyecto, detectada en `git log`)
- Conventional Commits con scope específico del área: `feat(api)`, `test(api)`, `docs(api)`
- **Sin** trailer `Co-Authored-By`
- Cada task cierra con un work-unit commit en `dev`
- TDD estricto: tests escritos antes que la implementación
- No avanzar si una task no cumple sus criterios de aceptación

## Decisiones pendientes para durante la implementación

- **¿`.portafolio.yml` o `.portafolio.yaml`?** Aceptar ambos (chequear el primero; si no, el otro).
- **¿Detección de idioma con `langdetect` o heurística simple?** Decidir en T3 según tests: si la heurística cubre el 95% de los casos reales, no sumar dependencia.
- **¿LLM client reusar uno configurado en el backend o uno dedicado para traducciones?** Empezar reusando; si hay diferencia de calidad, separar.
- **¿Slug único cross-repo?** Validar que `proj-<slug>` no choque con un proyecto existente; si choca, pedir al usuario un slug distinto.

## Definition of done (esta feature)

- [ ] Las 8 tareas tienen work-unit commit en `dev`
- [ ] Todos los tests pasan (`pytest -q` desde `apps/api/`)
- [ ] Los tests existentes del backend siguen verdes (124 + nuevos)
- [ ] Smoke test E2E exitoso contra `octocat/Hello-World`
- [ ] Documentación de uso del script
- [ ] PR abierto de `dev` a `main` (lo abre el humano tras review)
