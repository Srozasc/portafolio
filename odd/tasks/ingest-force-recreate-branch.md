# ingest_repo — `--force` recrea branch cuando ya existe (local + remote)

## Contexto

Hoy, `--force` sobrescribe el `.md` pero **no maneja el caso de branch existente**. El script aborta con:

```
ERROR: branch 'content/ingest-safegateway' already exists
```

`create_branch()` siempre levanta `GitError` si `git rev-parse` encuentra la branch, sin distinguir entre uso normal (sin force) y force (querés destruir).

Caso real: usuario re-corre el script con `--force` sobre `Srozasc/SafeGateway` después de agregar el feature de LLM tags. La branch del primer ingest todavía existe (local + remote), aborta el script.

## Alcance

**Cambia:**
- `apps/api/scripts/ingest_repo.py`:
  - `create_branch(name, base, force=False)`: si `force=True` y la branch existe local, `git branch -D`. Si existe remote, `git push origin --delete` (con warning si falla — no abortamos).
  - `git_push(name, force=False)`: si `force=True`, usa `--force-with-lease` en vez del push normal. `--force-with-lease` es más seguro que `--force`: rechaza pisar cambios remotos que no viste.
  - `main()`: pasa `args.force` a ambos helpers.
- `apps/api/tests/scripts/test_branch_pr.py`:
  - 3 tests nuevos: `test_no_force_raises_if_branch_exists` (regresión), `test_force_deletes_existing_local_branch`, `test_force_deletes_existing_remote_branch`.
  - 1 test para `git_push`: `test_force_push_uses_force_with_lease`.

**No cambia:**
- API pública del script (los flags CLI siguen iguales).
- Comportamiento sin `--force` (backward compat: sigue raising si branch existe).
- `--update` tiene el MISMO bug pero queda out of scope (task separado).

## Tasks

- [ ] **Task 1** — Modificar `create_branch` para soportar `force=False` (delete local + remote antes de crear).
- [ ] **Task 2** — Modificar `git_push` para soportar `force=False` (usa `--force-with-lease`).
- [ ] **Task 3** — Modificar `main()` para pasar `args.force` a ambos.
- [ ] **Task 4** — Tests unitarios (3 nuevos para create_branch + 1 para git_push).
- [ ] **Task 5** — Verificar ruff + todos los tests verde, commit work-unit.

## Convenciones

- Conventional commits en español, scope `api`
- Sin `Co-Authored-By`
- Mensaje atómico: solo el fix de --force
- Si una task crece más de lo planificado, dividir antes de commitear

## Nota sobre PRs viejos

Cuando el script destruye la branch vieja + crea una nueva, el PR viejo (ej: PR #1 contra `content/ingest-safegateway`) queda huérfano — GitHub lo marca como "closed (branch deleted)" automáticamente. El usuario tiene que cerrarlo a mano en la UI. El script no cierra PRs (no queremos depender de `gh` API para algo que debería ser cleanup manual).
