from __future__ import annotations

import shutil
import subprocess
from urllib.parse import urlparse

from prc.git_ops import DiffResult

from .base import PRPlatformError, PullRequestPlatform


class GitHubPullRequestPlatform(PullRequestPlatform):
    def fetch_diff(self, url: str, *, max_bytes: int) -> DiffResult:
        _ensure_gh(url)
        diff, truncated, bytes_total = _truncate_diff(
            _run_gh(["gh", "pr", "diff", url], url),
            max_bytes=max_bytes,
        )
        parsed = _parse_github_pr_url(url)
        files_total = _count_diff_files(diff)
        return DiffResult(
            base=f"{parsed.owner}/{parsed.repo}#base",
            branch=f"{parsed.owner}/{parsed.repo}#{parsed.number}",
            diff=diff,
            files_total=files_total,
            files_included=files_total,
            truncated=truncated,
            bytes_total=bytes_total,
        )

    def post_comment(self, url: str, body: str) -> None:
        _ensure_gh(url)
        _run_gh(["gh", "pr", "comment", url, "--body", body], url)


class ParsedGitHubPR:
    def __init__(self, owner: str, repo: str, number: str) -> None:
        self.owner = owner
        self.repo = repo
        self.number = number


def _parse_github_pr_url(url: str) -> ParsedGitHubPR:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme not in {"http", "https"} or len(parts) < 4:
        raise PRPlatformError("invalid GitHub pull request URL")
    owner, repo, marker, number = parts[:4]
    if marker != "pull" or not number.isdigit():
        raise PRPlatformError("invalid GitHub pull request URL")
    return ParsedGitHubPR(owner, repo, number)


def _ensure_gh(url: str) -> None:
    if shutil.which("gh") is None:
        raise PRPlatformError(
            "GitHub CLI not found; install gh from https://cli.github.com/"
        )
    host = urlparse(url).hostname or "github.com"
    auth = subprocess.run(
        ["gh", "auth", "status", "--hostname", host],
        text=True,
        capture_output=True,
    )
    if auth.returncode != 0:
        raise PRPlatformError(
            f"gh is not authenticated for {host}; run `gh auth login --hostname {host}`"
        )


def _run_gh(cmd: list[str], url: str) -> str:
    res = subprocess.run(cmd, text=True, capture_output=True)
    if res.returncode != 0:
        stderr = res.stderr.strip()
        host = urlparse(url).hostname or "github.com"
        if "authentication" in stderr.lower() or "not logged" in stderr.lower():
            raise PRPlatformError(
                f"gh is not authenticated for {host}; run `gh auth login --hostname {host}`"
            )
        detail = f": {stderr}" if stderr else ""
        raise PRPlatformError(f"gh failed{detail}")
    return res.stdout


def _truncate_diff(diff: str, *, max_bytes: int) -> tuple[str, bool, int]:
    bytes_total = len(diff.encode("utf-8"))
    if bytes_total <= max_bytes:
        return diff, False, bytes_total
    if bytes_total > max_bytes * 5:
        raise PRPlatformError(
            f"remote PR diff is {bytes_total} bytes (>5x cap of {max_bytes}); "
            "raise --max-diff-bytes or split the pull request"
        )
    truncated = diff.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
    return (
        truncated.rstrip()
        + f"\n\nTRUNCATED: remote PR diff capped at {max_bytes} bytes.\n",
        True,
        bytes_total,
    )


def _count_diff_files(diff: str) -> int:
    return sum(1 for line in diff.splitlines() if line.startswith("diff --git "))
