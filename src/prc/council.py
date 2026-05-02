from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import IO

from .context import ContextProvider
from .prompts import CROSS_EVAL_SYSTEM, REVIEWER_SYSTEM
from .reviewers import Reviewer


@dataclass
class CouncilOutcome:
    # letter (A, B, ...) -> (model, R1 markdown)
    r1: dict[str, tuple[str, str]] = field(default_factory=dict)
    # letter -> (model, R2 markdown); only members that completed R2
    r2: dict[str, tuple[str, str]] = field(default_factory=dict)
    # letter -> human-readable failure note
    failures: dict[str, str] = field(default_factory=dict)


def _letter(idx: int) -> str:
    if idx < 26:
        return chr(ord("A") + idx)
    return _letter(idx // 26 - 1) + chr(ord("A") + idx % 26)


_TRANSIENT = ("500", "502", "503", "504", "timeout", "Connection", "ECONN")


def _try_chat(
    rev: Reviewer, system: str, user: str, timeout: float
) -> str:
    try:
        return rev.chat(system, user, timeout=timeout)
    except Exception as e:
        if any(s in str(e) for s in _TRANSIENT):
            time.sleep(2)
            return rev.chat(system, user, timeout=timeout)
        raise


def run_council(
    reviewers: list[Reviewer],
    context: ContextProvider,
    *,
    timeout: float = 180.0,
    verbose: bool = False,
    log_stream: IO[str] = sys.stderr,
) -> CouncilOutcome:
    if not reviewers:
        raise ValueError("council is empty")
    letters = [_letter(i) for i in range(len(reviewers))]
    by_letter = dict(zip(letters, reviewers))
    out = CouncilOutcome()

    # Round 1 — independent reviews
    user_r1 = context.render()
    with ThreadPoolExecutor(max_workers=len(reviewers)) as ex:
        futs = {
            ex.submit(_try_chat, rev, REVIEWER_SYSTEM, user_r1, timeout): letter
            for letter, rev in zip(letters, reviewers)
        }
        for fut in as_completed(futs):
            letter = futs[fut]
            try:
                out.r1[letter] = (by_letter[letter].model, fut.result())
            except Exception as e:
                out.failures[letter] = f"R1: {e!r}"
                if verbose:
                    print(
                        f"prc: R1 fail {letter} "
                        f"({by_letter[letter].model}): {e!r}",
                        file=log_stream,
                    )
    if verbose:
        print(
            f"prc: R1 {len(out.r1)}/{len(reviewers)} ok",
            file=log_stream,
        )

    if len(out.r1) < 2:
        return out  # caller decides whether to abort

    # Round 2 — cross-evaluation among survivors
    survivors = [(l, by_letter[l]) for l in out.r1]
    with ThreadPoolExecutor(max_workers=len(survivors)) as ex:
        futs2 = {}
        for letter, rev in survivors:
            peers_md = "\n\n".join(
                f"### Reviewer {peer_letter}\n{out.r1[peer_letter][1]}"
                for peer_letter, _ in survivors
                if peer_letter != letter
            )
            user_r2 = (
                f"{context.render()}\n\n"
                f"<peer-reviews>\n{peers_md}\n</peer-reviews>"
            )
            futs2[
                ex.submit(_try_chat, rev, CROSS_EVAL_SYSTEM, user_r2, timeout)
            ] = letter
        for fut in as_completed(futs2):
            letter = futs2[fut]
            try:
                out.r2[letter] = (by_letter[letter].model, fut.result())
            except Exception as e:
                prev = out.failures.get(letter, "")
                out.failures[letter] = (prev + f" R2: {e!r}").strip()
                if verbose:
                    print(
                        f"prc: R2 fail {letter}: {e!r}", file=log_stream
                    )
    if verbose:
        print(
            f"prc: R2 {len(out.r2)}/{len(survivors)} ok",
            file=log_stream,
        )
    return out
