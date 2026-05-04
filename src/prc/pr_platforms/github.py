from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse

from prc.git_ops import DiffResult

from .base import PRPlatformError, PullRequestPlatform

GH = "gh"


class GitHubPullRequestPlatform(PullRequestPlatform):
    supports_posting = True

    def fetch_diff(self, url: str, *, max_bytes: int) -> DiffResult:
        parsed = _parse_github_pr_url(url)
        _ensure_gh(url)
        diff, truncated, bytes_total = _truncate_diff(
            _run_gh([GH, "pr", "diff", url], url),
            max_bytes=max_bytes,
        )
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
        _parse_github_pr_url(url)
        _ensure_gh(url)
        _run_gh([GH, "pr", "comment", url, "--body", body], url)


@dataclass(frozen=True)
class ParsedGitHubPR:
    owner: str
    repo: str
    number: str


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
    if shutil.which(GH) is None:
        raise PRPlatformError(
            "GitHub CLI not found; install gh from https://cli.github.com/"
        )
    host = _host(url)
    auth = _run_command([GH, "auth", "status", "--hostname", host])
    if auth.returncode != 0:
        raise PRPlatformError(_auth_message(host))


def _run_gh(cmd: list[str], url: str) -> str:
    res = _run_command(cmd)
    if res.returncode != 0:
        stderr = res.stderr.strip()
        if "authentication" in stderr.lower() or "not logged" in stderr.lower():
            raise PRPlatformError(_auth_message(_host(url)))
        detail = f": {stderr}" if stderr else ""
        raise PRPlatformError(f"gh failed{detail}")
    return res.stdout


def _run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, text=True, capture_output=True)
    except OSError as e:
        raise PRPlatformError(f"failed to run {cmd[0]!r}: {e}") from e


def _truncate_diff(diff: str, *, max_bytes: int) -> tuple[str, bool, int]:
    bytes_total = len(diff.encode("utf-8"))
    if bytes_total <= max_bytes:
        return diff, False, bytes_total
    if bytes_total > max_bytes * 5:
        raise PRPlatformError(
            f"remote PR diff is {bytes_total} bytes (>5x cap of {max_bytes}); "
            "raise --max-diff-bytes or split the pull request"
        )
    chunks: list[str] = []
    used = 0
    for line in diff.splitlines(keepends=True):
        line_bytes = len(line.encode("utf-8"))
        if used + line_bytes > max_bytes:
            break
        chunks.append(line)
        used += line_bytes
    truncated = "".join(chunks)
    if not truncated:
        truncated = diff[: max(1, max_bytes // 4)]
    return (
        truncated.rstrip()
        + "\n\n"
        + f"TRUNCATED: remote PR diff capped at {max_bytes} bytes "
        + f"(original {bytes_total} bytes).\n",
        True,
        bytes_total,
    )


def _count_diff_files(diff: str) -> int:
    return sum(1 for line in diff.splitlines() if line.startswith("diff --git "))


def _host(url: str) -> str:
    return urlparse(url).hostname or "github.com"


def _auth_message(host: str) -> str:
    return f"gh is not authenticated for {host}; run `gh auth login --hostname {host}`"
