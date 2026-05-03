"""Recording-only spinner mock for the README demo GIF.

Reuses prc's actual progress strings so visuals match the real CLI exactly.
No API calls. Ignores argv so an alias of `prc review` can drive it.
"""
from __future__ import annotations

import time

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from prc.cli import (
    PROGRESS_CHAIR,
    PROGRESS_COUNCIL_START,
    PROGRESS_R1,
    PROGRESS_R2,
)

PHASES = [
    (PROGRESS_COUNCIL_START, 0.8),
    (PROGRESS_R1, 2.0),
    (PROGRESS_R2, 1.5),
    (PROGRESS_CHAIR, 1.5),
]

REPORT = """\
## Summary
Adds JWT refresh-token rotation to the auth middleware.

## Blocking Issues
- [blocker] auth/jwt.py:142 — refresh token reused after rotation; replay window not closed.
- [blocker] auth/middleware.py:88 — token hash compared with `==`, timing leak; use `hmac.compare_digest`.

## Points of Disagreement
- Reviewer B flagged the new Redis call as a hot-path regression; A and C disagreed.
  Chair: agree with A/C — the call is async and gated on cache miss.
- Reviewer A wanted refresh-token TTL in config; C wanted it hardcoded.
  Chair: config, with a sane default.

## Verdict
Verdict: request-changes
"""


def main() -> None:
    console = Console(stderr=True)
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        console=console,
        transient=False,
    ) as progress:
        task_id = progress.add_task(PHASES[0][0], total=None)
        for description, seconds in PHASES:
            progress.update(task_id, description=description)
            time.sleep(seconds)
    print(REPORT)


if __name__ == "__main__":
    main()
