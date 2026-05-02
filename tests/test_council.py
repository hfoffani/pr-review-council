from __future__ import annotations

from prc.context import DiffOnlyContext
from prc.council import run_council
from prc.reviewers.base import Reviewer


class FakeReviewer(Reviewer):
    def __init__(self, model: str, *, fail_on: set[str] | None = None) -> None:
        self.model = model
        self.display_name = model
        self.calls: list[tuple[str, str]] = []
        self._fail_on = fail_on or set()

    def chat(self, system: str, user: str, *, timeout: float) -> str:
        self.calls.append((system, user))
        for tag in self._fail_on:
            if tag in system:
                raise RuntimeError(f"forced fail in {tag}")
        return f"REVIEW from {self.model}"


def test_blinding_excludes_own_review_in_r2() -> None:
    revs = [FakeReviewer("m1"), FakeReviewer("m2"), FakeReviewer("m3")]
    ctx = DiffOnlyContext(diff="diff body")
    out = run_council(revs, ctx, timeout=5.0)
    assert set(out.r1) == {"A", "B", "C"}
    assert set(out.r2) == {"A", "B", "C"}
    # Each R2 prompt must include the *other* two reviewers' R1 markdown but not its own.
    for rev, letter in zip(revs, ["A", "B", "C"]):
        r2_user = rev.calls[1][1]
        for peer_letter in {"A", "B", "C"} - {letter}:
            assert f"### Reviewer {peer_letter}" in r2_user
        assert f"### Reviewer {letter}" not in r2_user


def test_partial_failure_drops_member_from_r2() -> None:
    revs = [
        FakeReviewer("m1"),
        FakeReviewer("m2", fail_on={"senior software engineer"}),  # R1 prompt
        FakeReviewer("m3"),
    ]
    ctx = DiffOnlyContext(diff="d")
    out = run_council(revs, ctx, timeout=5.0)
    assert set(out.r1) == {"A", "C"}
    assert "B" in out.failures
    # R2 only runs for survivors; m2 should not have been called for R2
    assert len(revs[1].calls) == 1  # only the R1 attempt
    # Survivors saw only one peer (each other)
    for letter, rev in zip(["A", "C"], [revs[0], revs[2]]):
        r2_user = rev.calls[1][1]
        other = "C" if letter == "A" else "A"
        assert f"### Reviewer {other}" in r2_user
        assert "### Reviewer B" not in r2_user


def test_council_collapse_returns_early() -> None:
    revs = [
        FakeReviewer("m1", fail_on={"senior software engineer"}),
        FakeReviewer("m2", fail_on={"senior software engineer"}),
    ]
    ctx = DiffOnlyContext(diff="d")
    out = run_council(revs, ctx, timeout=5.0)
    assert out.r1 == {}
    assert out.r2 == {}
    assert set(out.failures) == {"A", "B"}


def test_chair_on_council_reuses_instance() -> None:
    """Chair instance shared with council list — only one R1 call for chair."""
    chair = FakeReviewer("chair-model")
    other = FakeReviewer("other-model")
    revs = [chair, other]
    ctx = DiffOnlyContext(diff="d")
    out = run_council(revs, ctx, timeout=5.0)
    assert len(chair.calls) == 2  # R1 + R2
    assert len(other.calls) == 2
    assert set(out.r1) == {"A", "B"}


def test_progress_reports_rounds() -> None:
    revs = [FakeReviewer("m1"), FakeReviewer("m2")]
    phases: list[str] = []

    out = run_council(
        revs,
        DiffOnlyContext(diff="d"),
        timeout=5.0,
        progress=phases.append,
    )

    assert set(out.r1) == {"A", "B"}
    assert set(out.r2) == {"A", "B"}
    assert phases == ["r1", "r2"]


def test_progress_skips_r2_when_council_collapses() -> None:
    revs = [
        FakeReviewer("m1", fail_on={"senior software engineer"}),
        FakeReviewer("m2", fail_on={"senior software engineer"}),
    ]
    phases: list[str] = []

    out = run_council(
        revs,
        DiffOnlyContext(diff="d"),
        timeout=5.0,
        progress=phases.append,
    )

    assert out.r1 == {}
    assert out.r2 == {}
    assert phases == ["r1"]


def test_progress_callback_failures_do_not_abort_council() -> None:
    revs = [FakeReviewer("m1"), FakeReviewer("m2")]
    phases: list[str] = []

    def fail_progress(phase: str) -> None:
        phases.append(phase)
        raise RuntimeError("progress renderer failed")

    out = run_council(
        revs,
        DiffOnlyContext(diff="d"),
        timeout=5.0,
        progress=fail_progress,
    )

    assert set(out.r1) == {"A", "B"}
    assert set(out.r2) == {"A", "B"}
    assert phases == ["r1", "r2"]
