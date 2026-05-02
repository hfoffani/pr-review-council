from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from prc import cli
from prc.council import CouncilOutcome
from prc.git_ops import DiffResult, GitError


runner = CliRunner()


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        council=["model-a", "model-b"],
        chair_model="chair-model",
        chair_on_council=False,
        providers={},
        api_keys={},
    )


def test_cli_empty_diff_exits_zero(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())
    monkeypatch.setattr(
        cli,
        "capture_diff",
        lambda repo, branch, base, max_bytes: DiffResult(
            base="main",
            branch=branch,
            diff="",
            files_total=0,
            files_included=0,
            truncated=False,
            bytes_total=0,
        ),
    )

    res = runner.invoke(cli.app, [str(tmp_path), "feature"])

    assert res.exit_code == 0
    assert "no changes" in res.stderr


def test_cli_git_error_maps_to_exit_4(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())

    def fail(*args, **kwargs):
        raise GitError("bad diff")

    monkeypatch.setattr(cli, "capture_diff", fail)

    res = runner.invoke(cli.app, [str(tmp_path), "feature"])

    assert res.exit_code == 4
    assert "bad diff" in res.stderr


def test_cli_config_error_maps_to_exit_5(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        cli.cfg,
        "load",
        lambda explicit=None: (_ for _ in ()).throw(ValueError("bad config")),
    )

    res = runner.invoke(cli.app, [str(tmp_path), "feature"])

    assert res.exit_code == 5
    assert "config error" in res.stderr


def test_cli_happy_path_prints_final_review(
    tmp_path: Path, monkeypatch
) -> None:
    made: list[str] = []

    class FakeReviewer:
        def __init__(self, model: str) -> None:
            self.model = model

    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())
    monkeypatch.setattr(
        cli,
        "capture_diff",
        lambda repo, branch, base, max_bytes: DiffResult(
            base="main",
            branch=branch,
            diff="diff body",
            files_total=1,
            files_included=1,
            truncated=False,
            bytes_total=9,
        ),
    )

    def make_reviewer(model, providers, api_keys):
        made.append(model)
        return FakeReviewer(model)

    def run_council(reviewers, ctx, timeout, verbose):
        assert [r.model for r in reviewers] == ["model-a", "model-b"]
        assert ctx.render() == "<diff>\ndiff body\n</diff>"
        return CouncilOutcome(
            r1={
                "A": ("model-a", "review a"),
                "B": ("model-b", "review b"),
            }
        )

    def synthesize(chair, outcome, ctx, timeout):
        assert chair.model == "chair-model"
        assert set(outcome.r1) == {"A", "B"}
        return "final review"

    monkeypatch.setattr(cli, "make_reviewer", make_reviewer)
    monkeypatch.setattr(cli, "run_council", run_council)
    monkeypatch.setattr(cli, "synthesize", synthesize)

    res = runner.invoke(cli.app, [str(tmp_path), "feature"])

    assert res.exit_code == 0
    assert res.stdout == "final review\n"
    assert made == ["chair-model", "model-a", "model-b"]
