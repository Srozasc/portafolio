"""CLI to ingest a single GitHub repo into the portfolio projects directory.

Usage:
    python apps/api/scripts/ingest_repo.py --repo owner/repo [--token GITHUB_TOKEN] \\
        [--projects-dir PATH] [--dry-run]

Tarea 1 scope: scaffold + parse_repo_ref + slugify_repo_name + GitHubClient
(get_repo, get_readme). Mapping to frontmatter, writing the .md, LLM
translation, branch/PR, .portafolio.yml, --force/--update are implemented
in subsequent tasks (see odd/tasks/ingest-repo-from-github.md).

Exit codes:
    0 - success (including dry-run)
    1 - fatal error (invalid input, GitHub API error, network failure)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

import httpx


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


# ---------------------------------------------------------------------------
# Pure helpers (no I/O)
# ---------------------------------------------------------------------------

def parse_repo_ref(ref: str) -> Tuple[str, str]:
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
        token: Optional[str] = None,
        transport: Optional[httpx.BaseTransport] = None,
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

    def __enter__(self) -> "GitHubClient":
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
        self, owner: str, repo: str, ref: Optional[str] = None
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


def main(argv: Optional[list[str]] = None) -> int:
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


if __name__ == "__main__":
    sys.exit(main())
