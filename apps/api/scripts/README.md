# `ingest_repo.py` — CLI para ingestar un repo de GitHub al portafolio

Toma una URL o shorthand `owner/repo` de GitHub y genera el archivo
`proj-<slug>.md` listo para el portafolio, con frontmatter bilingüe (idioma
detectado del README + traducción por LLM del lado contrario). Si `gh` CLI
está instalado y autenticado, también crea un branch y abre un draft PR
contra `dev`.

## Uso básico

```bash
# Desde apps/api/ con el venv activado:
python -m scripts.ingest_repo --repo octocat/Hello-World

# Desde la raíz del repo (Unix):
cd apps/api && .venv/bin/python -m scripts.ingest_repo --repo octocat/Hello-World

# Desde la raíz del repo (Windows):
cd apps/api && .venv/Scripts/python.exe -m scripts.ingest_repo --repo octocat/Hello-World
```

## Flags

| Flag | Descripción |
| --- | --- |
| `--repo OWNER/REPO` (requerido) | Repo de GitHub. Acepta `owner/repo`, URL `https://github.com/owner/repo`, o `git@github.com:owner/repo.git` |
| `--token TOKEN` | GitHub token. Default: lee de `GITHUB_TOKEN` env var |
| `--projects-dir PATH` | Directorio destino. Default: `apps/api/data/projects/` (relativo a la raíz del repo) |
| `--dry-run` | Imprime metadata sin escribir archivo ni crear branch/PR |
| `--non-interactive` | Aborta si falta info que solo el humano puede dar (ej: role sin `.portafolio.yml`) |
| `--force` | Sobrescribe `.md` existente completo (no preserva edits humanos) |
| `--update` | Actualiza `.md` existente preservando `role_*`, `client`, `impact_*` del humano; regenera el resto |

## Variables de entorno

| Variable | Default | Descripción |
| --- | --- | --- |
| `GITHUB_TOKEN` | (vacío) | Token personal de GitHub. Sin token: rate limit 60 req/h; con token: 5000 req/h |
| `LLM_BASE_URL` | `http://localhost:1234/v1` | Endpoint OpenAI-compatible para el LLM de traducción |
| `LLM_API_KEY` | `not-needed` | API key del LLM |
| `CHAT_MODEL` | `local-model` | Modelo de chat a usar |

## Opt-in: `.portafolio.yml` en la raíz del repo

Si el repo tiene un `.portafolio.yml` (o `.portafolio.yaml`) en la raíz,
el script lee `role`, `client`, `summary_extra` e `impact` de ahí. Ejemplo:

```yaml
role: Tech Lead
client: ACME Corp
summary_extra: Detalles adicionales que el humano quiere capturar.
impact:
  - Redujo el tiempo de deploy en 50%
  - Ahorró $1M anuales
```

Sin este archivo (o si no tiene `role:`), el script pregunta interactivamente
(o aborta con `--non-interactive`).

## Ejemplos

### Dry-run: ver qué haría sin escribir nada

```bash
python -m scripts.ingest_repo --repo octocat/Hello-World --dry-run
```

### Primer ingest (escribe el `.md`, crea branch, abre draft PR)

```bash
python -m scripts.ingest_repo --repo octocat/Hello-World
```

### Re-ingestar preservando campos humanos

```bash
python -m scripts.ingest_repo --repo octocat/Hello-World --update
```

### Forzar sobrescritura completa

```bash
python -m scripts.ingest_repo --repo octocat/Hello-World --force
```

### Modo CI / no-interactivo

```bash
python -m scripts.ingest_repo --repo owner/repo --non-interactive
```

(requiere `.portafolio.yml` con `role:` en el repo; aborta si falta)

## Output

El script genera `apps/api/data/projects/proj-<slug>.md` con:

- **Frontmatter YAML** validable contra el schema Zod del sitio (`slug`,
  `title_es/en`, `year`, `role_es/en`, `tags`, `stack_es/en`,
  `summary_es/en`, `client`, `impact_es/en`, `links`).
- **Cuerpo markdown** = README del repo (con URLs de imágenes reescritas
  a `raw.githubusercontent.com`).

Si `gh` CLI está instalado y autenticado, también:

- Crea el branch `content/ingest-<slug>` desde `dev`.
- Crea un commit `chore(content): ingest repo <owner>/<repo>`.
- Abre un draft PR contra `dev` con título y body generados.

Si `gh` no está disponible, imprime las instrucciones para crear el PR
manualmente.

## Troubleshooting

- **`GitHub API returned 401 Unauthorized`**: `GITHUB_TOKEN` inválido o sin scope `repo:read`. Regenerar en https://github.com/settings/tokens.
- **`GitHub API returned 403 Forbidden`**: rate limit. Esperar una hora o usar un token con más permisos.
- **`LLM translation failed (LLM unavailable after N attempts)`**: el LLM no responde. Revisar `LLM_BASE_URL` y `LLM_API_KEY` en `.env`. El script cae al placeholder `_(traducción pendiente)_` y no aborta — podés traducir a mano después.
- **`Cannot determine role: no .portafolio.yml found... and --non-interactive is set`**: agregar `.portafolio.yml` al repo o correr sin `--non-interactive`.
- **`slug mismatch`**: re-ingestar un repo cuyo slug derivado no coincide con el existente. Usar `--force` solo si querés renombrar el archivo (cuidado: cambia la URL del proyecto en el sitio).
- **README vacío o muy corto**: `detect_language` puede caer al fallback `en`. Si el repo tiene README multilenguaje, traducir manualmente después del ingest.

## Tests

```bash
cd apps/api
.venv/Scripts/python.exe -m pytest tests/scripts/ -v       # unit
.venv/Scripts/python.exe -m pytest tests/integration/ -v   # integration (incluye E2E smoke)
```

## Estructura interna

```
scripts/ingest_repo.py
├── parse_repo_ref, slugify_repo_name              # T1: parseo del input
├── validate_frontmatter, build_frontmatter,
│   write_project_md                               # T2: frontmatter + escritura atómica
├── detect_language, rewrite_image_urls_to_absolute # T3: idioma + imágenes
├── translate_fields (usa backend.rag.llm_client)  # T4: traducción LLM
├── parse_portafolio_yml, prompt_for_role,
│   load_role_from_repo, GitHubClient.get_file_content  # T5: role intake
├── is_gh_installed, create_branch, git_commit,
│   open_draft_pr, print_manual_pr_instructions   # T6: branch + PR
└── merge_frontmatter_for_update, load_existing_frontmatter  # T7: --force / --update
```
