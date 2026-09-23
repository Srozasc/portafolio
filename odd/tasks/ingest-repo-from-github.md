# Feature: Ingest repo from GitHub (script CLI)

**Status**: in progress (Tareas 1-5 done; Tarea 6 en curso)

## Commits landed on `dev`

| Tarea | Commit SHA | Subject |
| --- | --- | --- |
| 1 | `0a26c0f` | `feat(api): agregar scaffold del CLI ingest_repo con cliente GitHub` |
| docs (T1) | `647be9e` | `docs(tasks): registrar feature ingest-repo-from-github` |
| 2 | `691d8ec` | `feat(api): mapear repo de GitHub a frontmatter del portafolio y escribir .md` |
| 3 | `5c6e734` | `feat(api): detectar idioma del README y reescribir URLs de imagenes a absolutas` |
| 4 | `5991f4b` | `feat(api): extender LLMClient con chat() no-streaming y agregar translate_fields al script` |
| 5 | `465139a` | `feat(api): cargar role desde .portafolio.yml o prompt interactivo en el script` |

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

### Tarea 6 — Branch + commit + PR en draft

- [ ] **T6.1** Tests: `create_branch(branch_name)` corre `git checkout -b <branch>` desde `dev`; falla si el branch ya existe
- [ ] **T6.2** Tests: `open_draft_pr(...)` ejecuta `gh pr create --draft --title ... --body ...`; verifica exit code
- [ ] **T6.3** Implementación: wrapper sobre `git` (subprocess) y `gh` (subprocess). Detectar si `gh` está instalado; si no, fallback a instrucciones impresas para crear el PR manualmente.
- [ ] **T6.4** Conventional commit en español para el branch: `chore(content): ingest repo <owner>/<repo>` (scope `content` porque toca `apps/api/data/projects/`)
- [ ] **T6.5** Verificar: end-to-end contra un repo real genera branch + PR draft
- [ ] **T6.6** Work-unit commit en `dev`: `feat(api): open draft PR per ingested repo via gh CLI`

### Tarea 7 — Re-correr el script: `--force` y `--update`

- [ ] **T7.1** Tests: `--force` sobrescribe `.md` existente
- [ ] **T7.2** Tests: `--update` lee el `.md` existente, preserva `role_*` e `impact_*` del humano, regenera el resto
- [ ] **T7.3** Implementación: merge selectivo — campos del humano (role, client, impact) se preservan; campos derivados del repo (title, summary, stack, tags) se regeneran
- [ ] **T7.4** Work-unit commit en `dev`: `feat(api): add --force and --update modes for re-ingest`

### Tarea 8 — Docs + smoke test E2E contra un repo real

- [ ] **T8.1** README del script: usage, ejemplos, troubleshooting (rate limit, repo privado, README muy largo)
- [ ] **T8.2** Actualizar `apps/api/.env.example` con `GITHUB_TOKEN=...`
- [ ] **T8.3** Smoke test E2E contra `octocat/Hello-World`: ingest completo, verificar que el `.md` generado pasa el schema Zod, que el body markdown se ve OK, que el branch y el PR se crearon
- [ ] **T8.4** Work-unit commit en `dev`: `docs(api): document ingest_repo script and env vars`
- [ ] **T8.5** PR de `dev` → `main` (lo abre el humano tras review)

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
