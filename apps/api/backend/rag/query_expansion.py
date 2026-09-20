"""Static query expansion for short keyword queries.

OpenAI text-embedding-3-small is trained on contexts/sentences, not
isolated words. A user typing "rag" alone gets a low-quality embedding
that doesn't match any chunk in projects_index, so the retriever returns
0 hits and the bot deflects. This module expands short queries that
match a known tech keyword by appending a richer context string before
embedding, so the embedder has enough signal.

Pure CPU work, no LLM call, no extra latency or cost.
"""

from __future__ import annotations

import re

# Map of canonical keyword -> human-readable expansion string.
# Keys are lowercase; match is case-insensitive on the query.
# Keep expansions short and additive — we APPEND, not REPLACE, the original.
KEYWORD_EXPANSIONS: dict[str, str] = {
    "rag": "retrieval augmented generation LLM chatbot knowledge base documentos",
    "llm": "large language model LLM GPT text generation prompts",
    "ai": "artificial intelligence AI machine learning models",
    "ml": "machine learning ML modelos entrenamiento inferencia",
    "python": "python lenguaje programacion backend scripting",
    "aws": "amazon web services AWS cloud infraestructura EC2 Lambda S3",
    "gcp": "google cloud platform GCP cloud infraestructura",
    "azure": "microsoft azure cloud infraestructura",
    "k8s": "kubernetes k8s containers orquestacion",
    "kubernetes": "kubernetes containers orquestacion deploy",
    "docker": "docker containers imagenes build",
    "terraform": "terraform infrastructure as code IaC provisionamiento",
    "kafka": "apache kafka streaming eventos pub sub",
    "spark": "apache spark data processing batch streaming",
    "fastapi": "fastapi python backend API REST async",
    "typescript": "typescript javascript tipado frontend",
    "react": "react frontend components SPA",
    "astro": "astro sitios estaticos islands SSG",
    "postgres": "postgres postgresql base de datos SQL",
    "redis": "redis cache key value",
    "graphql": "graphql API queries",
    "sse": "server-sent events streaming HTTP",
    "ci/cd": "CI CD pipelines deploy automatizacion",
    "devops": "devops SRE infraestructura operacion",
    "fintech": "fintech banca finanzas pagos",
    "scoring": "scoring crediticio riesgo modelos",
    "fraud": "fraude deteccion risk monitoring transacciones",
    "i18n": "internacionalizacion i18n traduccion multilingual",
    "fullstack": "fullstack frontend backend",
    "data": "data engineering pipelines procesamiento datos",
    "realtime": "tiempo real real time streaming baja latencia",
}


# Pre-compiled patterns for fast, case-insensitive, word-boundary matching.
# Insertion order of KEYWORD_EXPANSIONS is preserved so expansion order is
# deterministic (helps stable test output and reproducible embeddings).
_KEYWORD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE), expansion)
    for kw, expansion in KEYWORD_EXPANSIONS.items()
]


def expand_query(question: str) -> str:
    """Expand a short query with known tech keywords.

    Rules:
      - If `question` has more than 4 whitespace-separated tokens, return
        it unchanged (already a full sentence — no expansion needed).
      - Otherwise, scan for any keyword from KEYWORD_EXPANSIONS (case-
        insensitive, word-boundary). For each match, APPEND the
        expansion to the original (don't replace the original wording).
      - Return the expanded question. If no keyword matches, return the
        original unchanged.

    Args:
        question: The raw user question.

    Returns:
        The question string, possibly with expansion suffixes appended.
    """
    tokens = question.split()
    if len(tokens) > 4:
        return question

    expansions_to_add: list[str] = []
    seen: set[str] = set()
    for pattern, expansion in _KEYWORD_PATTERNS:
        if pattern.search(question) and expansion not in seen:
            expansions_to_add.append(expansion)
            seen.add(expansion)

    if not expansions_to_add:
        return question

    return question + " " + " ".join(expansions_to_add)
