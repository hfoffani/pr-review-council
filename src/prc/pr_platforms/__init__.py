from __future__ import annotations

from urllib.parse import urlparse

from .base import (
    PRPlatformError,
    PullRequestMetadata,
    PullRequestPlatform,
    UnsupportedPRHost,
)
from .bitbucket import BitBucketPullRequestPlatform
from .github import GitHubPullRequestPlatform
from .gitlab import GitLabPullRequestPlatform


def is_pr_url(value: object) -> bool:
    parsed = urlparse(str(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def platform_for_url(url: str) -> PullRequestPlatform:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host == "github.com" or host.endswith(".github.com"):
        return GitHubPullRequestPlatform()
    if host == "bitbucket.org" or host.endswith(".bitbucket.org"):
        return BitBucketPullRequestPlatform()
    if host == "gitlab.com" or host.endswith(".gitlab.com"):
        return GitLabPullRequestPlatform()
    raise UnsupportedPRHost(f"unsupported PR host: {host}")


__all__ = [
    "PRPlatformError",
    "PullRequestMetadata",
    "PullRequestPlatform",
    "UnsupportedPRHost",
    "is_pr_url",
    "platform_for_url",
]
