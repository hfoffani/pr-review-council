from __future__ import annotations

import base64
import io
import json
import urllib.error
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


def test_github_subprocess_oserror_is_reported(monkeypatch) -> None:
    monkeypatch.setattr("prc.pr_platforms.github.shutil.which", lambda name: "/bin/gh")

    def run(cmd, text, capture_output):
        raise OSError("permission denied")

    monkeypatch.setattr("prc.pr_platforms.github.subprocess.run", run)

    with pytest.raises(PRPlatformError, match="failed to run 'gh'.*permission denied"):
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
    with pytest.raises(NotImplementedError, match="GitLab support is coming soon"):
        GitLabPullRequestPlatform().fetch_diff("https://gitlab.com/x/y", max_bytes=1)
    with pytest.raises(UnsupportedPRHost, match="unsupported PR host: example.com"):
        platform_for_url("https://example.com/org/repo/pull/1")


# ---------- BitBucket Cloud ----------


_BB_USER = "alice@example.com"
_BB_TOKEN = "tkn123"
_BB_BASIC = "Basic " + base64.b64encode(f"{_BB_USER}:{_BB_TOKEN}".encode()).decode()
_BB_PR_URL = "https://bitbucket.org/myws/myrepo/pull-requests/42"


class _FakeResp:
    def __init__(self, body: bytes = b"", status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *args) -> bool:
        return False


def _set_bb_env(monkeypatch) -> None:
    monkeypatch.setenv("PRC_BITBUCKET_USER", _BB_USER)
    monkeypatch.setenv("PRC_BITBUCKET_TOKEN", _BB_TOKEN)


def _capture_urlopen(monkeypatch, response):
    calls: list[dict] = []

    def fake_urlopen(req, timeout=None):
        calls.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "headers": dict(req.header_items()),
                "data": req.data,
                "timeout": timeout,
            }
        )
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response(req)
        return response

    monkeypatch.setattr(
        "prc.pr_platforms.bitbucket.urllib.request.urlopen", fake_urlopen
    )
    return calls


def test_bitbucket_fetch_diff_calls_api_with_basic_auth(monkeypatch) -> None:
    _set_bb_env(monkeypatch)
    body = b"diff --git a/file.py b/file.py\n+change\n"
    calls = _capture_urlopen(monkeypatch, _FakeResp(body=body, status=200))

    diff = BitBucketPullRequestPlatform().fetch_diff(_BB_PR_URL, max_bytes=600_000)

    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "GET"
    assert call["url"] == (
        "https://api.bitbucket.org/2.0/repositories/myws/myrepo"
        "/pullrequests/42/diff"
    )
    assert call["headers"]["Authorization"] == _BB_BASIC
    assert call["headers"]["Accept"] == "text/plain"
    assert call["data"] is None
    assert diff.diff.startswith("diff --git")
    assert diff.files_total == 1
    assert diff.truncated is False


def test_bitbucket_post_comment_posts_json_with_basic_auth(monkeypatch) -> None:
    _set_bb_env(monkeypatch)
    calls = _capture_urlopen(monkeypatch, _FakeResp(body=b"{}", status=201))

    BitBucketPullRequestPlatform().post_comment(_BB_PR_URL, "final review")

    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "POST"
    assert call["url"] == (
        "https://api.bitbucket.org/2.0/repositories/myws/myrepo"
        "/pullrequests/42/comments"
    )
    assert call["headers"]["Authorization"] == _BB_BASIC
    assert call["headers"]["Content-type"] == "application/json"
    assert json.loads(call["data"]) == {"content": {"raw": "final review"}}


def test_bitbucket_url_accepts_overview_trailer(monkeypatch) -> None:
    _set_bb_env(monkeypatch)
    calls = _capture_urlopen(
        monkeypatch, _FakeResp(body=b"diff --git a/x b/x\n", status=200)
    )

    BitBucketPullRequestPlatform().fetch_diff(
        _BB_PR_URL + "/overview", max_bytes=600_000
    )

    assert calls[0]["url"].endswith("/pullrequests/42/diff")


def test_bitbucket_url_accepts_arbitrary_trailers(monkeypatch) -> None:
    _set_bb_env(monkeypatch)
    for trailer in ("/diff", "/commits", "/activity", "/overview/extra/path"):
        calls = _capture_urlopen(
            monkeypatch, _FakeResp(body=b"diff --git a/x b/x\n", status=200)
        )
        BitBucketPullRequestPlatform().fetch_diff(
            _BB_PR_URL + trailer, max_bytes=600_000
        )
        assert calls[0]["url"].endswith("/pullrequests/42/diff")


def test_bitbucket_invalid_pr_url_is_rejected(monkeypatch) -> None:
    _set_bb_env(monkeypatch)
    bad_urls = [
        "https://bitbucket.org/myws/myrepo",
        "https://bitbucket.org/myws/myrepo/pull-requests/abc",
        "https://bitbucket.org/myws/myrepo/issues/42",
        "ftp://bitbucket.org/myws/myrepo/pull-requests/42",
    ]
    for url in bad_urls:
        with pytest.raises(PRPlatformError, match="invalid BitBucket pull request URL"):
            BitBucketPullRequestPlatform().fetch_diff(url, max_bytes=600_000)


def test_bitbucket_missing_env_vars_raise_credentials_error(monkeypatch) -> None:
    monkeypatch.delenv("PRC_BITBUCKET_USER", raising=False)
    monkeypatch.delenv("PRC_BITBUCKET_TOKEN", raising=False)
    with pytest.raises(PRPlatformError, match="BitBucket credentials not set"):
        BitBucketPullRequestPlatform().fetch_diff(_BB_PR_URL, max_bytes=600_000)

    monkeypatch.setenv("PRC_BITBUCKET_USER", _BB_USER)
    with pytest.raises(PRPlatformError, match="BitBucket credentials not set"):
        BitBucketPullRequestPlatform().fetch_diff(_BB_PR_URL, max_bytes=600_000)

    monkeypatch.delenv("PRC_BITBUCKET_USER", raising=False)
    monkeypatch.setenv("PRC_BITBUCKET_TOKEN", _BB_TOKEN)
    with pytest.raises(PRPlatformError, match="BitBucket credentials not set"):
        BitBucketPullRequestPlatform().fetch_diff(_BB_PR_URL, max_bytes=600_000)


def _http_error(status: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url=_BB_PR_URL,
        code=status,
        msg="error",
        hdrs={},
        fp=io.BytesIO(body),
    )


def test_bitbucket_401_maps_to_auth_error(monkeypatch) -> None:
    _set_bb_env(monkeypatch)
    _capture_urlopen(monkeypatch, _http_error(401, b"unauthorized"))
    with pytest.raises(PRPlatformError, match="auth failed.*401"):
        BitBucketPullRequestPlatform().fetch_diff(_BB_PR_URL, max_bytes=600_000)


def test_bitbucket_403_mentions_token_scope(monkeypatch) -> None:
    _set_bb_env(monkeypatch)
    _capture_urlopen(monkeypatch, _http_error(403, b"forbidden"))
    with pytest.raises(PRPlatformError, match="403.*PR read/write scope"):
        BitBucketPullRequestPlatform().fetch_diff(_BB_PR_URL, max_bytes=600_000)


def test_bitbucket_404_mentions_pr_not_found(monkeypatch) -> None:
    _set_bb_env(monkeypatch)
    _capture_urlopen(monkeypatch, _http_error(404, b"not found"))
    with pytest.raises(PRPlatformError, match="PR not found.*404"):
        BitBucketPullRequestPlatform().fetch_diff(_BB_PR_URL, max_bytes=600_000)


def test_bitbucket_post_comment_non_201_raises(monkeypatch) -> None:
    _set_bb_env(monkeypatch)
    _capture_urlopen(monkeypatch, _FakeResp(body=b"{}", status=200))
    with pytest.raises(PRPlatformError, match="comment post failed.*200"):
        BitBucketPullRequestPlatform().post_comment(_BB_PR_URL, "body")


def test_bitbucket_url_error_is_reported(monkeypatch) -> None:
    _set_bb_env(monkeypatch)
    _capture_urlopen(monkeypatch, urllib.error.URLError("network down"))
    with pytest.raises(PRPlatformError, match="request failed.*network down"):
        BitBucketPullRequestPlatform().fetch_diff(_BB_PR_URL, max_bytes=600_000)


def test_bitbucket_diff_truncation_preserves_lines_and_reports_original_bytes(
    monkeypatch,
) -> None:
    _set_bb_env(monkeypatch)
    body = "diff --git a/file.py b/file.py\n+áéíóú\n+second\n".encode("utf-8")
    _capture_urlopen(monkeypatch, _FakeResp(body=body, status=200))

    diff = BitBucketPullRequestPlatform().fetch_diff(_BB_PR_URL, max_bytes=35)

    assert diff.truncated is True
    assert diff.diff == (
        "diff --git a/file.py b/file.py\n\n"
        f"TRUNCATED: remote PR diff capped at 35 bytes "
        f"(original {diff.bytes_total} bytes).\n"
    )
