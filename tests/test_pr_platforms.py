from __future__ import annotations

from types import SimpleNamespace

import pytest

from prc.pr_platforms import platform_for_url
from prc.pr_platforms.base import PRPlatformError, UnsupportedPRHost
from prc.pr_platforms.bitbucket import BitBucketPullRequestPlatform
from prc.pr_platforms.github import GitHubPullRequestPlatform
from prc.pr_platforms.gitlab import GitLabPullRequestPlatform


def test_github_fetch_diff_uses_gh_pr_diff(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr("prc.pr_platforms.github.shutil.which", lambda name: "/bin/gh")

    def run(cmd, text, capture_output):
        calls.append(cmd)
        if cmd[:3] == ["gh", "auth", "status"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout="diff --git a/file.py b/file.py\n+change\n",
            stderr="",
        )

    monkeypatch.setattr("prc.pr_platforms.github.subprocess.run", run)

    diff = GitHubPullRequestPlatform().fetch_diff(
        "https://github.com/hfoffani/pr-review-council/pull/33",
        max_bytes=600_000,
    )

    assert calls == [
        ["gh", "auth", "status", "--hostname", "github.com"],
        [
            "gh",
            "pr",
            "diff",
            "https://github.com/hfoffani/pr-review-council/pull/33",
        ],
    ]
    assert diff.diff.startswith("diff --git")
    assert diff.files_total == 1


def test_github_post_comment_uses_gh_pr_comment(monkeypatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr("prc.pr_platforms.github.shutil.which", lambda name: "/bin/gh")

    def run(cmd, text, capture_output):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("prc.pr_platforms.github.subprocess.run", run)

    GitHubPullRequestPlatform().post_comment(
        "https://github.com/hfoffani/pr-review-council/pull/33",
        "final review",
    )

    assert calls == [
        ["gh", "auth", "status", "--hostname", "github.com"],
        [
            "gh",
            "pr",
            "comment",
            "https://github.com/hfoffani/pr-review-council/pull/33",
            "--body",
            "final review",
        ],
    ]


def test_github_missing_cli_has_install_message(monkeypatch) -> None:
    monkeypatch.setattr("prc.pr_platforms.github.shutil.which", lambda name: None)

    with pytest.raises(PRPlatformError, match="install gh"):
        GitHubPullRequestPlatform().fetch_diff(
            "https://github.com/hfoffani/pr-review-council/pull/33",
            max_bytes=600_000,
        )


def test_github_invalid_pr_url_is_rejected_before_cli_checks(monkeypatch) -> None:
    monkeypatch.setattr(
        "prc.pr_platforms.github.shutil.which",
        lambda name: (_ for _ in ()).throw(
            AssertionError("gh lookup should not run")
        ),
    )

    with pytest.raises(PRPlatformError, match="invalid GitHub pull request URL"):
        GitHubPullRequestPlatform().fetch_diff(
            "https://github.com/hfoffani/pr-review-council/issues/33",
            max_bytes=600_000,
        )


def test_github_unauthenticated_cli_has_login_message(monkeypatch) -> None:
    monkeypatch.setattr("prc.pr_platforms.github.shutil.which", lambda name: "/bin/gh")
    monkeypatch.setattr(
        "prc.pr_platforms.github.subprocess.run",
        lambda cmd, text, capture_output: SimpleNamespace(
            returncode=1, stdout="", stderr="not logged in"
        ),
    )

    with pytest.raises(PRPlatformError, match="gh auth login"):
        GitHubPullRequestPlatform().fetch_diff(
            "https://github.com/hfoffani/pr-review-council/pull/33",
            max_bytes=600_000,
        )


def test_github_diff_truncation_preserves_lines_and_reports_original_bytes(
    monkeypatch,
) -> None:
    monkeypatch.setattr("prc.pr_platforms.github.shutil.which", lambda name: "/bin/gh")

    def run(cmd, text, capture_output):
        if cmd[:3] == ["gh", "auth", "status"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout="diff --git a/file.py b/file.py\n+áéíóú\n+second\n",
            stderr="",
        )

    monkeypatch.setattr("prc.pr_platforms.github.subprocess.run", run)

    diff = GitHubPullRequestPlatform().fetch_diff(
        "https://github.com/hfoffani/pr-review-council/pull/33",
        max_bytes=35,
    )

    assert diff.truncated is True
    assert diff.diff == (
        "diff --git a/file.py b/file.py\n\n"
        f"TRUNCATED: remote PR diff capped at 35 bytes "
        f"(original {diff.bytes_total} bytes).\n"
    )


def test_platform_stubs_and_unsupported_hosts() -> None:
    assert isinstance(
        platform_for_url("https://bitbucket.org/org/repo/pull-requests/1"),
        BitBucketPullRequestPlatform,
    )
    assert isinstance(
        platform_for_url("https://gitlab.com/org/repo/-/merge_requests/1"),
        GitLabPullRequestPlatform,
    )
    with pytest.raises(NotImplementedError, match="BitBucket support is coming soon"):
        BitBucketPullRequestPlatform().fetch_diff("https://bitbucket.org/x/y", max_bytes=1)
    with pytest.raises(NotImplementedError, match="GitLab support is coming soon"):
        GitLabPullRequestPlatform().fetch_diff("https://gitlab.com/x/y", max_bytes=1)
    with pytest.raises(UnsupportedPRHost, match="unsupported PR host: example.com"):
        platform_for_url("https://example.com/org/repo/pull/1")
