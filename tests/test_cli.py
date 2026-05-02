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
        providers={
            "fake": {
                "family": "fake",
                "api_key": "${api_keys.fake}",
                "match": ["model-*", "chair-*"],
            }
        },
        api_keys={"fake": "fake-key"},
        source=Path("/tmp/prc.toml"),
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


def test_cli_defaults_to_current_repo_and_branch(monkeypatch) -> None:
    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())
    monkeypatch.setattr(cli, "current_branch", lambda repo: "current-branch")
    seen: dict[str, object] = {}

    def capture_diff(repo, branch, base, max_bytes):
        seen["repo"] = repo
        seen["branch"] = branch
        return DiffResult(
            base="main",
            branch=branch,
            diff="diff body",
            files_total=1,
            files_included=1,
            truncated=False,
            bytes_total=9,
        )

    monkeypatch.setattr(cli, "capture_diff", capture_diff)
    monkeypatch.setattr(
        cli,
        "make_reviewer",
        lambda model, providers, api_keys: SimpleNamespace(model=model),
    )
    monkeypatch.setattr(
        cli,
        "run_council",
        lambda reviewers, ctx, timeout, verbose: CouncilOutcome(
            r1={"A": ("model-a", "a"), "B": ("model-b", "b")}
        ),
    )
    monkeypatch.setattr(cli, "synthesize", lambda *args, **kwargs: "final")

    res = runner.invoke(cli.app, [])

    assert res.exit_code == 0
    assert seen["repo"] == Path(".").resolve()
    assert seen["branch"] == "current-branch"


def test_cli_print_config_resolves_active_members(monkeypatch) -> None:
    from prc.reviewers import _registry

    saved = dict(_registry._FAMILIES)
    _registry._FAMILIES["fake"] = object  # type: ignore[assignment]
    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())

    try:
        res = runner.invoke(cli.app, ["--print-config"])
    finally:
        _registry._FAMILIES.clear()
        _registry._FAMILIES.update(saved)

    assert res.exit_code == 0
    assert "chair: chair-model" in res.stdout
    assert "1. model-a" in res.stdout
    assert "2. model-b" in res.stdout
    assert "provider=fake" in res.stdout
    assert "api_key: set (config)" in res.stdout
    assert "no network request was made" in res.stdout


def test_cli_print_config_reports_env_key_source(monkeypatch) -> None:
    from prc.reviewers import _registry

    config = _config()
    config.providers = {
        "anthropic": {
            "family": "fake",
            "api_key": "${api_keys.anthropic}",
            "match": ["model-*", "chair-*"],
        }
    }
    config.api_keys = {}
    saved = dict(_registry._FAMILIES)
    _registry._FAMILIES["fake"] = object  # type: ignore[assignment]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: config)

    try:
        res = runner.invoke(cli.app, ["--print-config"])
    finally:
        _registry._FAMILIES.clear()
        _registry._FAMILIES.update(saved)

    assert res.exit_code == 0
    assert "api_key: set (env:ANTHROPIC_API_KEY)" in res.stdout


def test_cli_edit_config_uses_editor(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())
    monkeypatch.setenv("EDITOR", "editor --wait")
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda cmd, check: calls.append(cmd),
    )

    res = runner.invoke(cli.app, ["--edit-config"])

    assert res.exit_code == 0
    assert calls == [["editor", "--wait", "/tmp/prc.toml"]]


def test_cli_edit_config_requires_editor(monkeypatch) -> None:
    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())
    monkeypatch.delenv("EDITOR", raising=False)

    res = runner.invoke(cli.app, ["--edit-config"])

    assert res.exit_code == 5
    assert "EDITOR is not set" in res.stderr
