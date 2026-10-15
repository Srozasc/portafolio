# Fix ChromaDB cosine distance + reindex orphan cleanup

## Contexto

Dos bugs relacionados en ChromaDB que afectan el bot RAG:

### Bug #1: ChromaDB usa Euclidean distance, score math es incorrecta

`VectorStore.get_or_create()` crea collections con `metadata` vacío. ChromaDB por default usa **Euclidean distance (L2)**, no cosine distance.

`VectorStore.query()` calcula `score = 1 - dist` asumiendo que ≈ cosine similarity. Esto es **matemáticamente incorrecto** para embeddings normalizados en alta dimensión:

- Para cosine sim = 0.31 (match "rag" → proj-portafolio-rag):
  - Euclidean dist = sqrt(2 - 2*0.31) ≈ **1.18**
  - Score (1 - dist) = **-0.18** (NEGATIVO!)
- Threshold del bot = 0.1 → score < 0.1 → match filtrado
- Resultado: el bot NO encuentra matches válidos para queries cortas

Antes el bot funcionaba porque había 7 proyectos (incluyendo proj-rag-customer que matcheaba "rag" con suficiente overlap temático). Después de borrar placeholders, los 2 matches restantes tienen cosine bajo y se filtran.

### Bug #2: per-project collections huérfanas

`reindex.py --force` borra:
- `projects_index` (master)
- per-project collections para proyectos ACTUALES en `data/projects/`

Pero NO borra per-project collections para proyectos BORRADOS del filesystem. Resultado: 5 collections huérfanas (`projects_proj-ml-scoring`, etc.) quedan acumulando espacio en disco.

## Solución

### Fix #1: ChromaDB cosine distance

Modificar `VectorStore.get_or_create()` para pasar `metadata={"hnsw:space": "cosine"}` cuando crea collections. ChromaDB calculará cosine distance nativamente, entonces `score = 1 - cosine_distance = cosine_similarity` directamente.

**Importante**: ChromaDB no permite cambiar la métrica de una collection existente. Hay que **borrar y recrear**. El reindex con `--force` ya borra collections antes de re-crearlas, así que el fix se aplica con un reindex.

### Fix #2: Orphan cleanup

Modificar `ProjectsService.ingest_all()` para:
1. Recolectar los slugs actuales del `projects_dir`
2. Después del upsert (en el path de `--force`), iterar `store.list_collections()` y borrar cualquier `projects_proj-<slug>` cuyo slug no esté en el set actual
3. Idempotent: collections de proyectos actuales se borran y recrean normalmente

## Alcance

**Cambia:**
- `apps/api/backend/rag/vector_store.py` — `get_or_create()` pasa `metadata={"hnsw:space": "cosine"}`
- `apps/api/backend/services/projects_service.py` — `ingest_all(force=True)` borra orphan collections
- Tests existentes que asumen distance euclidean (algunos assertions numéricos pueden cambiar)
- Tests nuevos para orphan cleanup

**No cambia:**
- API pública de los servicios
- El threshold del bot (sigue siendo configurable via `SIMILARITY_THRESHOLD`)
- Comportamiento con `force=False` (no borra orphans — solo --force)

## Tasks

- [ ] **Task 1** — Fix #1: VectorStore.get_or_create con cosine distance + tests
- [ ] **Task 2** — Fix #2: ProjectsService.ingest_all cleanup de orphans + tests
- [ ] **Task 3** — Reindex --force para aplicar fix #1 (crea collections nuevas con cosine) + fix #2 (limpia orphans)
- [ ] **Task 4** — Verificar: el bot encuentra proj-portafolio-rag para query "rag"
- [ ] **Task 5** — 2 commits separados (uno por fix)

## Convenciones

- Conventional commits en español, scope `api` (Fix #1: `fix(api): ...`, Fix #2: `chore(api): ...`)
- Sin `Co-Authored-By`
- 1 commit por fix (atomic commits)
- Si una task crece más de lo planificado, dividir antes de commitear

## Notas

Después del commit, **el usuario debe correr** `reindex.py --force` para:
- Recrear collections con la nueva métrica (cosine)
- Limpiar las 5 collections huérfanas

O alternativamente, se puede hacer un `rm -rf apps/api/data/chroma/` y un reindex limpio desde cero.
