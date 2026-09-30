from __future__ import annotations

"""Tests for parse_portafolio_yml, prompt_for_role, get_file_content,
load_role_from_repo (Tarea 5).

Strategy:
- parse_portafolio_yml: pure function, no I/O.
- prompt_for_role: monkeypatch ``builtins.input`` to capture user reply.
- GitHubClient.get_file_content: same httpx.MockTransport pattern as T1.
- load_role_from_repo: combined function; uses both GitHubClient (mocked
  transport) and prompt_for_role (monkeypatched input).

Failure semantics (per T5.1 / T5.4):
- Malformed YAML → empty dict + warning, no abort.
- .portafolio.yml missing on repo → prompt the user.
- --non-interactive and YAML missing → MissingRoleError raised.
"""

import httpx
import pytest
from scripts.ingest_repo import (
    GitHubClient,
    GitHubError,
    MissingRoleError,
    load_role_from_repo,
    parse_portafolio_yml,
    prompt_for_role,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_transport(handler):
    return httpx.MockTransport(handler)


# ===========================================================================
# parse_portafolio_yml
# ===========================================================================

class TestParsePortafolioYml:
    """Pure parser. Tolerates malformed input; never raises."""

    def test_empty_string_returns_empty_dict(self):
        assert parse_portafolio_yml("") == {}

    def test_whitespace_only_returns_empty_dict(self):
        assert parse_portafolio_yml("   \n\t\n") == {}

    def test_yaml_with_only_separator_returns_empty_dict(self):
        assert parse_portafolio_yml("---\n") == {}

    def test_minimal_yaml_with_role(self):
        assert parse_portafolio_yml("role: Tech Lead\n") == {"role": "Tech Lead"}

    def test_role_with_double_quotes(self):
        assert parse_portafolio_yml('role: "Senior Engineer"\n') == {
            "role": "Senior Engineer"
        }

    def test_role_with_single_quotes(self):
        assert parse_portafolio_yml("role: 'CTO'\n") == {"role": "CTO"}

    def test_yaml_with_client(self):
        assert parse_portafolio_yml("role: Tech Lead\nclient: Acme Corp\n") == {
            "role": "Tech Lead",
            "client": "Acme Corp",
        }

    def test_yaml_with_impact_as_list(self):
        text = (
            "role: Tech Lead\n"
            "impact:\n"
            "  - Reduced deploy time by 50%\n"
            "  - Saved $1M annually\n"
        )
        result = parse_portafolio_yml(text)
        assert result["role"] == "Tech Lead"
        assert result["impact"] == [
            "Reduced deploy time by 50%",
            "Saved $1M annually",
        ]

    def test_yaml_with_all_supported_fields(self):
        text = (
            "role: Senior Engineer\n"
            "client: Globex\n"
            "summary_extra: Custom multi-line summary.\n"
            "impact:\n"
            "  - One\n"
            "  - Two\n"
        )
        result = parse_portafolio_yml(text)
        assert result == {
            "role": "Senior Engineer",
            "client": "Globex",
            "summary_extra": "Custom multi-line summary.",
            "impact": ["One", "Two"],
        }

    def test_missing_optional_fields_omitted(self):
        result = parse_portafolio_yml("role: Engineer\n")
        assert result == {"role": "Engineer"}
        assert "client" not in result
        assert "impact" not in result

    def test_extra_fields_ignored(self):
        result = parse_portafolio_yml(
            "role: Engineer\nfoo: bar\nanother_field: value\n"
        )
        assert result == {"role": "Engineer"}

    def test_invalid_yaml_returns_empty_dict(self):
        # Mismatched/duplicated keys combined with bad indentation is unparseable.
        result = parse_portafolio_yml(
            "role: Tech Lead\n  bad-indent: x\nrole: Duplicate\n"
        )
        assert result == {}

    def test_non_dict_yaml_string_returns_empty_dict(self):
        assert parse_portafolio_yml("just a string\n") == {}

    def test_non_dict_yaml_list_returns_empty_dict(self):
        assert parse_portafolio_yml("- item1\n- item2\n") == {}

    def test_role_explicit_null_omitted_or_none(self):
        # role: ~ / role: null / role: '' → caller treats as missing
        result = parse_portafolio_yml("role: ~\nclient: Acme\n")
        assert "role" not in result or result.get("role") is None
        assert result["client"] == "Acme"

    def test_role_non_string_skipped(self):
        # role: [list] is the wrong type → key omitted from result.
        result = parse_portafolio_yml("role:\n  - one\n  - two\n")
        assert result.get("role") is None

    def test_impact_non_list_skipped(self):
        result = parse_portafolio_yml("role: X\nimpact: not a list\n")
        assert "impact" not in result

    def test_impact_filters_non_string_items(self):
        result = parse_portafolio_yml(
            "impact:\n  - good\n  - 42\n  - also good\n"
        )
        assert result["impact"] == ["good", "also good"]


# ===========================================================================
# prompt_for_role
# ===========================================================================

class TestPromptForRole:
    def test_returns_user_input_en(self, monkeypatch):
        monkeypatch.setattr(
            "builtins.input", lambda *a, **kw: "Senior Engineer"
        )
        assert prompt_for_role("en") == "Senior Engineer"

    def test_returns_user_input_es(self, monkeypatch):
        monkeypatch.setattr(
            "builtins.input", lambda *a, **kw: "Ingeniero Senior"
        )
        assert prompt_for_role("es") == "Ingeniero Senior"

    def test_blank_returns_default_en(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda *a, **kw: "")
        assert prompt_for_role("en") == "Tech Lead"

    def test_blank_returns_default_es(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda *a, **kw: "")
        assert prompt_for_role("es") == "Ingeniero"

    def test_strips_surrounding_whitespace(self, monkeypatch):
        monkeypatch.setattr(
            "builtins.input", lambda *a, **kw: "  Tech Lead  "
        )
        assert prompt_for_role("en") == "Tech Lead"

    def test_prompt_text_en_mentions_role(self, monkeypatch):
        captured: list[str] = []
        def fake_input(prompt=""):
            captured.append(prompt)
            return "Tech Lead"
        monkeypatch.setattr("builtins.input", fake_input)
        prompt_for_role("en")
        assert "role" in captured[0].lower()

    def test_prompt_text_es_mentions_rol(self, monkeypatch):
        captured: list[str] = []
        def fake_input(prompt=""):
            captured.append(prompt)
            return "Ingeniero"
        monkeypatch.setattr("builtins.input", fake_input)
        prompt_for_role("es")
        assert "rol" in captured[0].lower() or "ingener" in captured[0].lower()

    def test_invalid_lang_raises(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda *a, **kw: "")
        with pytest.raises(ValueError, match="only es/en"):
            prompt_for_role("fr")


# ===========================================================================
# GitHubClient.get_file_content
# ===========================================================================

class TestGitHubClientGetFileContent:
    def test_returns_file_content_on_200(self):
        content = "role: Tech Lead\nclient: Acme\n"
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/repos/owner/repo/contents/.portafolio.yml"
            assert request.headers.get("accept") == "application/vnd.github.raw"
            return httpx.Response(200, text=content)
        client = GitHubClient(transport=make_transport(handler))
        try:
            text = client.get_file_content(
                "owner", "repo", ".portafolio.yml"
            )
        finally:
            client.close()
        assert text == content

    def test_404_returns_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "Not Found"})
        client = GitHubClient(transport=make_transport(handler))
        try:
            text = client.get_file_content(
                "owner", "repo", "missing.yml"
            )
        finally:
            client.close()
        assert text is None

    def test_ref_passed_as_query_param(self):
        captured: list[dict] = []
        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(dict(request.url.params))
            return httpx.Response(200, text="role: X\n")
        client = GitHubClient(transport=make_transport(handler))
        try:
            client.get_file_content(
                "owner", "repo", "x.yml", ref="develop"
            )
        finally:
            client.close()
        assert captured[0].get("ref") == "develop"

    def test_no_ref_omits_query_param(self):
        captured: list[dict] = []
        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(dict(request.url.params))
            return httpx.Response(200, text="role: X\n")
        client = GitHubClient(transport=make_transport(handler))
        try:
            client.get_file_content("owner", "repo", "x.yml")
        finally:
            client.close()
        assert "ref" not in captured[0]

    def test_403_raises_github_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"message": "rate limit"})
        client = GitHubClient(transport=make_transport(handler))
        try:
            with pytest.raises(GitHubError, match="403"):
                client.get_file_content("owner", "repo", "x.yml")
        finally:
            client.close()


# ===========================================================================
# load_role_from_repo (T5.3 + T5.4)
# ===========================================================================

class TestLoadRoleFromRepo:
    def test_returns_role_from_yml_file(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith(".portafolio.yml")
            return httpx.Response(200, text="role: Tech Lead\n")
        client = GitHubClient(transport=make_transport(handler))
        try:
            role = load_role_from_repo(client, "owner", "repo")
        finally:
            client.close()
        assert role == "Tech Lead"

    def test_returns_role_from_yaml_extension_when_yml_missing(self):
        call_count = [0]
        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            if call_count[0] == 1:
                # First try .yml → 404
                assert request.url.path.endswith(".portafolio.yml")
                return httpx.Response(404, json={"message": "Not Found"})
            # Second try .yaml → 200
            assert request.url.path.endswith(".portafolio.yaml")
            return httpx.Response(200, text="role: FromYaml\n")
        client = GitHubClient(transport=make_transport(handler))
        try:
            role = load_role_from_repo(client, "owner", "repo")
        finally:
            client.close()
        assert role == "FromYaml"
        assert call_count[0] == 2

    def test_prompts_when_no_yaml_file_found(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "Not Found"})
        client = GitHubClient(transport=make_transport(handler))
        monkeypatch.setattr(
            "builtins.input", lambda *a, **kw: "Prompted Role"
        )
        try:
            role = load_role_from_repo(client, "owner", "repo")
        finally:
            client.close()
        assert role == "Prompted Role"

    def test_non_interactive_without_yaml_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "Not Found"})
        client = GitHubClient(transport=make_transport(handler))
        try:
            with pytest.raises(MissingRoleError, match="non-interactive"):
                load_role_from_repo(
                    client, "owner", "repo", non_interactive=True
                )
        finally:
            client.close()

    def test_non_interactive_with_yaml_succeeds(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="role: From File\n")
        client = GitHubClient(transport=make_transport(handler))
        try:
            role = load_role_from_repo(
                client, "owner", "repo", non_interactive=True
            )
        finally:
            client.close()
        assert role == "From File"

    def test_ignores_non_role_fields_in_yaml(self):
        # If only client/impact are in YAML, prompt the user.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, text="client: Acme\nimpact:\n  - X\n"
            )
        client = GitHubClient(transport=make_transport(handler))
        monkeypatch_calls = []
        def fake_input(prompt=""):
            monkeypatch_calls.append(prompt)
            return "Fallback Role"
        import builtins
        builtins.input = fake_input
        try:
            role = load_role_from_repo(client, "owner", "repo")
        finally:
            client.close()
        assert role == "Fallback Role"
        assert len(monkeypatch_calls) == 1  # prompted exactly once

    def test_invalid_yaml_falls_back_to_prompt(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, text="role: Tech Lead\n  bad-indent: x\n"
            )
        client = GitHubClient(transport=make_transport(handler))
        monkeypatch.setattr("builtins.input", lambda *a, **kw: "From Prompt")
        try:
            role = load_role_from_repo(client, "owner", "repo")
        finally:
            client.close()
        assert role == "From Prompt"
