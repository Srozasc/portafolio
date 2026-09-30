# ingest_repo — tags deriva de `language` cuando `topics` está vacío

## Contexto

El script `apps/api/scripts/ingest_repo.py` (`build_frontmatter`, líneas ~358-368) deriva `tags` solo de los `topics` de GitHub. Pero `stack` se construye con `[language] + topics`. Resultado: cuando un repo tiene `language` configurado pero `topics` vacío (caso muy común en proyectos chicos/personales), `tags` queda `[]` y `validate_frontmatter` aborta con:

```
ERROR: tags must be non-empty array of strings: got []
```

Caso real: `Srozasc/SafeGateway` (TypeScript, sin topics). Corrió el script, llenó el rol, llegó al summary y abortó.

## Alcance

**Cambia:**
- `apps/api/scripts/ingest_repo.py` — alinear fuente de `tags` con la de `stack` (language + topics), lowercase + dedup. Cuando ambos están vacíos, `tags` queda `[]` (igual que ahora) — `validate_frontmatter` aborta con un mensaje claro.
- `apps/api/tests/scripts/test_ingest_repo_frontmatter.py` — agregar test de regresión: `language="TypeScript"` + `topics=[]` → `tags == ["typescript"]`.

**No cambia:**
- API pública del script (mismas funciones, misma signature).
- El validador (`validate_frontmatter`): sigue exigiendo `tags non-empty`. Si language + topics ambos vacíos, sigue abortando — pero eso es muy raro.
- `stack` (no se toca): sigue con mayúsculas (`["TypeScript"]`).
- Otros archivos (no hace falta tocar config, ni docs, ni main).

## Tasks

- [ ] **Task 1** — Editar `build_frontmatter` en `apps/api/scripts/ingest_repo.py`: cambiar la línea `tags = [t for t in topics ...]` por el loop nuevo (lowercase + dedup).
- [ ] **Task 2** — Agregar test `test_tags_includes_lowercased_language_when_topics_empty` en `apps/api/tests/scripts/test_ingest_repo_frontmatter.py`. Correr pytest, verificar que los 22 tests existentes siguen verdes + el nuevo verde.
- [ ] **Task 3** — Verificar end-to-end: re-correr el script con el repo del usuario (Srozasc/SafeGateway) para confirmar que llega al menos hasta el paso de traducción. Limpiar archivos basura si quedaron. Commit work-unit.

## Convenciones

- Conventional commits en español, scope `api`
- Sin `Co-Authored-By`
- Mensaje atómico: un solo bug fix
- Si una task crece más de lo planificado, dividir antes de commitear