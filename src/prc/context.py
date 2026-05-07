from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from html import escape

from prc.pr_platforms.base import PullRequestMetadata


class ContextProvider(ABC):
    """Supplies the user-message body that reviewers see in round 1.

    MVP: only the diff. Future implementations may attach PR metadata,
    repo-local skill files (`pull-request.md`), prior comments, etc.
    """

    @abstractmethod
    def render(self) -> str: ...


@dataclass
class DiffOnlyContext(ContextProvider):
    diff: str

    def render(self) -> str:
        return f"<diff>\n{self.diff}\n</diff>"


@dataclass
class PullRequestContext(ContextProvider):
    diff: str
    metadata: PullRequestMetadata

    def render(self) -> str:
        title = _escape_optional(self.metadata.title)
        description = _escape_optional(self.metadata.description)
        url = _escape_optional(self.metadata.url)
        return (
            "<pull_request>\n"
            f"<title>{title}</title>\n"
            f"<description>\n{description}\n</description>\n"
            f"<url>{url}</url>\n"
            "</pull_request>\n\n"
            f"<diff>\n{self.diff}\n</diff>"
        )


def _escape_optional(value: object) -> str:
    return escape(value) if isinstance(value, str) else ""
