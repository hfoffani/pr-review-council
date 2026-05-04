from __future__ import annotations

from .base import PullRequestPlatform


class GitLabPullRequestPlatform(PullRequestPlatform):
    def fetch_diff(self, url: str, *, max_bytes: int):  # noqa: ANN201
        raise NotImplementedError("GitLab support is coming soon")

    def post_comment(self, url: str, body: str) -> None:
        raise NotImplementedError("GitLab support is coming soon")
