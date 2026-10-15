# Fix `humanize_repo_name` — soporte CamelCase sin separadores

## Contexto

`humanize_repo_name()` usa `re.sub(r"[-_]+", " ", name).strip().title()` que reemplaza separadores (`-`, `_`) por espacios y aplica `.title()`. Funciona bien para repos como `my-cool-repo` → `My Cool Repo`.

**Bug**: repos sin separadores (todo CamelCase) se manejan mal. Ejemplo: `SafeGateway` → el `[-_]+` no matchea nada, `.title()` convierte la primera letra de cada palabra separada por whitespace, pero no hay whitespace. Resultado: `Safegateway` (mal).

Caso real: `Srozasc/SafeGateway` se ingiere con `title_es: Safegateway` (incorrecto, debería ser `SafeGateway`).

## Alcance

**Cambia:**
- `apps/api/scripts/ingest_repo.py` — `humanize_repo_name()` agrega 2 regex lookaheads para CamelCase boundaries:
  - `(?<=[a-z])(?=[A-Z])` inserta espacio entre minúscula→mayúscula (e.g., "safeGateway" → "safe Gateway")
  - `(?<=[A-Z])(?=[A-Z][a-z])` inserta espacio antes de mayúscula-seguida-de-minúscula (e.g., "SafeGateway" → "Safe Gateway" cuando hay 2+ mayúsculas iniciales)
- `apps/api/tests/scripts/test_ingest_repo_frontmatter.py` — agregar tests para casos CamelCase.

**No cambia:**
- API pública.
- Otros archivos.

## Tasks

- [ ] **Task 1** — Editar `humanize_repo_name()` con los 2 regex lookaheads.
- [ ] **Task 2** — Agregar tests para casos CamelCase (`SafeGateway`, `myRepo`, `HiRag15k`, edge cases).
- [ ] **Task 3** — Verificar ruff + tests verde, commit work-unit.

## Convenciones

- Conventional commits en español, scope `api`
- Sin `Co-Authored-By`
- Mensaje atómico: solo el fix de humanize
- Si una task crece más de lo planificado, dividir antes de commitear
