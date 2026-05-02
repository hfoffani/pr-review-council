from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from . import config as cfg
from .chairman import synthesize
from .context import DiffOnlyContext
from .council import run_council
from .git_ops import GitError, capture_diff
from .reviewers import make_reviewer

app = typer.Typer(add_completion=False)


@app.command()
def main(
    repo: Annotated[Path, typer.Argument(help="Path to local git repo")],
    branch: Annotated[str, typer.Argument(help="Branch to review")],
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
