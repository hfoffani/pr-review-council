from __future__ import annotations

from dataclasses import dataclass

from prc.git_ops import DiffResult


class PRPlatformError(Exception):
    pass


class UnsupportedPRHost(PRPlatformError):
    pass


@dataclass(frozen=True)
class RemotePullRequest:
    url: str
    host: str


@dataclass(frozen=True)
class PullRequestMetadata:
    title: str
    description: str
    url: str


class PullRequestPlatform:
    """Adapter for fetching and optionally commenting on remote pull requests."""

    supports_posting = False

    def fetch_diff(self, url: str, *, max_bytes: int) -> DiffResult:
        """Return a reviewable diff for the pull request URL."""
        raise NotImplementedError

    def fetch_metadata(self, url: str) -> PullRequestMetadata | None:
        """Return pull request title/description when the host supports it."""
        return None

    def post_comment(self, url: str, body: str) -> None:
        """Post a generated review body as a normal pull request comment."""
        raise NotImplementedError
