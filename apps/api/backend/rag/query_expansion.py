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
import unicodedata


def _strip_accents(s: str) -> str:
    """Remove diacritics: 'migración' -> 'migracion', 'café' -> 'cafe'.

    Uses NFKD decomposition and drops the resulting combining marks. The
    recruiter-style Spanish keyword map is ASCII (no tildes), so we normalize
    the user query the same way before matching.
    """
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


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
    # Spanish-recruiter-style keywords (accent-insensitive on match).
    "cloud": "cloud nube AWS GCP Azure kubernetes infraestructura cloud computing",
    "migracion": "migración cloud AWS Kubernetes Terraform monolito microservicios migración cutover",
    "nube": "nube cloud AWS GCP Azure infraestructura cloud computing",
    "monolito": "monolito microservicios migración refactorización strangler pattern",
    "microservicios": "microservicios arquitectura distribuida Kubernetes Docker APIs",
    "frontend": "frontend interfaz UI React Astro TypeScript componente cliente",
    "backend": "backend API servidor FastAPI Python REST endpoints",
    "data engineering": "data engineering pipelines ETL Spark Kafka processing",
    "infraestructura": "infraestructura Terraform AWS Kubernetes provisionamiento IaC",
    "senior": "senior lead tech lead principal staff engineer mentoría",
    "tech lead": "tech lead liderazgo técnico mentoría arquitectura decisiones",
    "mentoring": "mentoring mentoría coaching liderazgo 1:1 feedback",
    "orquestacion": "orquestación Kubernetes containers scheduling",
    "integracion": "integración APIs REST GraphQL eventos messaging",
}


# Store both the original (with-tilde) key and the accent-normalized form so
# queries typed without diacritics ("migracion") match Spanish keys, while
# the original (with-tilde) expansion string is still appended so the
# embedder sees proper Spanish context. Insertion order of
# KEYWORD_EXPANSIONS is preserved so expansion order is deterministic
# (helps stable test output and reproducible embeddings).
_KEYWORD_FORMS: list[tuple[str, str, str]] = [
    (kw, _strip_accents(kw.lower()), expansion)
    for kw, expansion in KEYWORD_EXPANSIONS.items()
]
# Pre-compiled patterns on the normalized key, paired with the original
# expansion string. Not consumed by expand_query today, but kept so
# external callers can reuse the same accent-insensitive lookup.
_KEYWORD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(norm_kw) + r"\b", re.IGNORECASE), expansion)
    for _orig_kw, norm_kw, expansion in _KEYWORD_FORMS
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

    # Normalize the user query so 'migracion' and 'migración' both match.
    question_norm = _strip_accents(question.lower())

    expansions_to_add: list[str] = []
    seen: set[str] = set()
    for _orig_kw, norm_kw, expansion in _KEYWORD_FORMS:
        if (
            re.search(r"\b" + re.escape(norm_kw) + r"\b", question_norm)
            and expansion not in seen
        ):
            expansions_to_add.append(expansion)
            seen.add(expansion)

    if not expansions_to_add:
        return question

    return question + " " + " ".join(expansions_to_add)
