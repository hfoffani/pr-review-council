from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from prc.git_ops import DiffResult

from ._diff_utils import count_diff_files, truncate_diff
from .base import PRPlatformError, PullRequestPlatform

ENV_USER = "PRC_BITBUCKET_USER"
ENV_TOKEN = "PRC_BITBUCKET_TOKEN"
API_BASE = "https://api.bitbucket.org/2.0"
HTTP_TIMEOUT = 30.0


class BitBucketPullRequestPlatform(PullRequestPlatform):
    supports_posting = True

    def fetch_diff(self, url: str, *, max_bytes: int) -> DiffResult:
        parsed = _parse_bitbucket_pr_url(url)
        user, token = _require_creds()
        api_url = (
            f"{API_BASE}/repositories/{parsed.workspace}/{parsed.repo}"
            f"/pullrequests/{parsed.number}/diff"
        )
        raw = _http_get_text(api_url, user, token)
        diff, truncated, bytes_total = truncate_diff(raw, max_bytes=max_bytes)
        files_total = count_diff_files(diff)
        return DiffResult(
            base=f"{parsed.workspace}/{parsed.repo}#base",
            branch=f"{parsed.workspace}/{parsed.repo}#{parsed.number}",
            diff=diff,
            files_total=files_total,
            files_included=files_total,
            truncated=truncated,
            bytes_total=bytes_total,
        )

    def post_comment(self, url: str, body: str) -> None:
        parsed = _parse_bitbucket_pr_url(url)
        user, token = _require_creds()
        api_url = (
            f"{API_BASE}/repositories/{parsed.workspace}/{parsed.repo}"
            f"/pullrequests/{parsed.number}/comments"
        )
        _http_post_json(
            api_url,
            {"content": {"raw": body}},
            user,
            token,
            expected_status=201,
        )


@dataclass(frozen=True)
class ParsedBitBucketPR:
    workspace: str
    repo: str
    number: str


def _parse_bitbucket_pr_url(url: str) -> ParsedBitBucketPR:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme not in {"http", "https"} or len(parts) < 4:
        raise PRPlatformError("invalid BitBucket pull request URL")
    workspace, repo, marker, number = parts[:4]
    if marker != "pull-requests" or not number.isdigit():
        raise PRPlatformError("invalid BitBucket pull request URL")
    return ParsedBitBucketPR(workspace, repo, number)


def _require_creds() -> tuple[str, str]:
    user = os.environ.get(ENV_USER, "").strip()
    token = os.environ.get(ENV_TOKEN, "").strip()
    if not user or not token:
        raise PRPlatformError(
            "BitBucket credentials not set; export "
            f"{ENV_USER} (email) and {ENV_TOKEN} "
            "(token needs PR read + write)"
        )
    return user, token


def _basic_auth_header(user: str, token: str) -> str:
    encoded = base64.b64encode(f"{user}:{token}".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def _http_get_text(url: str, user: str, token: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": _basic_auth_header(user, token),
            "Accept": "text/plain",
        },
        method="GET",
    )
    return _read_response_text(req)


def _http_post_json(
    url: str,
    payload: dict,
    user: str,
    token: str,
    *,
    expected_status: int,
) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": _basic_auth_header(user, token),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            status = getattr(resp, "status", resp.getcode())
            if status != expected_status:
                snippet = _read_snippet(resp)
                raise PRPlatformError(
                    f"BitBucket comment post failed ({status})"
                    + (f": {snippet}" if snippet else "")
                )
    except urllib.error.HTTPError as e:
        _raise_for_http_error(e)
    except urllib.error.URLError as e:
        raise PRPlatformError(f"BitBucket request failed: {e.reason}") from e
    except OSError as e:
        raise PRPlatformError(f"BitBucket request failed: {e}") from e


def _read_response_text(req: urllib.request.Request) -> str:
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read()
            return body.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        _raise_for_http_error(e)
    except urllib.error.URLError as e:
        raise PRPlatformError(f"BitBucket request failed: {e.reason}") from e
    except OSError as e:
        raise PRPlatformError(f"BitBucket request failed: {e}") from e
    raise PRPlatformError("BitBucket request failed: no response")


def _raise_for_http_error(e: urllib.error.HTTPError) -> None:
    status = e.code
    if status == 401:
        raise PRPlatformError(
            f"BitBucket auth failed (401); check {ENV_USER} and {ENV_TOKEN}"
        ) from e
    if status == 403:
        raise PRPlatformError(
            "BitBucket forbidden (403); token missing required scopes "
            "(needs Repositories: Read + Pull requests: Read/Write)"
        ) from e
    if status == 404:
        raise PRPlatformError(
            f"BitBucket PR not found (404): {e.url}"
        ) from e
    snippet = _read_snippet(e)
    raise PRPlatformError(
        f"BitBucket request failed ({status})"
        + (f": {snippet}" if snippet else "")
    ) from e


def _read_snippet(resp_or_err) -> str:
    try:
        body = resp_or_err.read()
    except Exception:
        return ""
    if not body:
        return ""
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    return body.strip()[:200]
