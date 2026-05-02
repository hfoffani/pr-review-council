from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from . import config as cfg
from .chairman import synthesize
from .context import DiffOnlyContext
from .council import run_council
from .git_ops import GitError, capture_diff, current_branch
from .reviewers import make_reviewer, resolve_reviewer

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
Usage: prc review [repo] [branch] [OPTIONS]

Review a local git branch with the configured LLM council.

Options:
  --base BASE                 Override auto-detected base ref.
  --council MODEL[,MODEL...]  Override config council.
  --chairman MODEL            Override config chair.
  --chair-on-council          Include chair as a council member.
  --no-chair-on-council       Do not include chair as a council member.
  --config PATH               Explicit config file.
  --max-diff-bytes N          Truncation cap, default 600000.
  --timeout SECS              Per-call timeout, default 180.
  -v, --verbose               Progress to stderr.
"""


CONFIG_HELP = """\
Usage: prc config [OPTIONS]

Show active chair/council configuration and provider/API-key resolution.

Options:
  --edit                      Open the selected config file in $EDITOR.
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
    repo: Annotated[
        Path,
        typer.Argument(help="Path to local git repo"),
    ] = Path("."),
    branch: Annotated[
        Optional[str],
        typer.Argument(help="Branch to review; defaults to current branch"),
    ] = None,
    base: Annotated[
        Optional[str], typer.Option("--base", help="Override auto-detected base ref")
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
    config_path: Annotated[
        Optional[Path], typer.Option("--config", help="Explicit config path")
    ] = None,
    max_diff_bytes: Annotated[
        int, typer.Option("--max-diff-bytes", help="Truncation cap (chars)")
    ] = 600_000,
    timeout: Annotated[
        float, typer.Option("--timeout", help="Per-call timeout in seconds")
    ] = 180.0,
    verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False,
) -> None:
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

    repo = repo.resolve()
    if branch is None:
        try:
            branch = current_branch(repo)
        except GitError as e:
            print(f"prc: {e}", file=sys.stderr)
            raise typer.Exit(4)

    try:
        diff = capture_diff(
            repo, branch, base, max_bytes=max_diff_bytes
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

    try:
        chair = make_reviewer(chair_model, c.providers, c.api_keys)
        reviewers = []
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

    ctx = DiffOnlyContext(diff=diff.diff)
    outcome = run_council(
        reviewers, ctx, timeout=timeout, verbose=verbose
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

    try:
        final = synthesize(chair, outcome, ctx, timeout=timeout)
    except Exception as e:
        print(f"prc: chair failed: {e!r}", file=sys.stderr)
        raise typer.Exit(2)

    if verbose:
        print(f"prc: chair {chair_model} ok", file=sys.stderr)
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
