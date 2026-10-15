# ingest_repo — generar tags con LLM desde el README

## Contexto

Hoy, `build_frontmatter()` deriva los `tags` solo desde `[language] + topics` de GitHub. Para repos sin topics (caso real: SafeGateway), eso da apenas 1-2 tags — insuficiente para que el bot RAG encuentre el proyecto con queries naturales como "gateway", "rate limiting", "circuit breaker".

El LLMClient ya está disponible (T4) con método `chat()` no-streaming, retries, JSON output parsing. Es lo único que falta usar.

## Diseño

### Flujo

```
main():
  get_repo()         → repo_data (incluye topics, language, description)
  get_readme()       → readme (raw markdown)
  detect_language(readme)
  llm = LLMClient(...)                    # NEW: una instancia, reutilizada
  build_frontmatter(repo_data, role, detected_lang, llm_client=llm, readme_text=readme)
  _maybe_translate_frontmatter(frontmatter, detected_lang, llm=llm)  # refactor para reusar llm
```

### Decisiones del usuario

| # | Decisión | Valor |
|---|---|---|
| 1 | Algoritmo | **B (LLM-assisted)** |
| 2 | Cantidad | **5 tags** |
| 3 | Topics de GitHub | **Se suman a los del LLM** (no reemplazan) |
| 4 | Si el LLM falla | **Lanzar excepción y cancelar el ingest** (no fallback silencioso) |

### Helper nuevo: `generate_tags_with_llm()`

```python
def generate_tags_with_llm(
    *,
    readme_text: str,
    description: str,
    language: str | None,
    existing_topics: list[str],
    llm_client: LLMClient,
) -> list[str]:
    """Devuelve exactamente 5 tags lowercase generados por LLM.

    Raises:
        RuntimeError: si el LLM falla, retorna JSON inválido, o retorna
            cantidad != 5 o tags no-string.
    """
```

### Constante: vocabulario controlado

Lista de tags conocidos (extraídos de los proyectos seed) como guía para consistencia en el prompt:

```python
_KNOWN_TAGS_VOCABULARY = frozenset({
    # Tech
    "python", "typescript", "aws", "kubernetes", "docker", "terraform",
    "kafka", "redis", "postgresql", "fastapi", "react", "astro",
    "spark", "flink", "openai", "llm", "rag", "vector-db", "chromadb",
    "ml", "mlops", "aws-sagemaker",
    # Domain
    "data-engineering", "real-time", "fraud-detection",
    "senior", "tech-lead", "fullstack", "backend", "frontend",
    "i18n", "sse", "rest-api",
    # Other
    "microservices", "monolith", "ci-cd", "devops", "observability",
})
```

### Modificaciones

- **`build_frontmatter()`**: agregar kwargs `llm_client` y `readme_text`. Tags = existing + llm_tags (dedup case-insensitive). Si `llm_client is None` → raise.
- **`main()`**: instanciar `LLMClient` una vez, pasarlo a `build_frontmatter` y `_maybe_translate_frontmatter` (refactor menor para reusar la instancia).
- **`_maybe_translate_frontmatter()`**: aceptar `llm` opcional (kwarg). Si se pasa, usar esa instancia. Si no, lazy create (backward compat).

### Tests a agregar/actualizar

1. **Unit test del helper** `generate_tags_with_llm`:
   - Happy path: mock LLM devuelve JSON array válido → 5 tags
   - Falla del LLM (`StreamError`) → `RuntimeError` propagada
   - JSON inválido → `RuntimeError`
   - Cantidad != 5 → `RuntimeError`
   - Tags no-string → `RuntimeError`
2. **Update tests existentes** de `build_frontmatter`: agregar `llm_client` y `readme_text` como kwargs. Verificar dedup entre existing + llm tags.
3. **Update E2E test**: el `_FakeLLMClient` actual devuelve el input como eco — agregar soporte para `chat()` en el flujo de tags (el `_FakeLLMClient` ya tiene `chat()`, hay que verificar que funcione en este nuevo path).

### Archivos tocados

- `apps/api/scripts/ingest_repo.py` — agregar constante + helper + modificar 2 funciones
- `apps/api/tests/scripts/test_ingest_repo_frontmatter.py` — agregar tests del helper + update existentes
- `apps/api/tests/integration/test_ingest_repo_e2e.py` — verificar flujo end-to-end (probablemente sin cambios, solo verificación)

### No en alcance (backlog)

- Auditar otros scripts CLI por el bug ModuleNotFoundError (mencionado en commit anterior)
- Fix de `humanize_repo_name()` para CamelCase
- Sanitizar links `file:///` en el body

## Tasks

- [ ] **Task 1** — Crear constante `_KNOWN_TAGS_VOCABULARY` + helper `generate_tags_with_llm()` con tests unitarios.
- [ ] **Task 2** — Modificar `build_frontmatter()` para aceptar `llm_client` + `readme_text` kwargs y combinar tags.
- [ ] **Task 3** — Refactor `_maybe_translate_frontmatter()` para aceptar `llm` opcional.
- [ ] **Task 4** — Modificar `main()` para instanciar `LLMClient` una vez y pasarlo a ambos.
- [ ] **Task 5** — Verificar ruff + todos los tests verde, commit work-unit.

## Convenciones

- Conventional commits en español, scope `api`
- Sin `Co-Authored-By`
- Mensaje atómico: solo el feature de tags
- Si una task crece más de lo planificado, dividir antes de commitear