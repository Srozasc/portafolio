# Feature: Ingest repo from GitHub (script CLI)

**Status**: in progress (Tarea 1 en curso)
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

### Tarea 1 — Scaffold del CLI + cliente GitHub (en curso)

- [ ] **T1.1** Tests: `parse_repo_ref("owner/repo")` → `("owner", "repo")`; URL `https://github.com/owner/repo[.git]` → mismo; string inválido → `ValueError`
- [ ] **T1.2** Tests: `slugify_repo_name("My-Repo")` → `"proj-my-repo"`; preserva `[a-z0-9-]`; trunca a 60 chars
- [ ] **T1.3** Tests: `GitHubClient(token=None)` lanza si GitHub responde 401; `get_repo(owner, repo)` parsea `created_at` → año int; `get_readme(owner, repo)` retorna markdown raw
- [ ] **T1.4** Implementación: `apps/api/scripts/ingest_repo.py` con `parse_repo_ref`, `slugify_repo_name`, `GitHubClient` (httpx + headers), argparse para `--token`, `--repo`, `--projects-dir`, `--out-dir`
- [ ] **T1.5** Verificar: `python apps/api/scripts/ingest_repo.py --repo octocat/Hello-World --projects-dir apps/api/data/projects/ --dry-run` imprime metadata del repo sin escribir nada
- [ ] **T1.6** Work-unit commit en `dev`: `feat(api): add ingest_repo CLI scaffold with GitHub client`

### Tarea 2 — Mapeo a frontmatter + escritura del `.md`

- [ ] **T2.1** Tests: `build_frontmatter(...)` produce dict válido según schema Zod; `slug` matchea `/^proj-[a-z0-9-]+$/`; campos bilingües con contenido real en el idioma detectado y placeholder explícito `# TODO translate` en el otro
- [ ] **T2.2** Tests: `write_project_md(...)` escribe archivo atómicamente (tmp + rename); aborta si el `.md` ya existe sin `--force`
- [ ] **T2.3** Implementación: `build_frontmatter(repo_data, detected_lang, translated_fields)` y `write_project_md(frontmatter, body, out_dir)`
- [ ] **T2.4** Validación Zod (importar schema de `apps/web/src/content/config.ts`... o redefinir como constante Python compartida): validar antes de escribir
- [ ] **T2.5** Verificar: dry-run contra `octocat/Hello-World` produce un frontmatter válido y un cuerpo markdown con el README
- [ ] **T2.6** Work-unit commit en `dev`: `feat(api): map GitHub repo to portfolio frontmatter and write .md`

### Tarea 3 — Detección de idioma del README + transformación de imágenes

- [ ] **T3.1** Tests: `detect_language(readme_text)` retorna `"es"` para texto español, `"en"` para inglés, `"en"` como fallback
- [ ] **T3.2** Tests: `rewrite_image_urls_to_absolute(readme_text, owner, repo, branch)` reemplaza `./foo.png` y `../bar.png` por `https://raw.githubusercontent.com/<owner>/<repo>/<branch>/<path>`
- [ ] **T3.3** Implementación: detector de idioma simple (heurística: stopwords ES vs EN, langdetect opcional como fallback). Reescritor de URLs de imágenes con regex.
- [ ] **T3.4** Verificar: README bilingüe detectado correctamente; imágenes relativas reescritas
- [ ] **T3.5** Work-unit commit en `dev`: `feat(api): detect README language and absolutize image URLs`

### Tarea 4 — Pasada de LLM para los campos del idioma secundario

- [ ] **T4.1** Extender `LLMClient` con método `chat(system, user) → str` (no-streaming) — test que mockea openai.OpenAI
- [ ] **T4.2** Tests: `translate_fields(fields, source_lang, target_lang, llm)` retorna dict con mismos keys pero valores traducidos; nombres propios y tech terms preservados (verificable con snapshot test)
- [ ] **T4.3** Implementación: prompt conservador (instrucciones explícitas de preservar nombres propios, terminología técnica, no inventar), `temperature=0.2`, retries (3) con backoff en StreamError
- [ ] **T4.4** Manejo de errores: si la traducción falla, dejar el idioma secundario con placeholder `# TODO translate` (no abortar el ingest)
- [ ] **T4.5** Verificar: integración con LLM real contra `octocat/Hello-World` produce campos traducidos coherentes
- [ ] **T4.6** Work-unit commit en `dev`: `feat(api): translate secondary-language fields via LLM`

### Tarea 5 — Modo interactivo del `role_*` + opt-in via `.portafolio.yml`

- [ ] **T5.1** Tests: `parse_portafolio_yml(raw_yaml)` retorna dict; ausencias toleradas; formato inválido → warning, no aborta
- [ ] **T5.2** Tests: `prompt_for_role(lang)` (función a testear con mock de `input()`) retorna string no vacío
- [ ] **T5.3** Implementación: descarga `.portafolio.yml` desde la API de GitHub (`/repos/{owner}/{repo}/contents/.portafolio.yml`); si existe, lee `role`, `client`, `summary_extra`, `impact`; si no, prompt al usuario (con default razonable: "Tech Lead" / "Engineer")
- [ ] **T5.4** Modo no-interactive (`--non-interactive`): aborta con error claro si falta info que solo el humano puede dar
- [ ] **T5.5** Work-unit commit en `dev`: `feat(api): ingest role/client from .portafolio.yml or interactive prompt`

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
