"""CLI to reindex project .md files into ChromaDB.

Usage:
    python scripts/reindex.py [--force] [--projects-dir PATH]
    python -m scripts.reindex [--force] [--projects-dir PATH]

Defaults:
    projects_dir = apps/api/data/projects/
    force = False (use True for first run or schema change)

Exit codes:
    0 - success (even with per-project errors skipped, as long as the
        overall batch completed)
    1 - fatal error (projects_dir missing, or any per-project error)
"""

import argparse
import sys
from pathlib import Path


def main() -> None:
    """Parse args, build the ProjectsService, run ingest_all, print results."""
    # Make 'backend' importable when run as a script: python scripts/reindex.py.
    # When run as -m, the cwd is already on sys.path so this is a no-op.
    _app_root = str(Path(__file__).resolve().parent.parent)
    if _app_root not in sys.path:
        sys.path.insert(0, _app_root)

    from backend.config import Settings
    from backend.rag.embedder import Embedder
    from backend.rag.vector_store import VectorStore
    from backend.services.projects_service import ProjectsService

    parser = argparse.ArgumentParser(description="Reindex project .md files")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete collections before upsert (use for first run or schema change).",
    )
    parser.add_argument(
        "--projects-dir",
        type=Path,
        default=None,
        help="Path to projects dir (default: apps/api/data/projects/).",
    )
    args = parser.parse_args()

    settings = Settings()
    projects_dir = args.projects_dir or (
        Path(__file__).parent.parent / "data" / "projects"
    )

    if not projects_dir.exists():
        print(f"ERROR: projects_dir does not exist: {projects_dir}", file=sys.stderr)
        sys.exit(1)

    store = VectorStore(settings.CHROMA_PERSIST_DIR)
    embedder = Embedder(
        base_url=settings.embedding_base_urlEffective,
        api_key=settings.embedding_api_keyEffective,
        model=settings.EMBEDDING_MODEL,
    )
    service = ProjectsService(embedder=embedder, store=store, settings=settings)

    print(f"Reindexing {projects_dir} (force={args.force})...")
    result = service.ingest_all(projects_dir, force=args.force)

    print(f"Done in {result.duration_ms}ms")
    print(f"  Indexed projects: {result.indexed_projects}")
    print(f"  Index chunks: {result.index_chunks}")
    print(f"  Detail chunks: {result.detail_chunks_total}")
    print(f"  Slugs: {result.project_slugs}")
    if result.errors:
        print(f"  Errors ({len(result.errors)}):")
        for err in result.errors:
            print(f"    - {err}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
