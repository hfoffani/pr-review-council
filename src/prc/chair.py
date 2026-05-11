from __future__ import annotations

from .context import ContextProvider
from .council import CouncilOutcome
from .prompts import DEFAULT_PROMPTS, PromptSet
from .reviewers import Reviewer


def synthesize(
    chair: Reviewer,
    outcome: CouncilOutcome,
    context: ContextProvider,
    *,
    timeout: float = 180.0,
    prompts: PromptSet | None = None,
) -> str:
    """Run round 3: chair sees diff + all R1 + all R2 (peers anonymized)."""
    prompt_set = prompts or DEFAULT_PROMPTS
    r1_md = "\n\n".join(
        f"### Reviewer {letter}\n{review}"
        for letter, (_model, review) in outcome.r1.items()
    )
    r2_md = "\n\n".join(
        f"### Reviewer {letter}'s critique of peers\n{critique}"
        for letter, (_model, critique) in outcome.r2.items()
    )
    user = (
        f"{context.render()}\n\n"
        f"<round-1-reviews>\n{r1_md}\n</round-1-reviews>\n\n"
        f"<round-2-cross-evaluations>\n{r2_md}\n</round-2-cross-evaluations>"
    )
    return chair.chat(prompt_set.chair, user, timeout=timeout)
