"""Smoke test E2E del flujo de ingest, simulando octocat/Hello-World.

Verifica que main() ejecuta el pipeline completo:
  parse_repo_ref → get_repo → get_readme → load_role_from_repo →
  detect_language → rewrite_image_urls_to_absolute → build_frontmatter →
  write_project_md → (no-op branch/PR en tests via mocks)

Mocking strategy:
  - Parchea ``GitHubClient.__init__`` para inyectar un ``httpx.MockTransport``
    que sirve fixtures de octocat/Hello-World.
  - Parchea ``LLMClient`` con un fake que devuelve el input como JSON
    (sin traduccion real; la logica de traduccion tiene su propio suite en
    ``tests/scripts/test_translate.py``).
  - Parchea ``subprocess.run`` para no-opear los comandos git/gh.

Estos tests son TDD strict:
  - ``test_full_ingest_dry_run``: pasaria con el stub anterior (regression
    guard del dry-run).
  - ``test_full_ingest_writes_md``: FALLA con el stub (write step no
    implementado); PASA una vez que main() ejecuta el pipeline completo.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import yaml

from scripts import ingest_repo
from scripts.ingest_repo import GitHubClient

# ---------------------------------------------------------------------------
# Fixtures: octocat/Hello-World (snapshot taken from real GitHub).
# ---------------------------------------------------------------------------

# language y topics fueron agregados al fixture porque build_frontmatter
# exige stack_es/stack_en y tags no-vacios, y el Hello-World real no tiene
# language/topics. Es una desviacion documentada del fixture: el script
# clona los datos de GitHub, no del repo real.
OCTOCAT_HELLO_WORLD: dict = {
    "name": "Hello-World",
    "full_name": "octocat/Hello-World",
    "description": "My first repository on GitHub!",
    "language": "Markdown",
    "topics": ["demo", "getting-started"],
    "created_at": "2011-01-26T19:01:12Z",
    "default_branch": "master",
    "html_url": "https://github.com/octocat/Hello-World",
    "private": False,
}

OCTOCAT_README = (
    "# Hello World\n\nThis is my first repo.\n\n![screenshot](./screenshot.png)\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_github_handler():
    """Devuelve un handler httpx que sirve los fixtures de octocat/Hello-World.

    Sirve un .portafolio.yml valido (con role) para evitar el prompt
    interactivo, y 404 para todo lo demas (incluido .portafolio.yaml).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/octocat/Hello-World":
            return httpx.Response(200, json=OCTOCAT_HELLO_WORLD)
        if path == "/repos/octocat/Hello-World/readme":
            return httpx.Response(200, text=OCTOCAT_README)
        if path == "/repos/octocat/Hello-World/contents/.portafolio.yml":
            return httpx.Response(200, text="role: Tech Lead\nclient: ACME\n")
        # .portafolio.yaml -> 404; cualquier otro -> 404
        return httpx.Response(404, json={"message": "Not Found"})

    return handler


class _FakeLLMClient:
    """Fake LLMClient que devuelve los campos de input como JSON (eco).

    El prompt de traduccion del script termina con ``Input:\\n<json>``;
    extraemos ese bloque y lo devolvemos como respuesta. Asi, las
    llamadas de translate_fields resultan en un no-op de campos (el valor
    traducido es identico al original).
    """

    def __init__(self, *args, **kwargs) -> None:
        # Acepta cualquier argumento de constructor (base_url, api_key, model).
        self.init_args = args
        self.init_kwargs = kwargs

    def chat(self, system: str, user: str, **kwargs) -> str:
        m = re.search(r"Input:\s*(\{.*\})\s*$", user, re.DOTALL)
        if m:
            return m.group(1)
        m = re.search(r"\{.*\}", user, re.DOTALL)
        return m.group(0) if m else "{}"


def _patch_github_client(transport: httpx.MockTransport):
    """Parchea ``GitHubClient.__init__`` para inyectar el MockTransport dado."""
    real_init = GitHubClient.__init__

    def patched_init(self, token=None, **kwargs):
        real_init(self, token=token, transport=transport)

    return patch.object(GitHubClient, "__init__", patched_init)


def _make_subprocess_side_effect():
    """Side-effect que retorna segun el comando ejecutado.

    main() invoca subprocess.run 7 veces (orden aproximado):
      1. ``git rev-parse --verify refs/heads/<name>`` -> returncode 1 (branch
         no existe, asi create_branch puede crear la nueva)
      2. ``git checkout -b <name> dev`` -> returncode 0
      3. ``git add <md_path>`` -> returncode 0
      4. ``git commit -m ...`` -> returncode 0
      5. ``git push -u origin <name>`` -> returncode 0 + output realista
      6. ``gh --version`` (is_gh_installed en main()) -> returncode 0
      7. ``gh --version`` (is_gh_installed dentro de open_draft_pr) -> 0
      8. ``gh pr create --draft ...`` -> returncode 0 + URL del PR

    Usamos una funcion (no una lista) porque la cantidad de invocaciones
    de ``is_gh_installed`` depende de donde se llame y puede variar.
    """

    def side_effect(*args, **kwargs):
        cmd = args[0] if args else []
        first = cmd[0] if cmd else ""
        # rev-parse debe fallar para que create_branch continue.
        if first == "git" and len(cmd) > 1 and cmd[1] == "rev-parse":
            return MagicMock(returncode=1, stdout="", stderr="")
        # git push devuelve output realista de Git.
        if first == "git" and len(cmd) > 1 and cmd[1] == "push":
            return MagicMock(
                returncode=0,
                stdout=(
                    "To github.com:owner/repo.git\n"
                    " * [new branch]      content/ingest-foo -> origin/content/ingest-foo\n"
                    "Branch 'content/ingest-foo' set up to track remote branch.\n"
                ),
                stderr="",
            )
        # gh pr create devuelve la URL del PR en stdout.
        if first == "gh" and len(cmd) > 1 and cmd[1] == "pr":
            return MagicMock(
                returncode=0,
                stdout="https://github.com/owner/repo/pull/42\n",
                stderr="",
            )
        # Cualquier otra llamada (git checkout, git add, git commit,
        # gh --version) retorna exito.
        return MagicMock(returncode=0, stdout="", stderr="")

    return side_effect


# ---------------------------------------------------------------------------
# Test: dry-run pipeline (no escribe, no branch)
# ---------------------------------------------------------------------------


class TestFullIngestDryRun:
    """main() --dry-run imprime el summary pero NO escribe .md ni branch."""

    def test_full_ingest_dry_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        transport = httpx.MockTransport(_make_github_handler())

        with (
            _patch_github_client(transport),
            patch.object(ingest_repo, "LLMClient", _FakeLLMClient),
            patch.object(ingest_repo.subprocess, "run") as mock_run,
        ):
            rc = ingest_repo.main(
                [
                    "--repo",
                    "octocat/Hello-World",
                    "--dry-run",
                    "--projects-dir",
                    str(projects_dir),
                ]
            )

        assert rc == 0
        captured = capsys.readouterr()
        # El summary incluye el slug derivado y el role cargado.
        assert "proj-hello-world" in captured.out
        assert "Tech Lead" in captured.out
        # Marcador de dry-run
        assert "dry run" in captured.out.lower()
        # No se escribio ningun .md
        assert list(projects_dir.glob("*.md")) == []
        # subprocess.run no se llama (dry-run corta antes de branch/PR)
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Test: ingest completo escribe el .md (con subprocess + LLM mocked)
# ---------------------------------------------------------------------------


class TestFullIngestWritesMd:
    """main() --repo octocat/Hello-World --projects-dir <tmp> escribe el .md."""

    def test_full_ingest_writes_md(self, tmp_path: Path) -> None:
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        transport = httpx.MockTransport(_make_github_handler())
        mock_results = _make_subprocess_side_effect()

        with (
            _patch_github_client(transport),
            patch.object(ingest_repo, "LLMClient", _FakeLLMClient),
            patch.object(
                ingest_repo.subprocess,
                "run",
                side_effect=mock_results,
            ) as mock_run,
        ):
            rc = ingest_repo.main(
                [
                    "--repo",
                    "octocat/Hello-World",
                    "--projects-dir",
                    str(projects_dir),
                ]
            )

        assert rc == 0
        # subprocess.run fue llamado al menos una vez (branch + PR).
        assert mock_run.call_count >= 1

        # git add <md_path> se invoca ANTES de git commit. Regression guard
        # del bug que abortaba con "nothing added to commit but untracked files
        # present" cuando main() llamaba git_commit sin stagear primero.
        call_cmds = [c.args[0] for c in mock_run.call_args_list]
        git_add_calls = [
            i for i, cmd in enumerate(call_cmds) if cmd[:2] == ["git", "add"]
        ]
        git_commit_calls = [
            i for i, cmd in enumerate(call_cmds) if cmd[:2] == ["git", "commit"]
        ]
        assert git_add_calls, f"expected git add to be called; got {call_cmds}"
        assert git_commit_calls, f"expected git commit to be called; got {call_cmds}"
        assert git_add_calls[0] < git_commit_calls[0], (
            f"git add must be called BEFORE git commit; "
            f"got git add at {git_add_calls[0]}, git commit at {git_commit_calls[0]}"
        )
        # Y el archivo stageado es el .md que escribimos.
        git_add_cmd = call_cmds[git_add_calls[0]]
        assert git_add_cmd[2].endswith("proj-hello-world.md"), (
            f"git add debe stagear proj-hello-world.md; got {git_add_cmd[2]}"
        )

        # git push -u origin <branch> se invoca DESPUÉS de git commit y
        # ANTES de gh pr create. Regression guard del bug que abortaba con
        # "you must first push the current branch to a remote".
        git_push_calls = [
            i for i, cmd in enumerate(call_cmds) if cmd[:2] == ["git", "push"]
        ]
        gh_pr_calls = [i for i, cmd in enumerate(call_cmds) if cmd[:2] == ["gh", "pr"]]
        assert git_push_calls, f"expected git push to be called; got {call_cmds}"
        assert gh_pr_calls, f"expected gh pr create to be called; got {call_cmds}"
        assert git_commit_calls[0] < git_push_calls[0], (
            f"git push must be called AFTER git commit; "
            f"got commit at {git_commit_calls[0]}, push at {git_push_calls[0]}"
        )
        assert git_push_calls[0] < gh_pr_calls[0], (
            f"git push must be called BEFORE gh pr create; "
            f"got push at {git_push_calls[0]}, gh pr at {gh_pr_calls[0]}"
        )
        # Y el comando exacto: push -u origin <branch>.
        git_push_cmd = call_cmds[git_push_calls[0]]
        assert git_push_cmd[:3] == ["git", "push", "-u"], (
            f"git push debe usar -u flag; got {git_push_cmd[:3]}"
        )
        assert git_push_cmd[3] == "origin", (
            f"git push debe apuntar a origin; got {git_push_cmd[3]}"
        )
        assert git_push_cmd[4].startswith("content/ingest-"), (
            f"git push debe pushear la branch content/ingest-<slug>; "
            f"got {git_push_cmd[4]}"
        )

        # El .md existe.
        md_path = projects_dir / "proj-hello-world.md"
        assert md_path.exists()

        # Parsea el .md.
        text = md_path.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        parts = text.split("---\n", 2)
        assert len(parts) >= 3
        fm = yaml.safe_load(parts[1])
        body = parts[2]

        # Frontmatter
        assert fm["slug"] == "proj-hello-world"
        assert fm["year"] == 2011  # 2011-01-26
        assert fm["title_en"] == "Hello World"
        assert fm["role_en"] == "Tech Lead"
        assert fm["role_es"] == "Tech Lead"
        assert fm["links"]["repo"] == "https://github.com/octocat/Hello-World"

        # Body contiene el README con la imagen reescrita a URL absoluta.
        assert "Hello World" in body
        assert "This is my first repo." in body
        assert (
            "https://raw.githubusercontent.com/octocat/Hello-World/master/screenshot.png"
            in body
        )
        # La ruta relativa original ya no esta presente.
        assert "./screenshot.png" not in body


# ---------------------------------------------------------------------------
# Test: ingest cuando el .md ya existe aborta con error claro
# ---------------------------------------------------------------------------


class TestFullIngestExistingProjectGuards:
    """Si el .md ya existe sin --force ni --update, main() aborta con exit 1."""

    def test_existing_project_without_force_or_update_aborts(
        self, tmp_path: Path
    ) -> None:
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        # Pre-crear el .md destino.
        (projects_dir / "proj-hello-world.md").write_text(
            "existing content\n", encoding="utf-8"
        )
        transport = httpx.MockTransport(_make_github_handler())

        with (
            _patch_github_client(transport),
            patch.object(ingest_repo, "LLMClient", _FakeLLMClient),
            patch.object(ingest_repo.subprocess, "run") as mock_run,
        ):
            rc = ingest_repo.main(
                [
                    "--repo",
                    "octocat/Hello-World",
                    "--projects-dir",
                    str(projects_dir),
                ]
            )

        assert rc == 1
        # El .md pre-existente no se modifica.
        content = (projects_dir / "proj-hello-world.md").read_text(encoding="utf-8")
        assert content == "existing content\n"
        # subprocess.run no se llama (no se llega a branch/PR).
        mock_run.assert_not_called()
