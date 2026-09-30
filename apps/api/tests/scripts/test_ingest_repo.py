"""Tests for apps/api/scripts/ingest_repo.py (Tarea 1).

Covers:
- parse_repo_ref: shorthand, https URL, ssh URL, malformed inputs.
- slugify_repo_name: case, separators, truncation, empty inputs.
- GitHubClient: get_repo, get_readme, header injection, error mapping.
  Uses httpx.MockTransport for hermetic tests (no network).
"""

from __future__ import annotations

import pytest
import httpx

from scripts.ingest_repo import (
    GitHubClient,
    GitHubError,
    parse_repo_ref,
    slugify_repo_name,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_transport(handler):
    """Build an httpx MockTransport from a sync handler function."""
    return httpx.MockTransport(handler)


# ===========================================================================
# parse_repo_ref
# ===========================================================================

class TestParseRepoRef:
    """Accept 'owner/repo', https URL, http URL, ssh form. Reject malformed."""

    def test_shorthand(self):
        assert parse_repo_ref("owner/repo") == ("owner", "repo")

    def test_https_url(self):
        assert parse_repo_ref("https://github.com/owner/repo") == ("owner", "repo")

    def test_https_url_with_git_suffix(self):
        assert parse_repo_ref("https://github.com/owner/repo.git") == ("owner", "repo")

    def test_https_url_with_trailing_path(self):
        assert parse_repo_ref("https://github.com/owner/repo/tree/main") == ("owner", "repo")

    def test_http_url(self):
        assert parse_repo_ref("http://github.com/owner/repo") == ("owner", "repo")

    def test_ssh_form(self):
        assert parse_repo_ref("git@github.com:owner/repo.git") == ("owner", "repo")

    def test_strips_surrounding_whitespace(self):
        assert parse_repo_ref("  owner/repo  ") == ("owner", "repo")

    def test_accepts_digits_in_owner_and_repo(self):
        assert parse_repo_ref("user123/repo-456") == ("user123", "repo-456")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_repo_ref("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_repo_ref("   ")

    def test_no_slash_raises(self):
        with pytest.raises(ValueError, match="invalid"):
            parse_repo_ref("just-a-name")

    def test_only_owner_raises(self):
        with pytest.raises(ValueError, match="invalid"):
            parse_repo_ref("owner/")

    def test_only_repo_raises(self):
        with pytest.raises(ValueError, match="invalid"):
            parse_repo_ref("/repo")

    def test_extra_path_components_shorthand_raises(self):
        with pytest.raises(ValueError, match="invalid"):
            parse_repo_ref("owner/repo/extra")


# ===========================================================================
# slugify_repo_name
# ===========================================================================

class TestSlugifyRepoName:
    """Derive portfolio slug 'proj-<kebab>' from a repo name."""

    def test_simple(self):
        assert slugify_repo_name("my-repo") == "proj-my-repo"

    def test_mixed_case_lowercased(self):
        assert slugify_repo_name("My-Repo") == "proj-my-repo"

    def test_uppercase_lowercased(self):
        assert slugify_repo_name("UPPER") == "proj-upper"

    def test_spaces_become_hyphens(self):
        assert slugify_repo_name("my repo") == "proj-my-repo"

    def test_dots_become_hyphens(self):
        assert slugify_repo_name("repo.with.dots") == "proj-repo-with-dots"

    def test_underscore_becomes_hyphen(self):
        assert slugify_repo_name("my_repo") == "proj-my-repo"

    def test_collapses_multiple_hyphens(self):
        assert slugify_repo_name("a - b") == "proj-a-b"

    def test_strips_leading_and_trailing_hyphens(self):
        assert slugify_repo_name("--hello--") == "proj-hello"

    def test_keeps_digits(self):
        assert slugify_repo_name("repo123") == "proj-repo123"

    def test_truncates_long_name_to_max_total_60(self):
        long = "a" * 100
        slug = slugify_repo_name(long)
        assert slug.startswith("proj-")
        assert len(slug) <= 60

    def test_truncation_strips_trailing_hyphen(self):
        # Build a name whose slug form lands on a hyphen at the truncation point.
        # After normalization "a"*54 + "-" + "b" → "a"*54 + "-" + "b" (56 chars).
        # Truncate to 55 → "a"*54 + "-" → strip trailing hyphen → "a"*54.
        name = "a" * 54 + "-" + "b"
        slug = slugify_repo_name(name)
        assert slug == "proj-" + "a" * 54
        assert not slug.endswith("--")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty"):
            slugify_repo_name("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty"):
            slugify_repo_name("   ")

    def test_only_special_chars_raises(self):
        with pytest.raises(ValueError, match="empty"):
            slugify_repo_name("!@#$%^&*()")


# ===========================================================================
# GitHubClient.get_repo
# ===========================================================================

class TestGitHubClientGetRepo:
    """Fetch repo metadata. Maps HTTP errors to GitHubError."""

    def test_returns_parsed_json(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/repos/owner/repo"
            return httpx.Response(
                200,
                json={
                    "name": "repo",
                    "full_name": "owner/repo",
                    "description": "Test repo",
                    "language": "Python",
                    "topics": ["cli", "demo"],
                    "created_at": "2024-01-15T10:00:00Z",
                    "default_branch": "main",
                    "html_url": "https://github.com/owner/repo",
                },
            )

        client = GitHubClient(transport=make_transport(handler))
        try:
            data = client.get_repo("owner", "repo")
        finally:
            client.close()

        assert data["name"] == "repo"
        assert data["full_name"] == "owner/repo"
        assert data["language"] == "Python"
        assert data["topics"] == ["cli", "demo"]
        assert data["default_branch"] == "main"

    def test_404_raises_with_helpful_message(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "Not Found"})

        client = GitHubClient(transport=make_transport(handler))
        try:
            with pytest.raises(GitHubError, match="not found"):
                client.get_repo("owner", "missing")
        finally:
            client.close()

    def test_401_raises_with_token_hint(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "Bad credentials"})

        client = GitHubClient(transport=make_transport(handler))
        try:
            with pytest.raises(GitHubError, match="401"):
                client.get_repo("owner", "repo")
        finally:
            client.close()

    def test_403_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"message": "API rate limit exceeded"})

        client = GitHubClient(transport=make_transport(handler))
        try:
            with pytest.raises(GitHubError, match="403"):
                client.get_repo("owner", "repo")
        finally:
            client.close()


# ===========================================================================
# GitHubClient.get_readme
# ===========================================================================

class TestGitHubClientGetReadme:
    """Fetch raw README markdown."""

    def test_returns_markdown_text(self):
        readme = "# Hello\n\nThis is a test README.\n"

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/repos/owner/repo/readme"
            assert request.headers.get("accept") == "application/vnd.github.raw"
            return httpx.Response(200, text=readme)

        client = GitHubClient(transport=make_transport(handler))
        try:
            text = client.get_readme("owner", "repo")
        finally:
            client.close()

        assert text == readme

    def test_404_raises_when_no_readme(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "Not Found"})

        client = GitHubClient(transport=make_transport(handler))
        try:
            with pytest.raises(GitHubError, match="no README"):
                client.get_readme("owner", "no-readme-repo")
        finally:
            client.close()


# ===========================================================================
# GitHubClient headers (auth)
# ===========================================================================

class TestGitHubClientAuthHeaders:
    """Token presence must affect the Authorization header sent to GitHub."""

    def test_token_sets_authorization_header(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.headers))
            return httpx.Response(200, json={"name": "repo"})

        client = GitHubClient(token="ghp_abc", transport=make_transport(handler))
        try:
            client.get_repo("owner", "repo")
        finally:
            client.close()

        assert captured["authorization"] == "Bearer ghp_abc"

    def test_no_token_omits_authorization_header(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.headers))
            return httpx.Response(200, json={"name": "repo"})

        client = GitHubClient(transport=make_transport(handler))
        try:
            client.get_repo("owner", "repo")
        finally:
            client.close()

        assert "authorization" not in {k.lower() for k in captured}
