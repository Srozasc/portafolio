# ingest_repo — `git add` faltante antes de `git commit`

## Contexto

El script `apps/api/scripts/ingest_repo.py` (`main()`, sección 6 "branch + commit + draft PR", líneas ~1430-1439) escribe el `.md` con `write_project_md`, crea la branch con `create_branch`, y llama `git_commit`. Pero **`main()` nunca hace `git add` antes de `git_commit`**.

La función `git_commit` documenta explícitamente: *"The caller must have staged files via `git add` before calling."* Pero el caller (`main`) no stagea nada. Resultado: `git commit` aborta con:

```
ERROR: git commit failed: On branch content/ingest-safegateway
Untracked files:
        data/projects/proj-safegateway.md
nothing added to commit but untracked files present
```

Caso real del usuario: ingiriendo `Srozasc/SafeGateway`, llegó hasta `Wrote proj-safegateway.md`, branch creada, y abortó en el commit.

## Alcance

**Cambia:**
- `apps/api/scripts/ingest_repo.py` — agregar `subprocess.run(["git", "add", str(md_path)], ...)` en `main()` justo antes de `git_commit()`. Si `git add` falla (non-zero exit), `main()` reporta y retorna exit 1 con el stderr de git.
- `apps/api/tests/integration/test_ingest_repo_e2e.py` — extender el mock de `subprocess.run` para incluir la nueva llamada `git add <md_path>` y verificar que se invoca en el orden correcto, antes del `git commit`.

**No cambia:**
- `git_commit()`: sigue con el contrato "caller stages files" — útil si en el futuro queremos stagear varios archivos.
- API pública del script.
- Otros archivos.

## Tasks

- [ ] **Task 1** — Editar `main()` en `apps/api/scripts/ingest_repo.py`: agregar el `git add` antes del `git_commit`.
- [ ] **Task 2** — Extender `tests/integration/test_ingest_repo_e2e.py`: actualizar el mock de `subprocess.run` para incluir la nueva llamada, agregar assertion de orden.
- [ ] **Task 3** — Correr pytest (todos los tests del script + integration), verificar verde. Commit work-unit.

## Convenciones

- Conventional commits en español, scope `api`
- Sin `Co-Authored-By`
- Mensaje atómico: solo el fix del git add
- Si una task crece más de lo planificado, dividir antes de commitear

## Nota sobre el commit anterior `ff33298`

El commit `ff33298` (anterior) mezcló el fix de `tags` con un format pre-existente del script (`chore(api): ruff format`). El usuario aprobó la separación para próximos commits. Este commit nuevo debe ser **solo el fix del git add** — sin format adicional.