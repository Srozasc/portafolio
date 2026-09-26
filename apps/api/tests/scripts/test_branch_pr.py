from __future__ import annotations

"""Tests for branch + PR operations (Tarea 6).

All subprocess calls are mocked via unittest.mock.patch on
``scripts.ingest_repo.subprocess.run`` (and ``subprocess.TimeoutExpired``
where needed). Tests never invoke real git or gh.

Coverage:
- is_gh_installed: found in PATH, not found, timeout.
- create_branch: success path, branch already exists, checkout failure,
  exact git args.
- git_commit: success without body, success with body, failure.
- open_draft_pr: success returns URL, gh not installed raises, gh non-zero
  exit raises, exact gh args.
- print_manual_pr_instructions: prints expected instructions.

Integration into ``main()`` is deferred to T7/T8 — these functions are
tested in isolation here.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from scripts.ingest_repo import (
    GitError,
    GitHubCLIError,
    create_branch,
    git_commit,
    git_push,
    is_gh_installed,
    open_draft_pr,
    print_manual_pr_instructions,
)

# ===========================================================================
# is_gh_installed
# ===========================================================================


class TestIsGhInstalled:
    @patch("scripts.ingest_repo.subprocess.run")
    def test_returns_true_when_gh_version_succeeds(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert is_gh_installed() is True

    @patch("scripts.ingest_repo.subprocess.run")
    def test_returns_false_when_gh_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("gh not found")
        assert is_gh_installed() is False

    @patch("scripts.ingest_repo.subprocess.run")
    def test_returns_false_when_gh_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert is_gh_installed() is False

    @patch("scripts.ingest_repo.subprocess.run")
    def test_returns_false_on_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=5)
        assert is_gh_installed() is False

    @patch("scripts.ingest_repo.subprocess.run")
    def test_returns_false_on_called_process_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd="gh --version"
        )
        assert is_gh_installed() is False


# ===========================================================================
# create_branch
# ===========================================================================


class TestCreateBranch:
    @patch("scripts.ingest_repo.subprocess.run")
    def test_creates_new_branch_successfully(self, mock_run):
        # First call (rev-parse --verify) fails because branch doesn't exist.
        # Second call (checkout -b) succeeds.
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="", stdout=""),
            MagicMock(returncode=0, stderr="", stdout=""),
        ]
        create_branch("feature/test")
        assert mock_run.call_count == 2

    @patch("scripts.ingest_repo.subprocess.run")
    def test_raises_when_branch_already_exists(self, mock_run):
        # rev-parse succeeds (branch exists), no second call.
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        with pytest.raises(GitError, match="already exists"):
            create_branch("feature/test")
        assert mock_run.call_count == 1

    @patch("scripts.ingest_repo.subprocess.run")
    def test_raises_when_checkout_fails(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="", stdout=""),
            MagicMock(returncode=128, stderr="fatal: cannot create branch", stdout=""),
        ]
        with pytest.raises(GitError, match="checkout -b failed"):
            create_branch("feature/test")

    @patch("scripts.ingest_repo.subprocess.run")
    def test_calls_rev_parse_first(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="", stdout=""),
            MagicMock(returncode=0, stderr="", stdout=""),
        ]
        create_branch("content/ingest-foo")
        first_call_args = mock_run.call_args_list[0].args[0]
        assert first_call_args[0] == "git"
        assert "rev-parse" in first_call_args
        assert "feature/test" in first_call_args[2] or "content/ingest-foo" in str(
            first_call_args
        )

    @patch("scripts.ingest_repo.subprocess.run")
    def test_calls_checkout_with_correct_args(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="", stdout=""),
            MagicMock(returncode=0, stderr="", stdout=""),
        ]
        create_branch("content/ingest-foo", base="main")
        second_call_args = mock_run.call_args_list[1].args[0]
        assert second_call_args[0] == "git"
        assert second_call_args[1] == "checkout"
        assert second_call_args[2] == "-b"
        assert second_call_args[3] == "content/ingest-foo"
        assert second_call_args[4] == "main"

    @patch("scripts.ingest_repo.subprocess.run")
    def test_default_base_is_dev(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="", stdout=""),
            MagicMock(returncode=0, stderr="", stdout=""),
        ]
        create_branch("content/ingest-foo")
        checkout_args = mock_run.call_args_list[1].args[0]
        assert checkout_args[-1] == "dev"

    @patch("scripts.ingest_repo.subprocess.run")
    def test_no_force_skips_ls_remote(self, mock_run):
        """force=False does NOT call ls-remote (saves time on the common path)."""
        # rev-parse succeeds (branch exists locally), expect GitError
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with pytest.raises(GitError, match="already exists"):
            create_branch("foo", force=False)
        # Only one subprocess call (the rev-parse check)
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert len(cmds) == 1
        assert cmds[0][:2] == ["git", "rev-parse"]

    @patch("scripts.ingest_repo.subprocess.run")
    def test_force_deletes_existing_local_branch(self, mock_run):
        """force=True with existing local branch: delete + create."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # rev-parse: exists
            MagicMock(returncode=0, stdout="", stderr=""),  # ls-remote: no remote
            MagicMock(returncode=0, stdout="", stderr=""),  # git branch -D
            MagicMock(returncode=0, stdout="", stderr=""),  # git checkout -b
        ]
        create_branch("content/ingest-foo", force=True)
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert len(cmds) == 4
        assert cmds[0][:2] == ["git", "rev-parse"]
        assert cmds[1][:2] == ["git", "ls-remote"]
        assert cmds[2] == ["git", "branch", "-D", "content/ingest-foo"]
        assert cmds[3] == ["git", "checkout", "-b", "content/ingest-foo", "dev"]

    @patch("scripts.ingest_repo.subprocess.run")
    def test_force_deletes_existing_remote_branch(self, mock_run):
        """force=True with existing remote branch: push --delete then create."""
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr=""),  # rev-parse: no local
            MagicMock(
                returncode=0,
                stdout="abc123\trefs/heads/foo\n",
                stderr="",
            ),  # ls-remote: exists
            MagicMock(returncode=0, stdout="", stderr=""),  # git push origin --delete
            MagicMock(returncode=0, stdout="", stderr=""),  # git checkout -b
        ]
        create_branch("foo", force=True)
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert cmds[2] == ["git", "push", "origin", "--delete", "foo"]
        assert cmds[3] == ["git", "checkout", "-b", "foo", "dev"]

    @patch("scripts.ingest_repo.subprocess.run")
    def test_force_remote_delete_failure_warns_but_continues(self, mock_run, capsys):
        """force=True with remote delete failing: prints warning, still creates."""
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr=""),  # rev-parse: no local
            MagicMock(
                returncode=0,
                stdout="abc\trefs/heads/foo\n",
                stderr="",
            ),  # ls-remote: exists
            MagicMock(
                returncode=128,
                stdout="",
                stderr="remote: permission denied",
            ),  # push --delete: fails
            MagicMock(
                returncode=0, stdout="", stderr=""
            ),  # checkout -b: still proceeds
        ]
        # Should NOT raise — warning is printed but create continues
        create_branch("foo", force=True)
        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert "failed to delete remote branch" in captured.err


# ===========================================================================
# git_commit
# ===========================================================================


class TestGitCommit:
    @patch("scripts.ingest_repo.subprocess.run")
    def test_commit_without_body(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        git_commit("feat: add thing")
        args = mock_run.call_args.args[0]
        assert args[0] == "git"
        assert args[1] == "commit"
        assert args[2] == "-m"
        assert args[3] == "feat: add thing"

    @patch("scripts.ingest_repo.subprocess.run")
    def test_commit_with_body(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        git_commit("feat: add thing", body="Long description here")
        args = mock_run.call_args.args[0]
        assert args[3] == "feat: add thing"
        assert args[4] == "-m"
        assert args[5] == "Long description here"

    @patch("scripts.ingest_repo.subprocess.run")
    def test_raises_on_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=128, stderr="nothing to commit", stdout=""
        )
        with pytest.raises(GitError, match="commit failed"):
            git_commit("feat: empty")


# ===========================================================================
# git_push
# ===========================================================================


class TestGitPush:
    @patch("scripts.ingest_repo.subprocess.run")
    def test_push_command_shape(self, mock_run):
        """Push command shape: git push -u origin <branch>."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        git_push("content/ingest-hello-world")
        args = mock_run.call_args.args[0]
        assert args == [
            "git",
            "push",
            "-u",
            "origin",
            "content/ingest-hello-world",
        ]

    @patch("scripts.ingest_repo.subprocess.run")
    def test_uses_timeout_kwarg(self, mock_run):
        """Push must use a timeout to avoid hanging on network issues."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        git_push("content/ingest-hello-world")
        kwargs = mock_run.call_args.kwargs
        assert "timeout" in kwargs
        assert kwargs["timeout"] > 0

    @patch("scripts.ingest_repo.subprocess.run")
    def test_raises_on_nonzero_exit(self, mock_run):
        """Non-zero exit → GitError with the original stderr."""
        mock_run.return_value = MagicMock(
            returncode=128,
            stderr="Permission denied (publickey)",
            stdout="",
        )
        with pytest.raises(GitError, match="git push failed") as exc_info:
            git_push("content/ingest-hello-world")
        assert "Permission denied" in str(exc_info.value)

    @patch("scripts.ingest_repo.subprocess.run")
    def test_raises_on_timeout(self, mock_run):
        """subprocess.TimeoutExpired → GitError with timed out message."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["git", "push"],
            timeout=30,
        )
        with pytest.raises(GitError, match="git push timed out"):
            git_push("content/ingest-hello-world")

    @patch("scripts.ingest_repo.subprocess.run")
    def test_raises_on_os_error(self, mock_run):
        """OSError spawning the process → GitError with spawn-failed message."""
        mock_run.side_effect = OSError("No such file or directory")
        with pytest.raises(GitError, match="git push failed to spawn"):
            git_push("content/ingest-hello-world")

    @patch("scripts.ingest_repo.subprocess.run")
    def test_force_push_uses_force_with_lease(self, mock_run):
        """When force=True, --force-with-lease is in the args."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        git_push("content/ingest-foo", force=True)
        args = mock_run.call_args.args[0]
        assert "--force-with-lease" in args
        assert "-u" in args
        assert "origin" in args
        assert "content/ingest-foo" in args

    @patch("scripts.ingest_repo.subprocess.run")
    def test_default_push_excludes_force_with_lease(self, mock_run):
        """When force=False (default), --force-with-lease is NOT included."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        git_push("content/ingest-foo")
        args = mock_run.call_args.args[0]
        assert "--force-with-lease" not in args
        assert "-u" in args
        assert "origin" in args
        assert "content/ingest-foo" in args


# ===========================================================================
# open_draft_pr
# ===========================================================================


class TestOpenDraftPr:
    @patch("scripts.ingest_repo.is_gh_installed", return_value=True)
    @patch("scripts.ingest_repo.subprocess.run")
    def test_returns_pr_url_on_success(self, mock_run, _is_gh):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="https://github.com/owner/repo/pull/42\n",
            stderr="",
        )
        url = open_draft_pr(title="feat: x", body="body text", base="dev")
        assert url == "https://github.com/owner/repo/pull/42"

    @patch("scripts.ingest_repo.is_gh_installed", return_value=False)
    @patch("scripts.ingest_repo.subprocess.run")
    def test_raises_when_gh_not_installed(self, mock_run, _is_gh):
        with pytest.raises(GitHubCLIError, match="gh CLI not installed"):
            open_draft_pr(title="feat: x", body="body text")
        mock_run.assert_not_called()

    @patch("scripts.ingest_repo.is_gh_installed", return_value=True)
    @patch("scripts.ingest_repo.subprocess.run")
    def test_raises_on_nonzero_exit(self, mock_run, _is_gh):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="error: authentication failed",
        )
        with pytest.raises(GitHubCLIError, match="authentication"):
            open_draft_pr(title="feat: x", body="body text")

    @patch("scripts.ingest_repo.is_gh_installed", return_value=True)
    @patch("scripts.ingest_repo.subprocess.run")
    def test_calls_gh_with_correct_args(self, mock_run, _is_gh):
        mock_run.return_value = MagicMock(returncode=0, stdout="https://x\n", stderr="")
        open_draft_pr(title="feat: x", body="body text", base="main")
        args = mock_run.call_args.args[0]
        assert args[0] == "gh"
        assert args[1] == "pr"
        assert args[2] == "create"
        assert "--draft" in args
        assert "--title" in args
        assert args[args.index("--title") + 1] == "feat: x"
        assert "--body" in args
        assert args[args.index("--body") + 1] == "body text"
        assert "--base" in args
        assert args[args.index("--base") + 1] == "main"

    @patch("scripts.ingest_repo.is_gh_installed", return_value=True)
    @patch("scripts.ingest_repo.subprocess.run")
    def test_default_base_is_dev(self, mock_run, _is_gh):
        mock_run.return_value = MagicMock(returncode=0, stdout="https://x\n", stderr="")
        open_draft_pr(title="t", body="b")
        args = mock_run.call_args.args[0]
        assert args[args.index("--base") + 1] == "dev"


# ===========================================================================
# print_manual_pr_instructions
# ===========================================================================


class TestPrintManualPrInstructions:
    def test_prints_expected_lines(self, capsys):
        print_manual_pr_instructions("content/ingest-foo", base="main")
        captured = capsys.readouterr()
        out = captured.out
        assert "Manual PR creation required" in out
        assert "content/ingest-foo" in out
        assert "main" in out
        assert "gh pr create" in out

    def test_default_base_is_dev(self, capsys):
        print_manual_pr_instructions("feature/x")
        captured = capsys.readouterr()
        assert "dev" in captured.out
