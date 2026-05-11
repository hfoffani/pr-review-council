from __future__ import annotations

from prc.chair import synthesize
from prc.context import DiffOnlyContext
from prc.council import CouncilOutcome
from prc.prompts import DEFAULT_PROMPTS, PromptSet
from prc.reviewers.base import Reviewer


class FakeChair(Reviewer):
    def __init__(self) -> None:
        self.model = "chair-model"
        self.display_name = "chair-model"
        self.system_prompt = ""
        self.user_prompt = ""

    def chat(self, system: str, user: str, *, timeout: float) -> str:
        self.system_prompt = system
        self.user_prompt = user
        return "final"


def test_chair_prompt_keeps_reviewer_models_anonymous() -> None:
    chair = FakeChair()
    outcome = CouncilOutcome(
        r1={"A": ("model-a", "review a")},
        r2={"A": ("model-a", "critique a")},
    )

    final = synthesize(chair, outcome, DiffOnlyContext(diff="diff"), timeout=5.0)

    assert final == "final"
    assert "Reviewer A" in chair.user_prompt
    assert "model-a" not in chair.user_prompt


def test_custom_chair_prompt_is_used() -> None:
    chair = FakeChair()
    outcome = CouncilOutcome(r1={"A": ("model-a", "review a")})
    prompt_set = PromptSet(
        reviewer=DEFAULT_PROMPTS.reviewer,
        cross_eval=DEFAULT_PROMPTS.cross_eval,
        chair="custom chair prompt",
    )

    final = synthesize(
        chair,
        outcome,
        DiffOnlyContext(diff="diff"),
        timeout=5.0,
        prompts=prompt_set,
    )

    assert final == "final"
    assert chair.system_prompt == "custom chair prompt"
