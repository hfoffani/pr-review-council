from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse

from prc.git_ops import DiffResult

from ._diff_utils import count_diff_files, truncate_diff
from .base import PRPlatformError, PullRequestMetadata, PullRequestPlatform

GH = "gh"


class GitHubPullRequestPlatform(PullRequestPlatform):
    supports_posting = True

    def fetch_diff(self, url: str, *, max_bytes: int) -> DiffResult:
        parsed = _parse_github_pr_url(url)
        _ensure_gh(url)
        diff, truncated, bytes_total = truncate_diff(
            _run_gh([GH, "pr", "diff", url], url),
            max_bytes=max_bytes,
        )
        files_total = count_diff_files(diff)
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

    def fetch_metadata(self, url: str) -> PullRequestMetadata:
        _parse_github_pr_url(url)
        _ensure_gh(url)
        raw = _run_gh([GH, "pr", "view", url, "--json", "title,body,url"], url)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise PRPlatformError("gh returned invalid PR metadata JSON") from e
        return PullRequestMetadata(
            title=_json_string(data, "title"),
            description=_json_string(data, "body"),
            url=_json_string(data, "url") or url,
        )


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


def _json_string(data: object, key: str) -> str:
    if not isinstance(data, dict):
        return ""
    value = data.get(key)
    return value if isinstance(value, str) else ""


def _host(url: str) -> str:
    return urlparse(url).hostname or "github.com"


def _auth_message(host: str) -> str:
    return f"gh is not authenticated for {host}; run `gh auth login --hostname {host}`"
