from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


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
