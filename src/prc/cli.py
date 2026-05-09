from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import click
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from . import config as cfg
from . import prompts as prompt_cfg
from .chairman import synthesize
from .context import DiffOnlyContext, PullRequestContext
from .council import CouncilOutcome, CouncilPhase, run_council
from .git_ops import DiffResult, GitError, capture_diff, current_branch
from .pr_platforms import (
    PRPlatformError,
    PullRequestMetadata,
    UnsupportedPRHost,
    is_pr_url,
    platform_for_url,
)
from .reviewers import Reviewer, make_reviewer, resolve_reviewer

app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
)


SUBCOMMANDS = {
    "review": "Review the current repo/branch with the configured council.",
    "config": "Show configuration, provider routing, and API-key presence.",
    "help": "Show help for a subcommand.",
}


REVIEW_HELP = """\
Usage: prc review [repo|pr-url] [branch] [OPTIONS]

Review a local git branch or remote pull request URL with the configured LLM council.

Options:
  --base BASE                 Target branch/ref to compare against.
  --council MODEL[,MODEL...]  Override config council.
  --chairman MODEL            Override config chair.
  --chair-on-council          Include chair as a council member.
  --no-chair-on-council       Do not include chair as a council member.
  --dry-run                   Show review output without posting; default.
  --post                      Post review as a PR comment; requires a supported PR URL.
  --disclose                  Append reviewer letter -> model name mapping.
  --include-dirty             Include local dirty changes; local repos only.
  --config PATH               Explicit config file.
  --max-diff-bytes N          Truncation cap, default 600000.
  --timeout SECS              Per-model API call timeout in seconds, default 180.
  -v, --verbose               Detailed progress to stderr.
"""


CONFIG_HELP = """\
Usage: prc config [OPTIONS]

Show active chair/council configuration and provider/API-key resolution.

Options:
  --edit                      Open the selected config file in $EDITOR.
  --edit-prompts              Create/open custom prompt overrides in $EDITOR.
  --config PATH               Explicit config file.
  --council MODEL[,MODEL...]  Override config council for display.
  --chairman MODEL            Override config chair for display.
  --chair-on-council          Include chair in displayed council.
  --no-chair-on-council       Do not include chair in displayed council.
"""


@app.callback()
def root(
    ctx: typer.Context,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    _print_subcommands()
    raise typer.Exit(0)


@app.command("review", help=SUBCOMMANDS["review"])
def review(
    ctx: typer.Context,
    repo: Annotated[
        str,
        typer.Argument(help="Path to local git repo or pull request URL"),
    ] = ".",
    branch: Annotated[
        Optional[str],
        typer.Argument(help="Branch to review; defaults to current branch"),
    ] = None,
    base: Annotated[
        Optional[str],
        typer.Option("--base", help="Target branch/ref to compare against"),
    ] = None,
    council: Annotated[
        Optional[str],
        typer.Option(
            "--council", help="Comma-separated council models (overrides config)"
        ),
    ] = None,
    chairman: Annotated[
        Optional[str],
        typer.Option("--chairman", help="Chair model (overrides config)"),
    ] = None,
    chair_on_council: Annotated[
        bool,
        typer.Option(
            "--chair-on-council/--no-chair-on-council",
            help="Include chair as a council member; chair's R1 review is reused",
        ),
    ] = False,
    disclose: Annotated[
        bool,
        typer.Option(
            "--disclose",
            help="Append reviewer letter to model name mapping to final output",
        ),
    ] = False,
    include_dirty: Annotated[
        bool,
        typer.Option(
            "--include-dirty",
            help=(
                "Include local staged, unstaged, and untracked changes; "
                "local repository reviews only"
            ),
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show review output without posting; default for PR URLs",
        ),
    ] = True,
    post: Annotated[
        bool,
        typer.Option(
            "--post",
            help="Post review as a PR comment without printing it",
        ),
    ] = False,
    config_path: Annotated[
        Optional[Path], typer.Option("--config", help="Explicit config path")
    ] = None,
    max_diff_bytes: Annotated[
        int, typer.Option("--max-diff-bytes", help="Truncation cap (chars)")
    ] = 600_000,
    timeout: Annotated[
        float,
        typer.Option(
            "--timeout", help="Per-model API call timeout in seconds"
        ),
    ] = 180.0,
    verbose: Annotated[
        bool,
        typer.Option("-v", "--verbose", help="Detailed progress to stderr"),
    ] = False,
) -> None:
    dry_run_explicit = (
        ctx.get_parameter_source("dry_run")
        == click.core.ParameterSource.COMMANDLINE
    )
    if dry_run_explicit and dry_run and post:
        print(
            "prc: choose either --dry-run or --post, not both",
            file=sys.stderr,
        )
        raise typer.Exit(2)

    remote_url = repo if is_pr_url(repo) else None
    if remote_url is not None and branch is not None:
        print(
            "prc: PR URL reviews do not support a branch argument",
            file=sys.stderr,
        )
        raise typer.Exit(2)
    if remote_url is not None and base is not None:
        print("prc: PR URL reviews do not support --base", file=sys.stderr)
        raise typer.Exit(2)
    if remote_url is not None and include_dirty:
        print(
            "prc: PR URL reviews do not support --include-dirty",
            file=sys.stderr,
        )
        raise typer.Exit(2)
    if remote_url is None and post:
        print("prc: --post requires a pull request URL", file=sys.stderr)
        raise typer.Exit(2)
    dry_run_mode = dry_run and not post

    platform = None
    if remote_url is not None:
        try:
            platform = platform_for_url(remote_url)
            if post and not platform.supports_posting:
                print(
                    "prc: --post is not supported for this pull request host",
                    file=sys.stderr,
                )
                raise typer.Exit(4)
        except UnsupportedPRHost as e:
            print(f"prc: {e}", file=sys.stderr)
            raise typer.Exit(4)
        except NotImplementedError as e:
            print(f"prc: {e}", file=sys.stderr)
            raise typer.Exit(4)

    try:
        c = cfg.load(explicit=config_path)
    except cfg.ConfigMissing as e:
        print(
            f"prc: created default config at {e.created_at}",
            file=sys.stderr,
        )
        print(
            "prc: edit it to add API keys, then rerun", file=sys.stderr
        )
        raise typer.Exit(5)
    except (FileNotFoundError, ValueError) as e:
        print(f"prc: config error: {e}", file=sys.stderr)
        raise typer.Exit(5)

    council_models = (
        [m.strip() for m in council.split(",") if m.strip()]
        if council
        else list(c.council)
    )
    chair_model = chairman or c.chair_model
    on_council_flag = chair_on_council or c.chair_on_council

    final: str | None = None
    metadata: PullRequestMetadata | None = None

    with _review_progress(enabled=not verbose) as progress:
        progress(PROGRESS_DIFF)

        if remote_url is not None:
            if platform is None:
                print("prc: unsupported PR platform", file=sys.stderr)
                raise typer.Exit(4)
            try:
                diff = platform.fetch_diff(remote_url, max_bytes=max_diff_bytes)
            except NotImplementedError as e:
                print(f"prc: {e}", file=sys.stderr)
                raise typer.Exit(4)
            except PRPlatformError as e:
                print(f"prc: {e}", file=sys.stderr)
                raise typer.Exit(4)
            try:
                metadata = platform.fetch_metadata(remote_url)
            except NotImplementedError as e:
                print(f"prc: {e}", file=sys.stderr)
                raise typer.Exit(4)
            except PRPlatformError as e:
                print(f"prc: {e}", file=sys.stderr)
                raise typer.Exit(4)
        else:
            repo_path = Path(repo).resolve()
            if branch is None:
                try:
                    branch = current_branch(repo_path)
                except GitError as e:
                    print(f"prc: {e}", file=sys.stderr)
                    raise typer.Exit(4)

            try:
                diff = capture_diff(
                    repo_path,
                    branch,
                    base,
                    include_dirty=include_dirty,
                    max_bytes=max_diff_bytes,
                )
            except GitError as e:
                print(f"prc: {e}", file=sys.stderr)
                raise typer.Exit(4)

        if verbose:
            print(
                f"prc: base={diff.base} branch={diff.branch} "
                f"files={diff.files_total} bytes={diff.bytes_total}",
                file=sys.stderr,
            )
        if diff.truncated:
            print(
                f"prc: warning: diff truncated, "
                f"{diff.files_included}/{diff.files_total} files included",
                file=sys.stderr,
            )
        if not diff.diff:
            print(
                "prc: no changes between base and branch; nothing to review",
                file=sys.stderr,
            )
            raise typer.Exit(0)

        final, outcome, chair_error = _review_diff(
            c=c,
            council_models=council_models,
            chair_model=chair_model,
            on_council_flag=on_council_flag,
            diff=diff,
            metadata=metadata,
            timeout=timeout,
            verbose=verbose,
            progress=progress,
        )

        if len(outcome.r1) < 2:
            print(
                f"prc: council collapsed (only {len(outcome.r1)} R1 reviews); "
                "aborting",
                file=sys.stderr,
            )
            for letter, why in outcome.failures.items():
                print(f"prc:   {letter}: {why}", file=sys.stderr)
            raise typer.Exit(3)

        if chair_error is not None:
            print(
                f"prc: chair failed: {_format_exception(chair_error)}",
                file=sys.stderr,
            )
            raise typer.Exit(2)

        if final is None:
            print("prc: chair failed: no verdict produced", file=sys.stderr)
            raise typer.Exit(2)

        if verbose:
            print(f"prc: chair {chair_model} ok", file=sys.stderr)
        if disclose:
            final = _append_reviewer_identities(final, outcome)
        if post:
            if remote_url is None or platform is None:
                print("prc: --post requires a supported pull request URL", file=sys.stderr)
                raise typer.Exit(2)
            progress(PROGRESS_POST)
            try:
                platform.post_comment(remote_url, final)
            except NotImplementedError as e:
                print(f"prc: {e}", file=sys.stderr)
                raise typer.Exit(4)
            except PRPlatformError as e:
                print(f"prc: {e}", file=sys.stderr)
                raise typer.Exit(4)
            if verbose:
                print("prc: review comment posted", file=sys.stderr)

    if dry_run_mode and final is not None:
        print(final)


@app.command("config", help=SUBCOMMANDS["config"])
def config_command(
    config_path: Annotated[
        Optional[Path], typer.Option("--config", help="Explicit config path")
    ] = None,
    edit: Annotated[
        bool,
        typer.Option("--edit", help="Open the selected config file in $EDITOR"),
    ] = False,
    edit_prompts: Annotated[
        bool,
        typer.Option(
            "--edit-prompts",
            help="Create/open custom prompt overrides in $EDITOR",
        ),
    ] = False,
    council: Annotated[
        Optional[str],
        typer.Option(
            "--council", help="Comma-separated council models (overrides config)"
        ),
    ] = None,
    chairman: Annotated[
        Optional[str],
        typer.Option("--chairman", help="Chair model (overrides config)"),
    ] = None,
    chair_on_council: Annotated[
        bool,
        typer.Option(
            "--chair-on-council/--no-chair-on-council",
            help="Include chair as a council member",
        ),
    ] = False,
) -> None:
    if edit_prompts:
        _edit_config(prompt_cfg.create_default_prompts())
        raise typer.Exit(0)

    try:
        c = cfg.load(explicit=config_path)
    except cfg.ConfigMissing as e:
        if edit:
            _edit_config(e.created_at)
            raise typer.Exit(0)
        print(
            f"prc: created default config at {e.created_at}",
            file=sys.stderr,
        )
        print(
            "prc: edit it to add API keys, then rerun", file=sys.stderr
        )
        raise typer.Exit(5)
    except (FileNotFoundError, ValueError) as e:
        print(f"prc: config error: {e}", file=sys.stderr)
        raise typer.Exit(5)

    if edit:
        _edit_config(c.source)
        raise typer.Exit(0)

    council_models = (
        [m.strip() for m in council.split(",") if m.strip()]
        if council
        else list(c.council)
    )
    chair_model = chairman or c.chair_model
    on_council_flag = chair_on_council or c.chair_on_council
    try:
        _print_config(c, council_models, chair_model, on_council_flag)
    except (ValueError, RuntimeError) as e:
        print(f"prc: {e}", file=sys.stderr)
        raise typer.Exit(5)


@app.command("help", help=SUBCOMMANDS["help"])
def help_command(
    topic: Annotated[
        Optional[str],
        typer.Argument(help="Subcommand to show help for"),
    ] = None,
) -> None:
    if topic is None:
        _print_subcommands()
        return
    if topic == "review":
        print(REVIEW_HELP)
        return
    if topic == "config":
        print(CONFIG_HELP)
        return
    if topic == "help":
        print("Usage: prc help [review|config]\n\nShow help for a subcommand.")
        return
    print(f"prc: unknown help topic {topic!r}", file=sys.stderr)
    raise typer.Exit(2)


def _print_subcommands() -> None:
    print("Commands:")
    for name, description in SUBCOMMANDS.items():
        print(f"  {name:<8} {description}")
    print()
    print("Installed with uv?")
    print("  Upgrade:   uv tool upgrade pr-review-council")
    print("  Uninstall: uv tool uninstall pr-review-council")


PROGRESS_DIFF = "prc: fetching diff..."
PROGRESS_COUNCIL_START = "prc: council starting..."
PROGRESS_R1 = "prc: council reviewing diff..."
PROGRESS_R2 = "prc: council reviewing reviewers..."
PROGRESS_CHAIR = "prc: chair writing verdict..."
PROGRESS_POST = "prc: posting review comment..."


def _review_diff(
    *,
    c: cfg.Config,
    council_models: list[str],
    chair_model: str,
    on_council_flag: bool,
    diff: DiffResult,
    timeout: float,
    verbose: bool,
    progress: Callable[[str], None],
    metadata: PullRequestMetadata | None = None,
) -> tuple[str | None, CouncilOutcome, BaseException | None]:
    try:
        chair = make_reviewer(chair_model, c.providers, c.api_keys)
        reviewers: list[Reviewer] = []
        chair_seat_taken = False
        for m in council_models:
            if (
                on_council_flag
                and m == chair_model
                and not chair_seat_taken
            ):
                reviewers.append(chair)
                chair_seat_taken = True
            else:
                reviewers.append(make_reviewer(m, c.providers, c.api_keys))
        if on_council_flag and not chair_seat_taken:
            reviewers.append(chair)
    except (ValueError, RuntimeError) as e:
        print(f"prc: {e}", file=sys.stderr)
        raise typer.Exit(5)

    if verbose:
        print(
            f"prc: chair={chair_model} council=["
            f"{', '.join(r.model for r in reviewers)}]",
            file=sys.stderr,
        )

    try:
        prompts = prompt_cfg.load_prompts()
    except ValueError as e:
        print(f"prc: config error: {e}", file=sys.stderr)
        raise typer.Exit(5)

    ctx = (
        PullRequestContext(diff=diff.diff, metadata=metadata)
        if metadata is not None
        else DiffOnlyContext(diff=diff.diff)
    )
    final: str | None = None
    chair_error: BaseException | None = None
    progress(PROGRESS_COUNCIL_START)
    outcome = run_council(
        reviewers,
        ctx,
        timeout=timeout,
        verbose=verbose,
        progress=_council_progress(progress),
        prompts=prompts,
    )

    if len(outcome.r1) >= 2:
        progress(PROGRESS_CHAIR)
        try:
            final = synthesize(
                chair, outcome, ctx, timeout=timeout, prompts=prompts
            )
        except Exception as e:
            chair_error = e

    return final, outcome, chair_error


@contextmanager
def _review_progress(
    *, enabled: bool
) -> Iterator[Callable[[str], None]]:
    def noop(_message: str) -> None:
        return

    if not enabled:
        yield noop
        return

    console = Console(stderr=True)
    if not console.is_terminal:
        yield noop
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        console=console,
        transient=True,
        redirect_stdout=False,
        redirect_stderr=False,
    ) as progress:
        task_id = progress.add_task(PROGRESS_COUNCIL_START, total=None)

        def update(message: str) -> None:
            progress.update(task_id, description=message)

        yield update


def _council_progress(
    progress: Callable[[str], None]
) -> Callable[[CouncilPhase], None]:
    def update(phase: CouncilPhase) -> None:
        if phase == "r1":
            progress(PROGRESS_R1)
        elif phase == "r2":
            progress(PROGRESS_R2)

    return update


def _format_exception(error: BaseException) -> str:
    return repr(error)


def _append_reviewer_identities(
    final: str, outcome: CouncilOutcome
) -> str:
    lines = [
        "",
        "---",
        "",
        "Reviewer identities:",
    ]
    lines.extend(
        f"- Reviewer {letter}: {model}"
        for letter, (model, _review) in sorted(outcome.r1.items())
    )
    return final.rstrip() + "\n".join(lines)


def _print_config(
    c: cfg.Config,
    council_models: list[str],
    chair_model: str,
    chair_on_council: bool,
) -> None:
    print(f"config: {c.source}")
    print(f"chair: {chair_model}")
    _print_resolution(chair_model, c, role="chair")
    print("council:")
    active = list(council_models)
    if chair_on_council and chair_model not in active:
        active.append(chair_model)
    for idx, model in enumerate(active, start=1):
        role = "council"
        if chair_on_council and model == chair_model:
            role = "chair+council"
        print(f"  {idx}. {model}")
        _print_resolution(model, c, role=role, indent="     ")
    print(
        "api-key validation: resolved provider/key presence only; no network "
        "request was made."
    )


def _print_resolution(
    model: str,
    c: cfg.Config,
    *,
    role: str,
    indent: str = "  ",
) -> None:
    resolved = resolve_reviewer(model, c.providers, c.api_keys)
    print(
        f"{indent}{role}: provider={resolved.provider} "
        f"family={resolved.family} api_model={resolved.api_model}"
    )
    if resolved.api_key is None:
        print(f"{indent}api_key: not required")
    else:
        print(f"{indent}api_key: set ({resolved.api_key_source})")


def _edit_config(path: Path) -> None:
    editor = os.environ.get("EDITOR")
    if not editor:
        print("prc: EDITOR is not set", file=sys.stderr)
        raise typer.Exit(5)
    try:
        subprocess.run([*shlex.split(editor), str(path)], check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"prc: editor failed: {e}", file=sys.stderr)
        raise typer.Exit(5)
