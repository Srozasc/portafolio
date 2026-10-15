# ingest_repo — `git push` faltante antes de `gh pr create`

## Contexto

El script `apps/api/scripts/ingest_repo.py` (`main()`, sección 6) crea la branch con `create_branch`, hace commit con `git_commit`, e intenta abrir un PR con `gh pr create`. Pero **nunca pushea la branch a `origin` antes del PR**. GitHub aborta con:

```
ERROR: gh pr create failed: aborted: you must first push the current branch to a remote, or use the --head flag
```

Caso real del usuario corriendo contra `Srozasc/SafeGateway`. Llegó al commit local, branch `content/ingest-safegateway` creada, y abortó en `gh pr create`.

## Alcance

**Cambia:**
- `apps/api/scripts/ingest_repo.py` — agregar helper `git_push(branch_name)` siguiendo el patrón de `git_commit`/`create_branch`/`open_draft_pr`. Llamarlo en `main()` entre `git_commit` y `open_draft_pr`. Si falla (auth, no remote, timeout), aborta con exit 1 + stderr de git + hint sobre auth.
- `apps/api/tests/scripts/test_ingest_repo.py` (o nuevo test file) — agregar tests unitarios de `git_push`: comando correcto, manejo de errores (returncode !=0, TimeoutExpired, OSError).
- `apps/api/tests/integration/test_ingest_repo_e2e.py` — extender `_make_subprocess_side_effect` para que `git push` retorne success con output realista. Agregar assertion de orden en `test_full_ingest_writes_md`: `git push<branch>` se invoca después de `git commit` y antes de `gh pr create`.

**No cambia:**
- API pública del script.
- Otros helpers git/gh.
- Otros tests.

## Tasks

- [ ] **Task 1** — Agregar `git_push(branch_name)` helper en `apps/api/scripts/ingest_repo.py`. Llamarlo en `main()` entre `git_commit` y `open_draft_pr`.
- [ ] **Task 2** — Agregar tests unitarios de `git_push` (comando, errores) + actualizar E2E mock + assertion de orden.
- [ ] **Task 3** — Verificar ruff + pytest (275 → 275+ verde), commit work-unit.

## Convenciones

- Conventional commits en español, scope `api`
- Sin `Co-Authored-By`
- Mensaje atómico: solo el fix del push
- Si una task crece más de lo planificado, dividir antes de commitear