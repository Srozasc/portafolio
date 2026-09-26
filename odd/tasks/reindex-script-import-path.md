# reindex.py — soporta ejecución como script directo o como módulo

## Contexto

El script `apps/api/scripts/reindex.py` falla con `ModuleNotFoundError: No module named 'backend'` cuando se ejecuta como:

```bash
.venv/Scripts/python.exe scripts/reindex.py
```

Porque Python agrega `scripts/` al `sys.path` (no `apps/api/`). Como los `from backend.config import Settings` están a nivel de módulo (no dentro de una función), se ejecutan al import time, antes del guard `if __name__ == "__main__": main()`.

Funciona bien cuando se ejecuta como módulo:

```bash
.venv/Scripts/python.exe -m scripts.reindex
```

(porque `-m` agrega el cwd al `sys.path`).

## Alcance

**Cambia:**
- `apps/api/scripts/reindex.py` — agregar 4 líneas después de los imports stdlib, antes de los `from backend... import`:
  ```python
  # Make 'backend' importable when run as a script: python scripts/reindex.py
  # (when run as -m, the cwd is already on sys.path, so this is a no-op)
  _app_root = str(Path(__file__).resolve().parent.parent)
  if _app_root not in sys.path:
      sys.path.insert(0, _app_root)
  ```

**No cambia:**
- API ni comportamiento del script.
- Otros archivos.
- Tests (no hay tests específicos para reindex.py).

## Tasks

- [ ] **Task 1** — Edit `apps/api/scripts/reindex.py`: agregar path manipulation después de stdlib imports.
- [ ] **Task 2** — Verificar: el script corre en AMBOS modos (script directo y módulo) sin ModuleNotFoundError. Commit work-unit.

## Convenciones

- Conventional commits en español, scope `api`
- Sin `Co-Authored-By`
- Mensaje atómico: solo el fix del path

## Notas

Este es el mismo patrón que el bug de `ingest_repo.py` (commits `e0a7284` + `f990d0a`). Vale auditar el resto de los scripts CLI del proyecto para ver si tienen el mismo problema (no en alcance de este task — para un commit separado si querés).