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

Pending tasks (see odd/tasks/ingest-repo-from-github.md): language detection,
image-URL rewriting, LLM translation, role/client prompt, branch + draft PR,
--force / --update, docs + E2E smoke test.

Exit codes:
    0 - success (including dry-run)
    1 - fatal error (invalid input, GitHub API error, network failure)
"""

import argparse
import contextlib
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Self

import httpx
import yaml

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
    m = re.match(
        r"^https?://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?(?:/.*)?$", s
    )
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
            raise ValueError(
                f"repo name {name!r} yields empty slug after truncation"
            )

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
            raise FrontmatterValidationError(
                f"{key} must be string: got {v!r}"
            )

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
    "_(traduccion pendiente — ver summary del idioma detectado)_"
)  # Zod-safe length


def humanize_repo_name(name: str) -> str:
    """Turn 'my-cool-repo' into 'My Cool Repo' for a human-readable title."""
    return re.sub(r"[-_]+", " ", name).strip().title()


def build_frontmatter(
    repo_data: dict,
    role: str,
    detected_lang: str,
) -> dict:
    """Build a portfolio frontmatter dict from GitHub repo metadata.

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
        ValueError: if detected_lang is not 'es' or 'en', or if role is empty.
    """
    if detected_lang not in ("es", "en"):
        raise ValueError(
            f"detected_lang must be 'es' or 'en': got {detected_lang!r}"
        )
    if not role or not role.strip():
        raise ValueError("role must be a non-empty string")

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

    tags = [t for t in topics if isinstance(t, str) and t]

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
            raise GitHubError(
                f"GitHub API error {r.status_code}: {r.text[:200]}"
            )

        return r.json()

    def get_readme(
        self, owner: str, repo: str, ref: str | None = None
    ) -> str:
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_repo_summary(repo_data: dict, slug: str) -> None:
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
    args = parser.parse_args(argv)

    # ----- 1. parse input ------------------------------------------------
    try:
        owner, repo = parse_repo_ref(args.repo)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    token = args.token or os.environ.get("GITHUB_TOKEN")

    # ----- 2. fetch repo metadata ---------------------------------------
    try:
        with GitHubClient(token=token) as client:
            repo_data = client.get_repo(owner, repo)
    except GitHubError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # ----- 3. derive slug ------------------------------------------------
    try:
        slug = slugify_repo_name(repo_data["name"])
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # ----- 4. report ----------------------------------------------------
    _print_repo_summary(repo_data, slug)

    if args.dry_run:
        print("\n(dry run — no files written)")
        return 0

    # ----- 5. write step (T2 onwards) -----------------------------------
    print(
        "\n(write step not yet implemented — see odd/tasks/ingest-repo-from-github.md)"
    )
    return 0


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
