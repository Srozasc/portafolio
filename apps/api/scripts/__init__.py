"""CLI scripts for the portafolio API.

Run from the apps/api directory using the module form so that the
backend package (sibling of this directory) is importable:

    python -m scripts.reindex [args]
    python -m scripts.ingest_repo [args]

Available scripts:
    reindex     Re-ingest project .md files into ChromaDB.
    ingest_repo Ingest a single GitHub repo into projects/ as a .md.
"""
