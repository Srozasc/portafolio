from __future__ import annotations

"""CLI to ingest a single GitHub repo into the portfolio projects directory.

Usage:
    python apps/api/scripts/ingest_repo.py --repo owner/repo [--token GITHUB_TOKEN] \\
        [--projects-dir PATH] [--dry-run]

Implemented in this iteration:
  - parse_repo_ref            accepts shorthand 'owner/repo', https/http URL, ssh form
  - slugify_repo_name         derives 'proj-<kebab>' slug, max 60 chars total
  - GitHubClient              get_repo + get_readme over httpx (transport-injectable)
  - validate_frontmatter      Python mirror of apps/web/src/content/config.ts
  - build_frontmatter         GitHub repo -> portfolio frontmatter
  - write_project_md          atomic write (tmp + rename), --force aware
  - detect_language           heuristica ES/EN con stopwords (fallback 'en')
  - rewrite_image_urls_to_absolute    ![alt](path) y <img src> → raw.githubusercontent.com

Pending tasks (see odd/tasks/ingest-repo-from-github.md): LLM translation,
role/client prompt, branch + draft PR, --force / --update, docs + E2E smoke test.

Exit codes:
    0 - success (including dry-run)
    1 - fatal error (invalid input, GitHub API error, network failure)
"""

import argparse
import contextlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Self

import httpx
import yaml

from backend.rag.llm_client import LLMClient, StreamError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum total length of a derived slug, including the 'proj-' prefix.
#: The Astro/Zod schema does not cap length; 60 keeps URLs readable.
SLUG_MAX_TOTAL = 60


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GitHubError(Exception):
    """Raised when the GitHub API returns an error or the network fails.

    The message is intentionally user-facing and contains remediation hints
    (e.g. mentions GITHUB_TOKEN when 401). Do not interpolate raw SDK text.
    """


class FrontmatterValidationError(Exception):
    """Raised when a frontmatter dict fails the portfolio schema.

    The Python schema mirrors apps/web/src/content/config.ts. Keep both in
    sync; the TS schema is the source of truth for Astro at build time,
    this Python version validates before any file is written.
    """


class ProjectExistsError(Exception):
    """Raised by write_project_md when the target .md exists and force=False."""


# ---------------------------------------------------------------------------
# Pure helpers (no I/O)
# ---------------------------------------------------------------------------


def parse_repo_ref(ref: str) -> tuple[str, str]:
    """Parse a GitHub repo reference into ``(owner, repo)``.

    Accepted forms:
      - ``owner/repo``
      - ``https://github.com/owner/repo[.git][/anything]``
      - ``http://github.com/owner/repo[.git][/anything]``
      - ``git@github.com:owner/repo.git``

    Surrounding whitespace is stripped.

    Raises:
        ValueError: if the input is empty, whitespace-only, or does not
            match any accepted form.
    """
    s = ref.strip()
    if not s:
        raise ValueError("repo ref is empty")

    # SSH form: git@github.com:owner/repo.git
    m = re.match(r"^git@github\.com:([^/\s]+)/([^/\s]+?)(?:\.git)?$", s)
    if m:
        return m.group(1), m.group(2)

    # https/http form: https://github.com/owner/repo[.git][/...]
    m = re.match(r"^https?://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?(?:/.*)?$", s)
    if m:
        return m.group(1), m.group(2)

    # Shorthand: owner/repo (no extra path components).
    m = re.match(r"^([^/\s]+)/([^/\s]+?)(?:\.git)?$", s)
    if m:
        return m.group(1), m.group(2)

    raise ValueError(f"invalid repo ref: {ref!r}")


def slugify_repo_name(name: str) -> str:
    """Derive a portfolio slug ``proj-<kebab>`` from a GitHub repo name.

    Rules:
      - Lowercase the input.
      - Replace any run of non ``[a-z0-9]`` characters with a single hyphen.
      - Collapse repeated hyphens; strip leading/trailing hyphens.
      - Prepend ``proj-`` so the result matches the Zod schema
        ``/^proj-[a-z0-9-]+$/``.
      - Truncate to a maximum of ``SLUG_MAX_TOTAL`` total characters,
        stripping any trailing hyphen left by the cut.

    Raises:
        ValueError: if the input is empty or contains no alphanumeric chars.
    """
    if not name or not name.strip():
        raise ValueError("repo name is empty")

    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s)
    s = s.strip("-")

    if not s:
        raise ValueError(f"repo name {name!r} yields empty slug")

    prefix = "proj-"
    max_body = SLUG_MAX_TOTAL - len(prefix)
    if len(s) > max_body:
        s = s[:max_body].rstrip("-")
        if not s:
            raise ValueError(f"repo name {name!r} yields empty slug after truncation")

    return prefix + s


# ---------------------------------------------------------------------------
# Schema validation (mirrors apps/web/src/content/config.ts)
# ---------------------------------------------------------------------------

SLUG_REGEX = re.compile(r"^proj-[a-z0-9-]+$")
MIN_TITLE_LEN = 3
MIN_SUMMARY_LEN = 20
YEAR_MIN, YEAR_MAX = 2000, 2100
MIN_TAGS = 1
MIN_STACK = 1


def validate_frontmatter(fm: dict) -> None:
    """Validate a frontmatter dict against the portfolio project schema.

    Mirrors apps/web/src/content/config.ts. Raises FrontmatterValidationError
    with a message identifying the offending field and value.
    """
    if not isinstance(fm, dict):
        raise FrontmatterValidationError(
            f"frontmatter must be a dict: got {type(fm).__name__}"
        )

    slug = fm.get("slug")
    if not isinstance(slug, str) or not SLUG_REGEX.match(slug):
        raise FrontmatterValidationError(
            f"slug must match /^proj-[a-z0-9-]+$/: got {slug!r}"
        )

    for key in ("title_es", "title_en"):
        v = fm.get(key)
        if not isinstance(v, str) or len(v) < MIN_TITLE_LEN:
            raise FrontmatterValidationError(
                f"{key} must be string of length >= {MIN_TITLE_LEN}: got {v!r}"
            )

    year = fm.get("year")
    # bool is a subclass of int in Python; reject it explicitly.
    if (
        not isinstance(year, int)
        or isinstance(year, bool)
        or year < YEAR_MIN
        or year > YEAR_MAX
    ):
        raise FrontmatterValidationError(
            f"year must be int in [{YEAR_MIN}, {YEAR_MAX}]: got {year!r}"
        )

    for key in ("role_es", "role_en"):
        v = fm.get(key)
        if not isinstance(v, str):
            raise FrontmatterValidationError(f"{key} must be string: got {v!r}")

    tags = fm.get("tags")
    if (
        not isinstance(tags, list)
        or len(tags) < MIN_TAGS
        or not all(isinstance(t, str) for t in tags)
    ):
        raise FrontmatterValidationError(
            f"tags must be non-empty array of strings: got {tags!r}"
        )

    for key in ("stack_es", "stack_en"):
        v = fm.get(key)
        if (
            not isinstance(v, list)
            or len(v) < MIN_STACK
            or not all(isinstance(s, str) for s in v)
        ):
            raise FrontmatterValidationError(
                f"{key} must be non-empty array of strings: got {v!r}"
            )

    for key in ("summary_es", "summary_en"):
        v = fm.get(key)
        if not isinstance(v, str) or len(v) < MIN_SUMMARY_LEN:
            raise FrontmatterValidationError(
                f"{key} must be string of length >= {MIN_SUMMARY_LEN}: got {v!r}"
            )

    client = fm.get("client")
    if client is not None and not isinstance(client, str):
        raise FrontmatterValidationError(
            f"client must be string or null: got {client!r}"
        )

    for key in ("impact_es", "impact_en"):
        if key not in fm or fm[key] is None:
            continue
        v = fm[key]
        if not isinstance(v, list) or not all(isinstance(s, str) for s in v):
            raise FrontmatterValidationError(
                f"{key} must be array of strings or null: got {v!r}"
            )

    links = fm.get("links")
    if links is not None:
        if not isinstance(links, dict):
            raise FrontmatterValidationError(
                f"links must be object or null: got {links!r}"
            )
        for k in ("repo", "demo", "case_study"):
            if k not in links:
                continue
            v = links[k]
            if v is None:
                continue
            if not isinstance(v, str):
                raise FrontmatterValidationError(
                    f"links.{k} must be string URL or null: got {v!r}"
                )
            if k in ("repo", "demo") and not v.startswith(("http://", "https://")):
                raise FrontmatterValidationError(
                    f"links.{k} must be an http(s) URL: got {v!r}"
                )


# ---------------------------------------------------------------------------
# Frontmatter builder
# ---------------------------------------------------------------------------

PLACEHOLDER_TITLE_OTHER_LANG = "_(traduccion pendiente)_"  # 22 chars (Zod-safe)
PLACEHOLDER_SUMMARY_OTHER_LANG = (
    "_(traduccion pendiente — ver summary del idioma detectado)_"  # Zod-safe length
)


def humanize_repo_name(name: str) -> str:
    """Turn a repo name into a human-readable title.

    Examples:
        "my-cool-repo"  -> "My Cool Repo"
        "My-Cool-Repo"  -> "My Cool Repo"
        "SafeGateway"   -> "Safe Gateway"     # CamelCase split
        "myRepo"        -> "My Repo"          # CamelCase split
        "HiRag15k"      -> "Hi Rag15k"

    Splits on ``-`` / ``_`` separators AND on CamelCase boundaries:
    - ``(?<=[a-z])(?=[A-Z])`` inserts a space at lower→upper transitions
      (e.g., "safeGateway" → "safe Gateway")
    - ``(?<=[A-Z])(?=[A-Z][a-z])`` inserts a space at upper-upper→lower
      transitions (e.g., "SafeGateway" when there's a 2+ uppercase run
      like "ABDef" → "AB Def")
    Then ``.title()`` capitalizes each word.
    """
    # Insert spaces at CamelCase boundaries before normalizing separators.
    camel_split = re.sub(
        r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name
    )
    return re.sub(r"[-_]+", " ", camel_split).strip().title()


def build_frontmatter(
    repo_data: dict,
    role: str,
    detected_lang: str,
    *,
    llm_client=None,
    readme_text: str = "",
) -> dict:
    """Build a portfolio frontmatter dict from GitHub repo metadata.

    ``llm_client`` is duck-typed (must have a ``chat(system, user, **kwargs)
    -> str`` method). Tests pass a mock; production passes an LLMClient.
    Type annotation is intentionally loose so pyright accepts both the
    real client and mocks without requiring structural compatibility.

    Args:
        repo_data: parsed JSON from GitHub /repos/{owner}/{repo}.
        role: human role on the project (e.g. "Tech Lead"). Used for both
            role_es and role_en (role strings usually cross-locale).
        detected_lang: 'es' or 'en' — the language detected in the README.
            Fields for this language get real content; fields for the other
            language get a Zod-safe placeholder (>= 20 chars) marked for
            later translation by task T4 or a human reviewer.

    Returns:
        A dict matching the portfolio schema. Call validate_frontmatter()
        on the result before passing it to write_project_md().

    Raises:
        ValueError: if detected_lang is not 'es' or 'en', role is empty,
            or llm_client is None.
        RuntimeError: propagated from ``generate_tags_with_llm()`` if the
            LLM fails or returns invalid output.
    """
    if detected_lang not in ("es", "en"):
        raise ValueError(f"detected_lang must be 'es' or 'en': got {detected_lang!r}")
    if not role or not role.strip():
        raise ValueError("role must be a non-empty string")
    if llm_client is None:
        raise ValueError(
            "llm_client is required to generate portfolio tags. "
            "Pass an LLMClient or mock with a chat() method to build_frontmatter()."
        )

    name = repo_data["name"]
    slug = slugify_repo_name(name)

    created_at = repo_data.get("created_at") or ""
    try:
        year = int(created_at[:4])
    except (ValueError, TypeError):
        year = 2024
    if year < YEAR_MIN or year > YEAR_MAX:
        year = 2024

    title = humanize_repo_name(name)

    description = (repo_data.get("description") or "").strip()
    summary = description
    if len(summary) < MIN_SUMMARY_LEN:
        if summary:
            summary = (
                f"{summary} (ver README del repositorio para la descripcion completa)"
            )
        else:
            summary = "Proyecto sin descripcion (ver README del repositorio)."
    if len(summary) < MIN_SUMMARY_LEN:
        summary = summary + " " * (MIN_SUMMARY_LEN - len(summary))

    lang = repo_data.get("language")
    topics = list(repo_data.get("topics") or [])
    stack: list = []
    seen: set = set()
    for item in ([lang] if lang else []) + topics:
        if not isinstance(item, str) or not item:
            continue
        if item.lower() in seen:
            continue
        seen.add(item.lower())
        stack.append(item)

    # Tags: existing (language + topics) + LLM-generated, dedup case-insensitive.
    # Per user policy, LLM is REQUIRED and its failure is loud (RuntimeError).
    existing_tags: list = []
    tags_seen: set = set()
    for item in ([lang] if lang else []) + topics:
        if not isinstance(item, str) or not item:
            continue
        tag = item.lower()
        if tag in tags_seen:
            continue
        tags_seen.add(tag)
        existing_tags.append(tag)

    llm_tags = generate_tags_with_llm(
        readme_text=readme_text,
        description=description,
        language=lang,
        existing_topics=topics,
        llm_client=llm_client,
    )
    tags = list(existing_tags)
    for tag in llm_tags:
        if tag not in tags_seen:
            tags_seen.add(tag)
            tags.append(tag)

    html_url = repo_data.get("html_url") or None
    if isinstance(html_url, str) and not html_url.startswith(("http://", "https://")):
        html_url = None

    if detected_lang == "en":
        title_en, title_es = title, PLACEHOLDER_TITLE_OTHER_LANG
        summary_en, summary_es = summary, PLACEHOLDER_SUMMARY_OTHER_LANG
    else:
        title_es, title_en = title, PLACEHOLDER_TITLE_OTHER_LANG
        summary_es, summary_en = summary, PLACEHOLDER_SUMMARY_OTHER_LANG

    return {
        "slug": slug,
        "title_es": title_es,
        "title_en": title_en,
        "year": year,
        "role_es": role,
        "role_en": role,
        "tags": tags,
        "stack_es": list(stack),
        "stack_en": list(stack),
        "summary_es": summary_es,
        "summary_en": summary_en,
        "client": None,
        "impact_es": None,
        "impact_en": None,
        "links": {
            "repo": html_url,
            "demo": None,
            "case_study": None,
        },
    }


# ---------------------------------------------------------------------------
# Translation (LLM-driven, T4)
# ---------------------------------------------------------------------------

_LANG_NAMES: dict[str, str] = {"es": "Spanish", "en": "English"}

_TRANSLATION_SYSTEM_PROMPT = (
    "You are a precise translator for portfolio project metadata. "
    "Preserve proper names and technical terms verbatim. "
    "Always respond with a JSON object — never with prose, markdown, "
    "or code fences."
)

# Vocabulary of preferred tags, derived from the seed projects. The LLM
# is steered toward these terms when generating new tags so the RAG
# vocabulary stays consistent across ingests. Domain-specific terms
# (e.g., "circuit-breaker", "rate-limiting") are added on top by the LLM
# when relevant — this set is the *floor*, not the ceiling.
_KNOWN_TAGS_VOCABULARY: frozenset[str] = frozenset(
    {
        # Tech
        "python",
        "typescript",
        "javascript",
        "rust",
        "go",
        "aws",
        "gcp",
        "azure",
        "kubernetes",
        "docker",
        "terraform",
        "kafka",
        "rabbitmq",
        "redis",
        "postgresql",
        "mongodb",
        "fastapi",
        "flask",
        "django",
        "react",
        "vue",
        "astro",
        "spark",
        "flink",
        "airflow",
        "openai",
        "llm",
        "rag",
        "vector-db",
        "chromadb",
        "pinecone",
        "ml",
        "mlops",
        "aws-sagemaker",
        # Domain
        "data-engineering",
        "real-time",
        "fraud-detection",
        "senior",
        "tech-lead",
        "fullstack",
        "backend",
        "frontend",
        "i18n",
        "sse",
        "rest-api",
        "graphql",
        # Other
        "microservices",
        "monolith",
        "ci-cd",
        "devops",
        "observability",
    }
)

_TAG_GENERATION_SYSTEM_PROMPT = (
    "You are a portfolio tagging assistant. "
    "Output ONLY a JSON array of strings — no prose, no markdown, "
    "no code fences. Tags are lowercase with kebab-case for multi-word."
)

_TAG_GENERATION_USER_TEMPLATE = """Generate exactly 5 tags for a portfolio project.

**Project description**: {description}
**Primary language**: {language}
**Existing GitHub topics**: {existing_topics}
**README (excerpt, first 2000 chars)**:
```
{readme_excerpt}
```

**Preferred vocabulary** (prefer these when they apply): {vocab}

Rules:
- Output EXACTLY 5 tags (not 4, not 6).
- Lowercase, kebab-case for multi-word (e.g., "circuit-breaker").
- Prefer terms from the preferred vocabulary when they match the project's domain.
- Add domain-specific terms when clearly relevant (e.g., "rate-limiting", "api-gateway", "circuit-breaker").
- Do not invent terms that don't apply to the project.
- Output ONLY a JSON array. No commentary, no markdown, no code fences.
"""

_TRANSLATION_PROMPT_TEMPLATE = """Translate these portfolio project metadata fields from {source_name} to {target_name}.

Rules:
- Preserve proper names and technical terms verbatim (e.g., "Python", "AWS", "Kubernetes", product names, person names, company names).
- Do not invent, remove, or reorder information.
- Match the tone and length of the original.
- Return ONLY a JSON object with the same keys and translated values.

Input:
{input_json}
"""

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict | None:
    """Extract a JSON object from an LLM response.

    Handles:
      - Raw JSON: {"title": "..."}
      - Code-fenced JSON: ```json ... ``` or ``` ... ```
      - Preamble text before JSON: "Here is the result: {...}"

    Returns the first parseable JSON object found, or None if none parse.
    """
    # Strategy 1: strip code fences and try the whole cleaned text.
    cleaned = re.sub(r"```(?:json)?\s*\n?|\n?```", "", text).strip()
    if cleaned:
        try:
            obj = json.loads(cleaned)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # Strategy 2: find the first balanced {...} block in the cleaned text.
    # For our flat dict responses, [^{}]* is enough; nested braces would
    # not be produced by the LLM in this translation prompt.
    for match in re.finditer(r"\{[^{}]*\}", cleaned or text):
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    return None


def translate_fields(
    fields: dict[str, str],
    source_lang: str,
    target_lang: str,
    llm: LLMClient,
) -> dict[str, str]:
    """Translate a dict of fields from source_lang to target_lang via the LLM.

    Falls back gracefully (T4.4): if the LLM response is unparseable,
    missing keys, or any LLM error occurs, returns the original fields
    unchanged and logs a warning.

    Args:
        fields: Dict of field-name → text to translate. Values must be strings.
        source_lang: 'es' or 'en' — language of the input.
        target_lang: 'es' or 'en' — language to translate into.
        llm: LLMClient instance to use for translation.

    Returns:
        A new dict with the same keys as ``fields``. Each value is the
        translated text if successful, or the original text if translation
        failed for that key.

    Raises:
        ValueError: If source_lang or target_lang is not 'es' or 'en'.
    """
    if source_lang not in ("es", "en"):
        raise ValueError(f"only es/en supported for source_lang, got {source_lang!r}")
    if target_lang not in ("es", "en"):
        raise ValueError(f"only es/en supported for target_lang, got {target_lang!r}")
    if not fields:
        return {}
    if source_lang == target_lang:
        return dict(fields)

    user_prompt = _TRANSLATION_PROMPT_TEMPLATE.format(
        source_name=_LANG_NAMES[source_lang],
        target_name=_LANG_NAMES[target_lang],
        input_json=json.dumps(fields, ensure_ascii=False, indent=2),
    )

    try:
        raw = llm.chat(_TRANSLATION_SYSTEM_PROMPT, user_prompt)
    except StreamError as exc:
        # T4.4: graceful fallback. Keep originals.
        logger.warning("LLM translation failed (%s); keeping original fields", exc)
        return dict(fields)

    parsed = _extract_json(raw)
    if not isinstance(parsed, dict):
        logger.warning("LLM translation response was not a JSON object: %r", raw[:200])
        return dict(fields)

    result: dict[str, str] = {}
    for key, original in fields.items():
        translated = parsed.get(key)
        if isinstance(translated, str) and translated.strip():
            result[key] = translated
        else:
            # Key missing, non-string, or empty → fall back to original.
            result[key] = original
    return result


# ---------------------------------------------------------------------------
# Language detection & image rewriting
# ---------------------------------------------------------------------------

#: Spanish stopwords used by :func:`detect_language` to score how likely a
#: README is in Spanish. Curated to cover articles, prepositions, common
#: pronouns, auxiliary verbs and frequent adverbs.
ES_STOPWORDS: frozenset[str] = frozenset(
    {
        # artículos
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        # preposiciones
        "de",
        "del",
        "en",
        "a",
        "por",
        "con",
        "para",
        "sin",
        "sobre",
        "entre",
        "hasta",
        "desde",
        "al",
        # conjunciones / relativo
        "y",
        "o",
        "pero",
        "ni",
        "que",
        "si",
        "como",
        "cuando",
        "donde",
        "mientras",
        "aunque",
        "porque",
        # pronombres
        "yo",
        "tu",
        "él",
        "ella",
        "nosotros",
        "ellos",
        "ellas",
        "me",
        "te",
        "se",
        "nos",
        "le",
        "les",
        "lo",
        "mi",
        "su",
        "nuestro",
        "vuestro",
        "sus",
        "este",
        "esta",
        "estos",
        "estas",
        "ese",
        "esa",
        "esos",
        "esas",
        "aquel",
        "aquella",
        "aquellos",
        "aquellas",
        # verbos comunes
        "es",
        "son",
        "ser",
        "estar",
        "está",
        "están",
        "era",
        "eran",
        "fue",
        "fueron",
        "ha",
        "han",
        "había",
        "he",
        "has",
        "hay",
        "tiene",
        "tienen",
        "tenía",
        # adverbios
        "no",
        "sí",
        "muy",
        "más",
        "menos",
        "también",
        "ya",
        "aún",
        "todavía",
        "aquí",
        "allí",
        "ahora",
        "entonces",
        "bien",
        # otros
        "todo",
        "todos",
        "cada",
    }
)

#: English stopwords used by :func:`detect_language` to score how likely a
#: README is in English. Curated to mirror ES_STOPWORDS for symmetry.
EN_STOPWORDS: frozenset[str] = frozenset(
    {
        # artículos
        "the",
        "a",
        "an",
        # preposiciones
        "of",
        "in",
        "on",
        "to",
        "for",
        "with",
        "at",
        "by",
        "from",
        "into",
        "over",
        "under",
        "between",
        "through",
        "during",
        "before",
        "after",
        "about",
        "against",
        "without",
        # conjunciones / relativo
        "and",
        "or",
        "but",
        "nor",
        "so",
        "yet",
        "because",
        "if",
        "when",
        "where",
        "while",
        "although",
        "since",
        "unless",
        "until",
        # pronombres
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "its",
        "our",
        "their",
        "this",
        "that",
        "these",
        "those",
        # verbos auxiliares / comunes
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "having",
        "do",
        "does",
        "did",
        "doing",
        "will",
        "would",
        "should",
        "could",
        "can",
        "may",
        "might",
        "must",
        # adverbios
        "not",
        "no",
        "yes",
        "very",
        "more",
        "less",
        "also",
        "just",
        "only",
        "even",
        "still",
        "already",
        "here",
        "there",
        "now",
        "then",
        "well",
        "too",
        "much",
        "many",
        "some",
        "any",
        "all",
        "every",
    }
)

# Noise patterns stripped before counting stopwords.
_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]+`")
_URL = re.compile(r"https?://\S+")
_HTML_TAG = re.compile(r"<[^>]+>")

# Tokenizer for language detection. Matches runs of letters incl. Spanish
# accented chars (Unicode Latin-1 Supplement).
_WORDS = re.compile(r"[a-záéíóúñü]+", re.IGNORECASE)

# Markdown image: `![alt](path)` with optional title `![alt](path "title")`.
# Group 3 captures the title (including the leading space) or empty string.
# Lazy match so alt may contain brackets/text within reason.
_MD_IMAGE = re.compile(
    r'!\[(.*?)\]\(([^)\s]+)((?:\s+"[^"]*")?)\)',
    re.DOTALL,
)

# HTML <img> whole-tag matcher (case-insensitive).
_HTML_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)

# src="..." or src='...' inside an <img> tag.
_HTML_IMG_SRC = re.compile(r'src=(["\'])([^"\']*?)\1', re.IGNORECASE)


def detect_language(readme_text: str) -> str:
    """Detect whether a README is primarily Spanish or English.

    Heuristic: strip code blocks, inline code, URLs and HTML tags; count
    stopword matches (tokens of length >= 3 only, to avoid 1-2 char
    ambiguous words like ``"a"``, ``"y"``, ``"of"``) for ES and EN;
    return ``"es"`` if ES wins, otherwise ``"en"``. Empty/blank input and
    ties fall back to ``"en"``.

    Returns:
        ``"es"`` or ``"en"``.
    """
    if not readme_text or not readme_text.strip():
        return "en"

    txt = _FENCED_CODE.sub(" ", readme_text)
    txt = _INLINE_CODE.sub(" ", txt)
    txt = _URL.sub(" ", txt)
    txt = _HTML_TAG.sub(" ", txt)

    tokens = [t.lower() for t in _WORDS.findall(txt) if len(t) >= 3]
    if not tokens:
        return "en"

    es = sum(1 for t in tokens if t in ES_STOPWORDS)
    en = sum(1 for t in tokens if t in EN_STOPWORDS)

    return "es" if es > en else "en"


def rewrite_image_urls_to_absolute(
    readme_text: str,
    owner: str,
    repo: str,
    branch: str,
) -> str:
    """Rewrite relative image URLs in a README to absolute raw.githubusercontent URLs.

    Handles both Markdown ``![alt](path)`` (with optional title) and HTML
    ``<img src="path">`` forms. Leaves alone: absolute URLs (http/https),
    data URLs, mailto, and anchor links (``#anchor``). Relative paths are
    resolved from the repo root (where READMEs sit); ``..`` segments
    clamp at the root.
    """
    if not readme_text:
        return readme_text

    base = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/"

    def _resolve(path: str) -> str | None:
        if not path:
            return None
        if path.startswith(("http://", "https://", "data:", "mailto:", "#")):
            return None
        # Strip leading ./ segments
        cleaned = path
        while cleaned.startswith("./"):
            cleaned = cleaned[2:]
        # Resolve . and .. segments against the repo root (empty).
        parts = cleaned.split("/")
        resolved: list[str] = []
        for p in parts:
            if p == "" or p == ".":
                continue
            if p == "..":
                if resolved:
                    resolved.pop()
                continue
            resolved.append(p)
        return base + "/".join(resolved)

    def _replace_md(m: re.Match[str]) -> str:
        alt = m.group(1)
        path = m.group(2)
        title = m.group(3)
        new = _resolve(path)
        if new is None:
            return m.group(0)
        return f"![{alt}]({new}{title})"

    def _replace_html(m: re.Match[str]) -> str:
        tag = m.group(0)
        src_match = _HTML_IMG_SRC.search(tag)
        if src_match is None:
            return tag
        quote = src_match.group(1)
        path = src_match.group(2)
        new = _resolve(path)
        if new is None:
            return tag
        # Rewrite only the src="path" within the tag, preserving everything
        # around it (alt, class, style, etc.).
        return (
            tag[: src_match.start()]
            + f"src={quote}{new}{quote}"
            + tag[src_match.end() :]
        )

    text = _MD_IMAGE.sub(_replace_md, readme_text)
    text = _HTML_IMG_TAG.sub(_replace_html, text)
    return text


# ---------------------------------------------------------------------------
# Role intake (.portafolio.yml + interactive prompt) — T5
# ---------------------------------------------------------------------------

DEFAULT_ROLES: dict[str, str] = {"es": "Ingeniero", "en": "Tech Lead"}


class MissingRoleError(Exception):
    """Raised when role loading is required but neither .portafolio.yml
    nor an interactive prompt is available (--non-interactive mode)."""


def parse_portafolio_yml(raw_text: str) -> dict:
    """Parse a .portafolio.yml document into a typed dict.

    Tolerates malformed input: returns an empty dict (with a warning logged)
    on YAML parse errors, non-dict top-level values, or invalid field types.
    Only recognised fields (role, client, summary_extra, impact) appear in
    the result; everything else is ignored.

    Field type validation:
      - role: str (non-empty after strip)
      - client: str
      - summary_extra: str
      - impact: list[str] (non-string items filtered out)
    Keys with wrong types are silently omitted from the result.
    Explicit ``null`` / ``~`` values are treated as missing (key omitted).
    """
    if not raw_text or not raw_text.strip():
        return {}

    try:
        parsed = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        logger.warning("Invalid YAML in .portafolio.yml: %s", exc)
        return {}

    if not isinstance(parsed, dict):
        return {}

    result: dict = {}
    role = parsed.get("role")
    if isinstance(role, str) and role.strip():
        result["role"] = role.strip()

    client = parsed.get("client")
    if isinstance(client, str) and client.strip():
        result["client"] = client.strip()

    summary = parsed.get("summary_extra")
    if isinstance(summary, str) and summary.strip():
        result["summary_extra"] = summary.strip()

    impact = parsed.get("impact")
    if isinstance(impact, list):
        str_items = [s for s in impact if isinstance(s, str) and s.strip()]
        if str_items:
            result["impact"] = [s.strip() for s in str_items]

    return result


def prompt_for_role(lang: str, *, default: str | None = None) -> str:
    """Prompt the user (via input()) for their role on the project.

    Returns the entered string, or ``default`` if the user submits an empty
    line. Default fallback when ``default`` is None is language-specific:
    "Tech Lead" for English, "Ingeniero" for Spanish.

    Raises:
        ValueError: If ``lang`` is not "es" or "en".
    """
    if lang not in DEFAULT_ROLES:
        raise ValueError(f"only es/en supported for role prompt, got {lang!r}")
    fallback = default if default is not None else DEFAULT_ROLES[lang]
    if lang == "es":
        prompt_text = f"¿Cuál fue tu rol en este proyecto? [{fallback}]: "
    else:
        prompt_text = f"What was your role on this project? [{fallback}]: "

    raw = input(prompt_text)
    cleaned = raw.strip()
    return cleaned if cleaned else fallback


def load_role_from_repo(
    github: GitHubClient,
    owner: str,
    repo: str,
    branch: str | None = None,
    *,
    non_interactive: bool = False,
    detected_lang: str = "en",
) -> str:
    """Load the human role from .portafolio.yml on the repo, falling back
    to an interactive prompt.

    Tries .portafolio.yml first, then .portafolio.yaml as a fallback. If
    neither file is present (or both are malformed/empty):

    - If ``non_interactive=False``: prompts the user via input().
    - If ``non_interactive=True``: raises MissingRoleError.

    Returns:
        The role string (non-empty).

    Raises:
        MissingRoleError: If non-interactive and no valid role found in either
            YAML file.
        GitHubError: If the GitHub API call fails for a non-404 reason.
    """
    for filename in (".portafolio.yml", ".portafolio.yaml"):
        raw = github.get_file_content(owner, repo, filename, ref=branch)
        if raw is None:
            continue
        parsed = parse_portafolio_yml(raw)
        role = parsed.get("role")
        if role:
            return role

    # Neither file had a valid role.
    if non_interactive:
        raise MissingRoleError(
            "Cannot determine role: no .portafolio.yml found on the repo "
            "and --non-interactive is set. Either add a .portafolio.yml "
            "with a `role:` field, or run without --non-interactive."
        )

    return prompt_for_role(detected_lang)


# ---------------------------------------------------------------------------
# GitHub REST client
# ---------------------------------------------------------------------------


class GitHubClient:
    """Minimal synchronous GitHub REST client for repo ingest.

    Wraps :class:`httpx.Client`. Accepts an optional ``transport`` so tests
    can inject :class:`httpx.MockTransport` without hitting the network.
    """

    BASE_URL = "https://api.github.com"

    def __init__(
        self,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "portafolio-ingest-repo/0.1",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers=headers,
            transport=transport,
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ----- public API ----------------------------------------------------

    def get_repo(self, owner: str, repo: str) -> dict:
        """Fetch repo metadata. Returns the parsed JSON body as a dict.

        Raises:
            GitHubError: on 401 (token issue), 403 (rate limit),
                404 (not found / no access), other >=400, or network failure.
        """
        try:
            r = self._client.get(f"/repos/{owner}/{repo}")
        except httpx.HTTPError as exc:
            raise GitHubError(f"network error: {type(exc).__name__}") from exc

        if r.status_code == 401:
            raise GitHubError(
                "GitHub API returned 401 Unauthorized. "
                "Check that GITHUB_TOKEN is valid and has repo:read scope."
            )
        if r.status_code == 404:
            raise GitHubError(
                f"repo not found or not accessible: {owner}/{repo} "
                "(is it private? does GITHUB_TOKEN have access?)"
            )
        if r.status_code == 403:
            raise GitHubError(
                f"GitHub API returned 403 Forbidden (rate limit?): {r.text[:200]}"
            )
        if r.status_code >= 400:
            raise GitHubError(f"GitHub API error {r.status_code}: {r.text[:200]}")

        return r.json()

    def get_readme(self, owner: str, repo: str, ref: str | None = None) -> str:
        """Fetch the raw README markdown for the repo.

        Args:
            owner: repo owner.
            repo: repo name.
            ref: optional branch/tag/sha to pin the README to.

        Returns:
            The raw README text as returned by the
            ``application/vnd.github.raw`` media type.

        Raises:
            GitHubError: on 404 (no README), other >=400, or network failure.
        """
        path = f"/repos/{owner}/{repo}/readme"
        headers = {"Accept": "application/vnd.github.raw"}
        params = {"ref": ref} if ref else None
        try:
            r = self._client.get(path, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise GitHubError(f"network error: {type(exc).__name__}") from exc

        if r.status_code == 404:
            raise GitHubError(f"no README found for {owner}/{repo}")
        if r.status_code >= 400:
            raise GitHubError(
                f"GitHub API error {r.status_code} fetching README: {r.text[:200]}"
            )

        return r.text

    def get_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str | None = None,
    ) -> str | None:
        """Fetch the raw content of a file at a given path.

        Calls ``GET /repos/{owner}/{repo}/contents/{path}`` with the raw
        media type. 404 returns ``None`` (file doesn't exist on the repo).
        Other 4xx/5xx raise ``GitHubError``. Network failures raise
        ``GitHubError``.

        Args:
            owner: repo owner.
            repo: repo name.
            path: file path relative to repo root (e.g. ".portafolio.yml").
            ref: optional branch/tag/sha to pin the file content to.

        Returns:
            Raw file content as text, or ``None`` if the file does not exist.

        Raises:
            GitHubError: On 401, 403 (rate limit), other >=400, or network failure.
        """
        endpoint = f"/repos/{owner}/{repo}/contents/{path}"
        headers = {"Accept": "application/vnd.github.raw"}
        params = {"ref": ref} if ref else None
        try:
            r = self._client.get(endpoint, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise GitHubError(f"network error: {type(exc).__name__}") from exc

        if r.status_code == 404:
            return None
        if r.status_code == 401:
            raise GitHubError(
                "GitHub API returned 401 Unauthorized. "
                "Check that GITHUB_TOKEN is valid and has repo:read scope."
            )
        if r.status_code == 403:
            raise GitHubError(
                f"GitHub API returned 403 Forbidden (rate limit?): {r.text[:200]}"
            )
        if r.status_code >= 400:
            raise GitHubError(f"GitHub API error {r.status_code}: {r.text[:200]}")
        return r.text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_repo_summary(repo_data: dict, slug: str, role: str) -> None:
    """Print a human-friendly summary of the repo metadata."""
    print(f"Repo: {repo_data.get('full_name')}")
    print(f"  name:           {repo_data.get('name')}")
    print(f"  description:    {repo_data.get('description') or '(none)'}")
    print(f"  language:       {repo_data.get('language') or '(none)'}")
    topics = repo_data.get("topics") or []
    print(f"  topics:         {topics}")
    print(f"  created_at:     {repo_data.get('created_at')}")
    print(f"  default_branch: {repo_data.get('default_branch')}")
    print(f"  html_url:       {repo_data.get('html_url')}")
    print(f"  derived slug:   {slug}")
    print(f"  role:           {role}")


def generate_tags_with_llm(
    *,
    readme_text: str,
    description: str,
    language: str | None,
    existing_topics: list[str],
    llm_client: LLMClient,
) -> list[str]:
    """Generate exactly 5 portfolio tags for a repo via LLM.

    Uses temperature 0.2 for consistency. Steered by `_KNOWN_TAGS_VOCABULARY`
    as the preferred vocabulary (the LLM adds domain-specific terms on top
    when relevant).

    Args:
        readme_text: Raw README markdown from the repo. Truncated to the
            first 2000 chars before being sent to the LLM.
        description: GitHub repo description (may be empty).
        language: Primary language from GitHub (e.g., "TypeScript"); may be None.
        existing_topics: GitHub topics configured on the repo (may be empty).
        llm_client: An LLMClient instance.

    Returns:
        A list of exactly 5 lowercase tags.

    Raises:
        RuntimeError: If the LLM fails (StreamError), returns invalid JSON,
            returns a non-list, returns the wrong number of tags, or
            returns any non-string tag. **No fallback** — caller must
            handle (per user decision: cancel the ingest).
    """
    readme_excerpt = (readme_text or "")[:2000]
    topics_str = ", ".join(existing_topics) if existing_topics else "(none)"
    vocab_str = ", ".join(sorted(_KNOWN_TAGS_VOCABULARY))
    user_prompt = _TAG_GENERATION_USER_TEMPLATE.format(
        description=description or "(none)",
        language=language or "(unknown)",
        existing_topics=topics_str,
        readme_excerpt=readme_excerpt,
        vocab=vocab_str,
    )

    try:
        response_text = llm_client.chat(
            system=_TAG_GENERATION_SYSTEM_PROMPT,
            user=user_prompt,
            temperature=0.2,
        )
    except StreamError as exc:
        raise RuntimeError(
            f"LLM failed to generate tags: {exc}. Per policy, the ingest is cancelled."
        ) from exc

    # Parse JSON array. The system prompt asks for "ONLY a JSON array"
    # but tolerate prose preamble / code fences as defense.
    import json as _json

    raw = response_text.strip()
    # Strip code fences if present.
    if raw.startswith("```"):
        first_newline = raw.find("\n")
        if first_newline != -1:
            raw = raw[first_newline + 1 :]
        if raw.endswith("```"):
            raw = raw[:-3].rstrip()
    # Try to find the first '[' and last ']' (in case of prose preamble).
    bracket_start = raw.find("[")
    bracket_end = raw.rfind("]")
    if bracket_start != -1 and bracket_end != -1 and bracket_end > bracket_start:
        raw = raw[bracket_start : bracket_end + 1]

    try:
        parsed = _json.loads(raw)
    except _json.JSONDecodeError as exc:
        raise RuntimeError(
            f"LLM returned invalid JSON for tags: {exc}; "
            f"response={response_text[:200]!r}. Per policy, the ingest is cancelled."
        ) from exc

    if not isinstance(parsed, list):
        raise TypeError(
            f"LLM returned non-list for tags: {type(parsed).__name__}; "
            f"response={response_text[:200]!r}. Per policy, the ingest is cancelled."
        )

    tags: list[str] = []
    for item in parsed:
        if not isinstance(item, str) or not item.strip():
            raise RuntimeError(
                f"LLM returned invalid tag entry: {item!r}; "
                f"response={response_text[:200]!r}. Per policy, the ingest is cancelled."
            )
        tags.append(item.strip().lower())

    if len(tags) != 5:
        raise RuntimeError(
            f"LLM returned {len(tags)} tags, expected exactly 5: {tags}. "
            f"Per policy, the ingest is cancelled."
        )

    return tags


def _maybe_translate_frontmatter(
    frontmatter: dict,
    detected_lang: str,
    *,
    llm: LLMClient | None = None,
) -> dict:
    """Translate the secondary-language fields of ``frontmatter`` via the LLM.

    Skips translation when the input for the other language is only the
    placeholder (no real content to translate). On any LLM error
    (unconfigured client, retry exhaustion, parse failure), returns the
    input ``frontmatter`` unchanged (T4.4 fallback — translation is
    best-effort and never aborts the ingest).

    If ``llm`` is provided, uses that instance (preferred path — main()
    creates the LLMClient once and shares it with build_frontmatter for
    tag generation). If ``llm`` is None, lazily creates one (backward
    compat for tests that don't pass an explicit client).
    """
    if detected_lang not in ("es", "en"):
        return frontmatter

    target_lang = "es" if detected_lang == "en" else "en"

    # Map: target field -> source value (use detected-lang content as input).
    if detected_lang == "en":
        fields_to_translate: dict[str, str] = {}
        if (
            isinstance(frontmatter.get("title_en"), str)
            and frontmatter["title_en"] != PLACEHOLDER_TITLE_OTHER_LANG
        ):
            fields_to_translate["title_es"] = frontmatter["title_en"]
        if (
            isinstance(frontmatter.get("summary_en"), str)
            and frontmatter["summary_en"] != PLACEHOLDER_SUMMARY_OTHER_LANG
        ):
            fields_to_translate["summary_es"] = frontmatter["summary_en"]
    else:
        fields_to_translate = {}
        if (
            isinstance(frontmatter.get("title_es"), str)
            and frontmatter["title_es"] != PLACEHOLDER_TITLE_OTHER_LANG
        ):
            fields_to_translate["title_en"] = frontmatter["title_es"]
        if (
            isinstance(frontmatter.get("summary_es"), str)
            and frontmatter["summary_es"] != PLACEHOLDER_SUMMARY_OTHER_LANG
        ):
            fields_to_translate["summary_en"] = frontmatter["summary_es"]

    if not fields_to_translate:
        return frontmatter

    if llm is None:
        # Backward-compat path: lazily create LLMClient if none was passed.
        try:
            # Lazy import to keep the script decoupled from backend.config at
            # import time (Settings reads env at construction; tests may not
            # have env vars set when the script module is imported).
            from backend.config import Settings

            settings = Settings()
            llm = LLMClient(
                base_url=settings.LLM_BASE_URL,
                api_key=settings.LLM_API_KEY,
                model=settings.CHAT_MODEL,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLM unavailable, skipping translation (%s)", type(exc).__name__
            )
            return frontmatter

    try:
        translated = translate_fields(
            fields_to_translate,
            source_lang=detected_lang,
            target_lang=target_lang,
            llm=llm,
        )
    except StreamError as exc:
        logger.warning("Translation failed, keeping originals: %s", exc)
        return frontmatter

    result = dict(frontmatter)
    for key, value in translated.items():
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns process exit code (0 success, 1 fatal)."""
    parser = argparse.ArgumentParser(
        description=(
            "Ingest a single GitHub repo into the portfolio projects directory."
        )
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repo: 'owner/repo' or full URL",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="GitHub token (default: read from GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "--projects-dir",
        type=Path,
        default=None,
        help=(
            "Path to projects dir "
            "(default: apps/api/data/projects/, resolved relative to repo root)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print metadata without writing any file or opening a PR",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Abort if a required value cannot be auto-detected "
        "(e.g. role without .portafolio.yml). No prompts.",
    )
    ingest_mode = parser.add_mutually_exclusive_group()
    ingest_mode.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .md file completely (skip the "
        "role/client/impact preservation).",
    )
    ingest_mode.add_argument(
        "--update",
        action="store_true",
        help="Update existing .md file, preserving human-edited fields "
        "(role_*, client, impact_*). Regenerates derived fields.",
    )
    args = parser.parse_args(argv)

    # ----- 1. parse input ------------------------------------------------
    try:
        owner, repo = parse_repo_ref(args.repo)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    token = args.token or os.environ.get("GITHUB_TOKEN")

    # ----- 2. fetch repo metadata, README, role ------------------------
    try:
        with GitHubClient(token=token) as client:
            repo_data = client.get_repo(owner, repo)
            default_branch = repo_data.get("default_branch")
            readme = client.get_readme(owner, repo, ref=default_branch)
            role = load_role_from_repo(
                client,
                owner,
                repo,
                branch=default_branch,
                non_interactive=args.non_interactive,
                detected_lang="en",  # initial guess; refined below
            )
    except GitHubError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except MissingRoleError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # ----- 3. derive slug + language + rewrite images + frontmatter ----
    try:
        slug = slugify_repo_name(repo_data["name"])
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    detected_lang = detect_language(readme)
    default_branch = repo_data.get("default_branch") or "main"
    body = rewrite_image_urls_to_absolute(readme, owner, repo, default_branch)

    # Create a single LLMClient for both tag generation and translation.
    # Per user policy, tag generation fails loud if the LLM is unavailable
    # (build_frontmatter raises ValueError when llm_client is None).
    # Translation has its own silent fallback (best-effort) inside
    # _maybe_translate_frontmatter.
    try:
        # Lazy import: keeps the script decoupled from backend.config at
        # import time (Settings reads env at construction; tests may not
        # have env vars set when the script module is imported).
        from backend.config import Settings

        settings = Settings()
        llm = LLMClient(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            model=settings.CHAT_MODEL,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"ERROR: failed to create LLM client (required for tag generation): "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            "  hint: check that LLM_API_KEY (and LLM_BASE_URL if non-default) are set.",
            file=sys.stderr,
        )
        return 1

    new_frontmatter = build_frontmatter(
        repo_data,
        role=role,
        detected_lang=detected_lang,
        llm_client=llm,
        readme_text=readme,
    )
    new_frontmatter = _maybe_translate_frontmatter(
        new_frontmatter,
        detected_lang,
        llm=llm,
    )

    # ----- 4. report ----------------------------------------------------
    _print_repo_summary(repo_data, slug, role)

    if args.dry_run:
        print("\n(dry run — no files written)")
        return 0

    # ----- 5. write the .md ---------------------------------------------
    # Resolve default projects dir relative to the repo root (3 parents up
    # from apps/api/scripts/ingest_repo.py).
    repo_root = Path(__file__).resolve().parents[3]
    projects_dir = args.projects_dir or (
        repo_root / "apps" / "api" / "data" / "projects"
    )
    md_path = projects_dir / f"{slug}.md"

    try:
        if md_path.exists():
            if args.force:
                write_project_md(new_frontmatter, body, projects_dir, force=True)
            elif args.update:
                existing = load_existing_frontmatter(md_path) or {}
                merged = merge_frontmatter_for_update(existing, new_frontmatter)
                write_project_md(merged, body, projects_dir, force=True)
            else:
                raise ProjectExistsError(
                    f"{md_path} already exists. "
                    f"Use --force to overwrite, or --update to preserve "
                    f"human-edited fields (role_*, client, impact_*)."
                )
        else:
            write_project_md(new_frontmatter, body, projects_dir)
    except (ProjectExistsError, FrontmatterValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: filesystem error writing {md_path}: {exc}", file=sys.stderr)
        return 1

    print(f"\nWrote {md_path}")

    # ----- 6. branch + commit + draft PR --------------------------------
    # Branch name strips the "proj-" prefix from the slug to keep the name
    # short and match the convention documented in scripts/README.md and
    # exercised by tests/scripts/test_branch_pr.py (e.g. content/ingest-foo).
    branch_name = f"content/ingest-{slug.removeprefix('proj-')}"
    commit_message = f"chore(content): ingest repo {owner}/{repo}"
    commit_body = f"Auto-generated project .md from {owner}/{repo}."

    try:
        create_branch(branch_name, base="dev", force=args.force)
    except GitError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Stage the .md we just wrote. git_commit requires the caller to stage.
    try:
        subprocess.run(
            ["git", "add", str(md_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: git add failed: {exc.stderr}", file=sys.stderr)
        return 1

    try:
        git_commit(commit_message, body=commit_body)
    except GitError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        git_push(branch_name, force=args.force)
    except GitError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "  hint: make sure 'origin' is configured and you have push access "
            "(SSH key loaded or HTTPS PAT configured).",
            file=sys.stderr,
        )
        return 1

    if is_gh_installed():
        pr_body = (
            f"Generated by ingest_repo CLI.\n\n"
            f"Repo: {repo_data.get('html_url', '')}\n"
            f"Slug: {slug}"
        )
        try:
            pr_url = open_draft_pr(
                title=commit_message,
                body=pr_body,
                base="dev",
            )
            print(f"\nDraft PR opened: {pr_url}")
        except GitHubCLIError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    else:
        print_manual_pr_instructions(branch_name, base="dev")

    return 0


# ---------------------------------------------------------------------------
# Branch + PR operations (T6)
# ---------------------------------------------------------------------------


class GitError(Exception):
    """Raised when a git subprocess fails (non-zero exit or parse error)."""


class GitHubCLIError(Exception):
    """Raised when the gh CLI subprocess fails or is not installed."""


def is_gh_installed() -> bool:
    """Check whether the ``gh`` CLI is available on PATH.

    Runs ``gh --version`` with a short timeout. Returns True only if the
    command exits 0. All failure modes (binary not found, non-zero exit,
    timeout, OS error) return False.
    """
    try:
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
        OSError,
    ):
        return False
    return result.returncode == 0


def create_branch(branch_name: str, *, base: str = "dev", force: bool = False) -> None:
    """Create and check out a new branch off ``base``.

    If ``force=True`` and the branch already exists (locally or remotely),
    the existing branch is deleted first (local with ``git branch -D``,
    remote with ``git push origin --delete``) before recreating. This
    matches the semantics of ``--force`` at the CLI level: completely
    overwrite the branch and its remote.

    Without ``force``, any existing branch (local or remote) raises
    ``GitError`` to prevent accidental destruction.

    Raises:
        GitError: If the branch exists and ``force=False``, or if the
            checkout / delete / push fails.
    """
    # Check local branch.
    verify = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{branch_name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    local_exists = verify.returncode == 0

    # Check remote branch (only matters if force=True).
    remote_exists = False
    if force:
        ls = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", branch_name],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if ls.returncode == 0:
            # ls-remote output: "<sha>\trefs/heads/<branch>" per branch
            remote_exists = any(
                line.endswith(f"\trefs/heads/{branch_name}")
                for line in ls.stdout.splitlines()
            )

    if local_exists or remote_exists:
        if not force:
            raise GitError(f"branch {branch_name!r} already exists")

        # force=True: delete local + remote.
        if local_exists:
            delete_local = subprocess.run(
                ["git", "branch", "-D", branch_name],
                capture_output=True,
                text=True,
                check=False,
            )
            if delete_local.returncode != 0:
                raise GitError(
                    f"git branch -D failed: "
                    f"{delete_local.stderr.strip() or delete_local.stdout.strip()}"
                )

        if remote_exists:
            delete_remote = subprocess.run(
                ["git", "push", "origin", "--delete", branch_name],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if delete_remote.returncode != 0:
                # Don't abort — the remote might be misconfigured, or we may
                # not have push rights. The force-push later will fail loudly
                # if it actually matters (e.g., divergent history).
                print(
                    f"WARNING: failed to delete remote branch {branch_name!r}: "
                    f"{delete_remote.stderr.strip() or delete_remote.stdout.strip()}",
                    file=sys.stderr,
                )

    # Create the branch off ``base``.
    checkout = subprocess.run(
        ["git", "checkout", "-b", branch_name, base],
        capture_output=True,
        text=True,
        check=False,
    )
    if checkout.returncode != 0:
        raise GitError(
            f"git checkout -b failed: {checkout.stderr.strip() or checkout.stdout.strip()}"
        )


def git_commit(message: str, *, body: str = "") -> None:
    """Create a commit with the given subject + optional body.

    The caller must have staged files via ``git add`` before calling.

    Raises:
        GitError: If ``git commit`` exits non-zero.
    """
    args = ["git", "commit", "-m", message]
    if body:
        args.extend(["-m", body])
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise GitError(
            f"git commit failed: {result.stderr.strip() or result.stdout.strip()}"
        )


def git_push(branch_name: str, *, force: bool = False) -> None:
    """Push ``branch_name`` to ``origin`` with upstream tracking.

    Required before ``gh pr create`` — GitHub rejects PRs against branches
    that exist only in the local working tree.

    If ``force=True``, uses ``--force-with-lease`` instead of plain push.
    ``--force-with-lease`` is safer than ``--force``: it refuses to
    overwrite remote changes you haven't seen (which prevents accidentally
    clobbering concurrent work).

    Raises:
        GitError: On non-zero exit, timeout, or failure to spawn the process.
    """
    args = ["git", "push"]
    if force:
        args.append("--force-with-lease")
    args.extend(["-u", "origin", branch_name])

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git push timed out after {exc.timeout}s") from exc
    except OSError as exc:
        raise GitError(f"git push failed to spawn: {exc}") from exc

    if result.returncode != 0:
        raise GitError(
            f"git push failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def open_draft_pr(*, title: str, body: str, base: str = "dev") -> str:
    """Open a draft PR via ``gh pr create --draft``.

    Returns the PR URL printed on stdout.

    Raises:
        GitHubCLIError: If ``gh`` is not installed or exits non-zero.
    """
    if not is_gh_installed():
        raise GitHubCLIError(
            "gh CLI not installed. Install it from https://cli.github.com/ "
            "and authenticate with `gh auth login`."
        )

    result = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--draft",
            "--title",
            title,
            "--body",
            body,
            "--base",
            base,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitHubCLIError(
            f"gh pr create failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


def print_manual_pr_instructions(branch_name: str, *, base: str = "dev") -> None:
    """Print instructions for manually opening the PR."""
    print(f"\nManual PR creation required for branch {branch_name!r}:")
    print(
        f"  gh pr create --draft --title ... --body ... "
        f"--base {base} --head {branch_name}"
    )
    print(
        f"  or visit: https://github.com/<owner>/<repo>/compare/{base}...{branch_name}"
    )


# ---------------------------------------------------------------------------
# Re-ingest modes: --force / --update (T7)
# ---------------------------------------------------------------------------

# Fields preserved from existing frontmatter during --update mode.
# Human-edited values that must NOT be overwritten on re-ingest.
_UPDATE_PRESERVED_FIELDS: frozenset[str] = frozenset(
    {
        "role_es",
        "role_en",
        "client",
        "impact_es",
        "impact_en",
    }
)

# Fields that come from the source repo and are always regenerated.
# Slug is excluded — it's the filename and stays stable for the same repo.
_UPDATE_REGENERATED_FIELDS: frozenset[str] = frozenset(
    {
        "title_es",
        "title_en",
        "summary_es",
        "summary_en",
        "stack_es",
        "stack_en",
        "tags",
        "year",
        "links",
    }
)


def merge_frontmatter_for_update(existing: dict, new: dict) -> dict:
    """Merge existing frontmatter with a freshly-built one for --update mode.

    Preserves human-editable fields (role_*, client, impact_*) from
    ``existing`` (only when non-empty). Uses freshly-built values for
    derived fields (title, summary, stack, tags, year, links) from ``new``.
    Slug stays from ``existing`` (it's the filename; mismatch is a bug).
    Unknown fields from either side are kept (forward-compat).

    Args:
        existing: frontmatter dict from the existing .md file.
        new: frontmatter dict freshly built from the current repo state.

    Returns:
        A new dict with merged values.

    Raises:
        ValueError: If the slug in ``new`` differs from ``existing``.
    """
    new_slug = new.get("slug")
    existing_slug = existing.get("slug")
    if new_slug is not None and existing_slug is not None and new_slug != existing_slug:
        raise ValueError(
            f"slug mismatch: existing has {existing_slug!r}, "
            f"new would produce {new_slug!r}. Use --force to rename."
        )

    result: dict = {}
    # Start with all fields from new (the regenerated baseline).
    result.update(new)

    # Preserve human-edited fields from existing (only if non-empty).
    for field in _UPDATE_PRESERVED_FIELDS:
        if field not in existing:
            continue
        value = existing[field]
        # Treat None/""/[] as "no human input" → fall back to new value.
        if value in (None, "", []):
            continue
        result[field] = value

    # Slug stays from existing (safer default; renamed file is a separate op).
    if existing_slug is not None:
        result["slug"] = existing_slug

    # Preserve unknown fields from existing (might be human-added custom keys).
    for field, value in existing.items():
        if field in result:
            continue
        result[field] = value

    return result


def load_existing_frontmatter(md_path: Path) -> dict | None:
    """Load frontmatter from an existing .md file.

    Returns the parsed frontmatter dict, or None if the file doesn't
    exist, has no frontmatter, or the frontmatter is malformed/not a dict.
    """
    if not md_path.exists():
        return None

    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError:
        return None

    if not text.startswith("---\n"):
        return None

    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return None

    yaml_text = parts[1]
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return None

    if not isinstance(parsed, dict):
        return None

    return parsed


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

TEMP_PREFIX = ".ingest-tmp-"


def write_project_md(
    frontmatter: dict,
    body: str,
    out_dir: Path,
    *,
    force: bool = False,
) -> Path:
    """Render and write the portfolio project .md file atomically.

    The frontmatter is rendered as YAML between ``---`` delimiters, then
    the body follows. The write is atomic: a temp file is written first,
    then renamed onto the final path. If any step fails, the temp file
    is cleaned up and no partial file is left at the target path.

    Args:
        frontmatter: dict matching the schema. Validated first.
        body: markdown body content (e.g. the README).
        out_dir: directory to write into. Created if it does not exist.
        force: if True, overwrite an existing .md at the target path.
            Default False raises ProjectExistsError.

    Returns:
        The Path of the written file.

    Raises:
        FrontmatterValidationError: if frontmatter fails validation.
        ProjectExistsError: if the target .md exists and force is False.
        OSError: on filesystem failure (after temp cleanup).
    """
    # Validate first — fail fast, no partial state.
    validate_frontmatter(frontmatter)

    slug = frontmatter["slug"]
    out_path = out_dir / f"{slug}.md"

    if out_path.exists() and not force:
        raise ProjectExistsError(
            f"{out_path} already exists. Use --force to overwrite."
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    yaml_text = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )

    fd, tmp_name = tempfile.mkstemp(
        dir=str(out_dir),
        prefix=TEMP_PREFIX,
        suffix=".md.tmp",
    )
    tmp_path = Path(tmp_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("---\n")
            f.write(yaml_text)
            if not yaml_text.endswith("\n"):
                f.write("\n")
            f.write("---\n\n")
            f.write(body.rstrip())
            f.write("\n")

        os.replace(tmp_path, out_path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise

    return out_path


if __name__ == "__main__":
    sys.exit(main())
