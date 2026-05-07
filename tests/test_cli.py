from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from prc import cli
from prc.council import CouncilOutcome
from prc.git_ops import DiffResult, GitError
from prc.pr_platforms.base import PullRequestMetadata


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

    res = runner.invoke(cli.app, ["review", str(tmp_path), "feature"])

    assert res.exit_code == 0
    assert "no changes" in res.stderr


def test_cli_git_error_maps_to_exit_4(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())

    def fail(*args, **kwargs):
        raise GitError("bad diff")

    monkeypatch.setattr(cli, "capture_diff", fail)

    res = runner.invoke(cli.app, ["review", str(tmp_path), "feature"])

    assert res.exit_code == 4
    assert "bad diff" in res.stderr


def test_cli_config_error_maps_to_exit_5(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        cli.cfg,
        "load",
        lambda explicit=None: (_ for _ in ()).throw(ValueError("bad config")),
    )

    res = runner.invoke(cli.app, ["review", str(tmp_path), "feature"])

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

    def run_council(reviewers, ctx, timeout, verbose, progress, prompts):
        assert [r.model for r in reviewers] == ["model-a", "model-b"]
        assert ctx.render() == "<diff>\ndiff body\n</diff>"
        assert progress is not None
        assert prompts.reviewer
        return CouncilOutcome(
            r1={
                "A": ("model-a", "review a"),
                "B": ("model-b", "review b"),
            }
        )

    def synthesize(chair, outcome, ctx, timeout, prompts):
        assert chair.model == "chair-model"
        assert set(outcome.r1) == {"A", "B"}
        assert prompts.chairman
        return "final review"

    monkeypatch.setattr(cli, "make_reviewer", make_reviewer)
    monkeypatch.setattr(cli, "run_council", run_council)
    monkeypatch.setattr(cli, "synthesize", synthesize)

    res = runner.invoke(cli.app, ["review", str(tmp_path), "feature"])

    assert res.exit_code == 0
    assert res.stdout == "final review\n"
    assert made == ["chair-model", "model-a", "model-b"]


def test_cli_disclose_appends_reviewer_identities(
    tmp_path: Path, monkeypatch
) -> None:
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
    monkeypatch.setattr(
        cli,
        "make_reviewer",
        lambda model, providers, api_keys: FakeReviewer(model),
    )
    monkeypatch.setattr(
        cli,
        "run_council",
        lambda reviewers, ctx, timeout, verbose, progress, prompts: CouncilOutcome(
            r1={
                "B": ("model-b", "review b"),
                "A": ("model-a", "review a"),
            }
        ),
    )

    def synthesize(chair, outcome, ctx, timeout, prompts):
        assert "model-a" not in outcome.r1["A"][1]
        assert "model-b" not in outcome.r1["B"][1]
        assert prompts.chairman
        return "final review"

    monkeypatch.setattr(cli, "synthesize", synthesize)

    res = runner.invoke(
        cli.app, ["review", str(tmp_path), "feature", "--disclose"]
    )

    assert res.exit_code == 0
    assert res.stdout == (
        "final review\n"
        "---\n\n"
        "Reviewer identities:\n"
        "- Reviewer A: model-a\n"
        "- Reviewer B: model-b\n"
    )


def test_cli_remote_pr_defaults_to_dry_run(monkeypatch) -> None:
    class FakePlatform:
        def fetch_diff(self, url, max_bytes):
            assert url == "https://github.com/hfoffani/pr-review-council/pull/33"
            return DiffResult(
                base="repo#base",
                branch="repo#33",
                diff="remote diff",
                files_total=1,
                files_included=1,
                truncated=False,
                bytes_total=11,
            )

        def fetch_metadata(self, url):
            assert url == "https://github.com/hfoffani/pr-review-council/pull/33"
            return PullRequestMetadata(
                title="Remote title",
                description="Remote description",
                url=url,
            )

        def post_comment(self, url, body):
            raise AssertionError("dry run should not post")

    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())
    monkeypatch.setattr(cli, "platform_for_url", lambda url: FakePlatform())
    monkeypatch.setattr(
        cli,
        "capture_diff",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("local git diff should not run")
        ),
    )
    monkeypatch.setattr(
        cli,
        "make_reviewer",
        lambda model, providers, api_keys: SimpleNamespace(model=model),
    )

    def run_council(reviewers, ctx, timeout, verbose, progress, prompts):
        assert ctx.render() == (
            "<pull_request>\n"
            "<title>Remote title</title>\n"
            "<description>\n"
            "Remote description\n"
            "</description>\n"
            "<url>https://github.com/hfoffani/pr-review-council/pull/33</url>\n"
            "</pull_request>\n\n"
            "<diff>\n"
            "remote diff\n"
            "</diff>"
        )
        return CouncilOutcome(
            r1={"A": ("model-a", "a"), "B": ("model-b", "b")}
        )

    monkeypatch.setattr(cli, "run_council", run_council)
    monkeypatch.setattr(cli, "synthesize", lambda *args, **kwargs: "remote final")

    res = runner.invoke(
        cli.app,
        ["review", "https://github.com/hfoffani/pr-review-council/pull/33"],
    )

    assert res.exit_code == 0
    assert res.stdout == "remote final\n"


def test_cli_remote_pr_post_suppresses_stdout(monkeypatch) -> None:
    posted: dict[str, str] = {}

    class FakePlatform:
        supports_posting = True

        def fetch_diff(self, url, max_bytes):
            return DiffResult(
                base="repo#base",
                branch="repo#33",
                diff="remote diff",
                files_total=1,
                files_included=1,
                truncated=False,
                bytes_total=11,
            )

        def fetch_metadata(self, url):
            return PullRequestMetadata(
                title="Remote title",
                description="Remote description",
                url=url,
            )

        def post_comment(self, url, body):
            posted["url"] = url
            posted["body"] = body

    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())
    monkeypatch.setattr(cli, "platform_for_url", lambda url: FakePlatform())
    monkeypatch.setattr(
        cli,
        "make_reviewer",
        lambda model, providers, api_keys: SimpleNamespace(model=model),
    )
    monkeypatch.setattr(
        cli,
        "run_council",
        lambda reviewers, ctx, timeout, verbose, progress, prompts: CouncilOutcome(
            r1={"A": ("model-a", "a"), "B": ("model-b", "b")}
        ),
    )
    monkeypatch.setattr(cli, "synthesize", lambda *args, **kwargs: "remote final")

    res = runner.invoke(
        cli.app,
        ["review", "https://github.com/hfoffani/pr-review-council/pull/33", "--post"],
    )

    assert res.exit_code == 0
    assert res.stdout == ""
    assert posted == {
        "url": "https://github.com/hfoffani/pr-review-council/pull/33",
        "body": "remote final",
    }


def test_cli_remote_pr_post_requires_platform_support(monkeypatch) -> None:
    class FakePlatform:
        supports_posting = False

        def fetch_diff(self, url, max_bytes):
            raise AssertionError("diff should not be fetched")

    monkeypatch.setattr(cli, "platform_for_url", lambda url: FakePlatform())
    monkeypatch.setattr(
        cli.cfg,
        "load",
        lambda explicit=None: (_ for _ in ()).throw(
            AssertionError("config should not be loaded")
        ),
    )

    res = runner.invoke(
        cli.app,
        ["review", "https://bitbucket.org/org/repo/pull-requests/1", "--post"],
    )

    assert res.exit_code == 4
    assert "--post is not supported" in res.stderr


def test_cli_platform_construction_not_implemented_is_reported(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "platform_for_url",
        lambda url: (_ for _ in ()).throw(
            NotImplementedError("custom host support is coming soon")
        ),
    )

    res = runner.invoke(
        cli.app,
        ["review", "https://github.com/hfoffani/pr-review-council/pull/33"],
    )

    assert res.exit_code == 4
    assert "custom host support is coming soon" in res.stderr


def test_review_diff_builds_reviewers_and_final(monkeypatch) -> None:
    class FakeReviewer:
        def __init__(self, model: str) -> None:
            self.model = model

    monkeypatch.setattr(
        cli,
        "make_reviewer",
        lambda model, providers, api_keys: FakeReviewer(model),
    )

    def run_council(reviewers, ctx, timeout, verbose, progress, prompts):
        assert [r.model for r in reviewers] == ["model-a", "model-b"]
        assert ctx.render() == "<diff>\ndiff body\n</diff>"
        return CouncilOutcome(
            r1={"A": ("model-a", "a"), "B": ("model-b", "b")}
        )

    monkeypatch.setattr(cli, "run_council", run_council)
    monkeypatch.setattr(cli, "synthesize", lambda *args, **kwargs: "final")

    final, outcome, chair_error = cli._review_diff(
        c=_config(),
        council_models=["model-a", "model-b"],
        chair_model="chair-model",
        on_council_flag=False,
        diff=DiffResult(
            base="main",
            branch="feature",
            diff="diff body",
            files_total=1,
            files_included=1,
            truncated=False,
            bytes_total=9,
        ),
        timeout=180,
        verbose=False,
        progress=lambda _: None,
    )

    assert final == "final"
    assert set(outcome.r1) == {"A", "B"}
    assert chair_error is None


def test_cli_remote_pr_rejects_branch_base_and_conflicting_modes() -> None:
    res = runner.invoke(
        cli.app,
        [
            "review",
            "https://github.com/hfoffani/pr-review-council/pull/33",
            "feature",
            "--base",
            "main",
        ],
    )

    assert res.exit_code == 2
    assert "do not support a branch argument" in res.stderr

    res = runner.invoke(
        cli.app,
        [
            "review",
            "https://github.com/hfoffani/pr-review-council/pull/33",
            "--base",
            "main",
        ],
    )

    assert res.exit_code == 2
    assert "do not support --base" in res.stderr

    res = runner.invoke(
        cli.app,
        [
            "review",
            "https://github.com/hfoffani/pr-review-council/pull/33",
            "--dry-run",
            "--post",
        ],
    )

    assert res.exit_code == 2
    assert "choose either --dry-run or --post" in res.stderr

    res = runner.invoke(
        cli.app,
        [
            "review",
            "https://github.com/hfoffani/pr-review-council/pull/33",
            "--post",
            "--dry-run",
        ],
    )

    assert res.exit_code == 2
    assert "choose either --dry-run or --post" in res.stderr


def test_cli_uses_custom_prompts_file(
    tmp_path: Path, monkeypatch
) -> None:
    prompts_path = tmp_path / "config/pr-review-council/prompts.toml"
    prompts_path.parent.mkdir(parents=True)
    prompts_path.write_text(
        '[reviewer]\nsystem = "custom reviewer"\n\n'
        '[cross_eval]\nsystem = "custom cross eval"\n\n'
        '[chairman]\nsystem = "custom chair"\n'
    )

    class FakeReviewer:
        def __init__(self, model: str) -> None:
            self.model = model

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
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
    monkeypatch.setattr(
        cli,
        "make_reviewer",
        lambda model, providers, api_keys: FakeReviewer(model),
    )

    def run_council(reviewers, ctx, timeout, verbose, progress, prompts):
        assert prompts.reviewer == "custom reviewer"
        assert prompts.cross_eval == "custom cross eval"
        return CouncilOutcome(
            r1={"A": ("model-a", "a"), "B": ("model-b", "b")}
        )

    def synthesize(chair, outcome, ctx, timeout, prompts):
        assert prompts.chairman == "custom chair"
        return "final"

    monkeypatch.setattr(cli, "run_council", run_council)
    monkeypatch.setattr(cli, "synthesize", synthesize)

    res = runner.invoke(cli.app, ["review", str(tmp_path), "feature"])

    assert res.exit_code == 0
    assert res.stdout == "final\n"


def test_cli_bad_prompts_file_exits_5(
    tmp_path: Path, monkeypatch
) -> None:
    prompts_path = tmp_path / "config/pr-review-council/prompts.toml"
    prompts_path.parent.mkdir(parents=True)
    prompts_path.write_text("[reviewer]\nsystem = []\n")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
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
    monkeypatch.setattr(
        cli,
        "make_reviewer",
        lambda model, providers, api_keys: SimpleNamespace(model=model),
    )
    monkeypatch.setattr(
        cli,
        "run_council",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("council should not run")
        ),
    )

    res = runner.invoke(cli.app, ["review", str(tmp_path), "feature"])

    assert res.exit_code == 5
    assert "prompts.toml" in res.stderr
    assert "system" in res.stderr


def test_cli_progress_wraps_llm_work(
    tmp_path: Path, monkeypatch
) -> None:
    events: list[str] = []

    class FakeReviewer:
        def __init__(self, model: str) -> None:
            self.model = model

    @contextmanager
    def fake_progress(*, enabled: bool) -> Iterator[Callable[[str], None]]:
        assert enabled is True
        events.append("open")

        def update(message: str) -> None:
            events.append(message)

        try:
            yield update
        finally:
            events.append("closed")

    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())
    monkeypatch.setattr(cli, "_review_progress", fake_progress)
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
    monkeypatch.setattr(
        cli,
        "make_reviewer",
        lambda model, providers, api_keys: FakeReviewer(model),
    )
    monkeypatch.setattr(
        cli,
        "run_council",
        lambda reviewers, ctx, timeout, verbose, progress, prompts: (
            progress("r1"),
            progress("r2"),
            CouncilOutcome(
                r1={"A": ("model-a", "a"), "B": ("model-b", "b")}
            ),
        )[-1],
    )
    monkeypatch.setattr(cli, "synthesize", lambda *args, **kwargs: "final")

    res = runner.invoke(cli.app, ["review", str(tmp_path), "feature"])

    assert res.exit_code == 0
    assert res.stdout == "final\n"
    assert events == [
        "open",
        cli.PROGRESS_DIFF,
        cli.PROGRESS_COUNCIL_START,
        cli.PROGRESS_R1,
        cli.PROGRESS_R2,
        cli.PROGRESS_CHAIR,
        "closed",
    ]


def test_cli_progress_closes_before_council_collapse(
    tmp_path: Path, monkeypatch
) -> None:
    events: list[str] = []

    @contextmanager
    def fake_progress(*, enabled: bool) -> Iterator[Callable[[str], None]]:
        assert enabled is True
        events.append("open")

        def update(message: str) -> None:
            events.append(message)

        try:
            yield update
        finally:
            events.append("closed")

    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())
    monkeypatch.setattr(cli, "_review_progress", fake_progress)
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
    monkeypatch.setattr(
        cli,
        "make_reviewer",
        lambda model, providers, api_keys: SimpleNamespace(model=model),
    )
    monkeypatch.setattr(
        cli,
        "run_council",
        lambda reviewers, ctx, timeout, verbose, progress, prompts: (
            progress("r1"),
            CouncilOutcome(r1={"A": ("model-a", "a")}),
        )[-1],
    )
    monkeypatch.setattr(
        cli,
        "synthesize",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("chair should not run")
        ),
    )

    res = runner.invoke(cli.app, ["review", str(tmp_path), "feature"])

    assert res.exit_code == 3
    assert "council collapsed" in res.stderr
    assert events == ["open", cli.PROGRESS_DIFF, cli.PROGRESS_COUNCIL_START, cli.PROGRESS_R1, "closed"]


def test_review_progress_disabled_when_stderr_is_not_terminal(
    monkeypatch,
) -> None:
    class FakeConsole:
        is_terminal = False

        def __init__(self, *, stderr: bool) -> None:
            assert stderr is True

    def fail_progress(*args, **kwargs):
        raise AssertionError("progress renderer should not start")

    monkeypatch.setattr(cli, "Console", FakeConsole)
    monkeypatch.setattr(cli, "Progress", fail_progress)

    with cli._review_progress(enabled=True) as progress:
        progress("ignored")


def test_cli_without_subcommand_lists_commands() -> None:
    res = runner.invoke(cli.app, [])

    assert res.exit_code == 0
    assert "review" in res.stdout
    assert "config" in res.stdout
    assert "help" in res.stdout
    assert "uv tool upgrade pr-review-council" in res.stdout
    assert "uv tool uninstall pr-review-council" in res.stdout


def test_review_defaults_to_current_repo_and_branch(monkeypatch) -> None:
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
        lambda reviewers, ctx, timeout, verbose, progress, prompts: CouncilOutcome(
            r1={"A": ("model-a", "a"), "B": ("model-b", "b")}
        ),
    )
    monkeypatch.setattr(cli, "synthesize", lambda *args, **kwargs: "final")

    res = runner.invoke(cli.app, ["review"])

    assert res.exit_code == 0
    assert seen["repo"] == Path(".").resolve()
    assert seen["branch"] == "current-branch"


def test_config_resolves_active_members(monkeypatch) -> None:
    from prc.reviewers import _registry

    saved = dict(_registry._FAMILIES)
    _registry._FAMILIES["fake"] = object  # type: ignore[assignment]
    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())

    try:
        res = runner.invoke(cli.app, ["config"])
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


def test_config_reports_env_key_source(monkeypatch) -> None:
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
        res = runner.invoke(cli.app, ["config"])
    finally:
        _registry._FAMILIES.clear()
        _registry._FAMILIES.update(saved)

    assert res.exit_code == 0
    assert "api_key: set (env:ANTHROPIC_API_KEY)" in res.stdout


def test_config_edit_uses_editor(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())
    monkeypatch.setenv("EDITOR", "editor --wait")
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda cmd, check: calls.append(cmd),
    )

    res = runner.invoke(cli.app, ["config", "--edit"])

    assert res.exit_code == 0
    assert calls == [["editor", "--wait", "/tmp/prc.toml"]]


def test_config_edit_prompts_creates_and_opens_file(
    tmp_path: Path, monkeypatch
) -> None:
    config_home = tmp_path / "config"
    prompts_path = config_home / "pr-review-council/prompts.toml"
    calls: list[list[str]] = []

    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("EDITOR", "editor --wait")
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda cmd, check: calls.append(cmd),
    )
    monkeypatch.setattr(
        cli.cfg,
        "load",
        lambda explicit=None: (_ for _ in ()).throw(
            AssertionError("config should not load")
        ),
    )

    res = runner.invoke(cli.app, ["config", "--edit-prompts"])

    assert res.exit_code == 0
    assert calls == [["editor", "--wait", str(prompts_path)]]
    assert "[reviewer]" in prompts_path.read_text()
    assert "[cross_eval]" in prompts_path.read_text()
    assert "[chairman]" in prompts_path.read_text()


def test_config_edit_requires_editor(monkeypatch) -> None:
    monkeypatch.setattr(cli.cfg, "load", lambda explicit=None: _config())
    monkeypatch.delenv("EDITOR", raising=False)

    res = runner.invoke(cli.app, ["config", "--edit"])

    assert res.exit_code == 5
    assert "EDITOR is not set" in res.stderr


def test_help_review_shows_options() -> None:
    res = runner.invoke(cli.app, ["help", "review"])

    assert res.exit_code == 0
    assert "Usage: prc review" in res.stdout
    assert "--base BASE" in res.stdout
    assert "--disclose" in res.stdout
    assert "--timeout SECS" in res.stdout


def test_help_config_shows_options() -> None:
    res = runner.invoke(cli.app, ["help", "config"])

    assert res.exit_code == 0
    assert "Usage: prc config" in res.stdout
    assert "--edit" in res.stdout
    assert "--edit-prompts" in res.stdout
    assert "--config PATH" in res.stdout
