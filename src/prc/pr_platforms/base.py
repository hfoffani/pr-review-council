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


class PullRequestPlatform:
    def fetch_diff(self, url: str, *, max_bytes: int) -> DiffResult:
        raise NotImplementedError

    def post_comment(self, url: str, body: str) -> None:
        raise NotImplementedError
