from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["approve", "request-changes", "comment"]


@dataclass(frozen=True)
class Review:
    model: str
    raw_markdown: str
    verdict: Verdict | None = None


class Reviewer(ABC):
    model: str
    display_name: str

    @abstractmethod
    def chat(self, system: str, user: str, *, timeout: float) -> str: ...
