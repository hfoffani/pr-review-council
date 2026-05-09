from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    pass


@dataclass
class DiffResult:
    base: str
    branch: str
    diff: str
    files_total: int
    files_included: int
    truncated: bool
    bytes_total: int


BASE_CANDIDATES = (
    "origin/main",
    "main",
    "origin/develop",
    "develop",
    "origin/master",
    "master",
)


def _run(cmd: list[str], cwd: Path) -> str:
    res = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if res.returncode != 0:
        raise GitError(
            f"git failed: {' '.join(cmd)}\n{res.stderr.strip()}"
        )
    return res.stdout


def repo_root(path: Path) -> Path:
    """Return the git repo root for any path inside a repository."""
    if not path.exists():
        raise GitError(f"{path} does not exist")
    try:
        out = _run(["git", "rev-parse", "--show-toplevel"], path)
    except GitError as e:
        raise GitError(f"{path} is not a git repository") from e
    top = out.strip()
    if not top:
        raise GitError(f"{path} is not a git repository")
    return Path(top)


def detect_base(repo: Path, branch: str) -> str:
    """Return the likely target ref for a two-dot review diff."""
    scores: list[tuple[int, int, int, int, str]] = []
    branch_commit = _run(["git", "rev-parse", "--verify", branch], repo).strip()

    for idx, candidate in enumerate(BASE_CANDIDATES):
        try:
            candidate_commit = _run(
                ["git", "rev-parse", "--verify", candidate], repo
            ).strip()
            if candidate_commit == branch_commit:
                continue
            numstat = _run(
                [
                    "git",
                    "diff",
                    "--numstat",
                    "--no-renames",
                    f"{candidate}..{branch}",
                ],
                repo,
            )
        except GitError:
            continue

        files_changed, binary_files_changed, lines_changed = _numstat_score(
            numstat
        )
        scores.append(
            (files_changed, binary_files_changed, lines_changed, idx, candidate)
        )

    if scores:
        return min(scores)[4]

    raise GitError(
        f"could not detect base ref for branch {branch!r}; "
        "pass --base explicitly"
    )


def _numstat_score(numstat: str) -> tuple[int, int, int]:
    files_changed = 0
    binary_files_changed = 0
    lines_changed = 0
    for line in numstat.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            raise GitError(f"malformed git numstat line: {line!r}")
        files_changed += 1
        added, deleted, *_rest = parts
        if added == "-" or deleted == "-":
            binary_files_changed += 1
            continue
        try:
            lines_changed += int(added) + int(deleted)
        except ValueError as e:
            raise GitError(f"malformed git numstat line: {line!r}") from e
    return files_changed, binary_files_changed, lines_changed


def current_branch(repo: Path) -> str:
    repo = repo_root(repo)
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo).strip()
    if not branch or branch == "HEAD":
        raise GitError(
            f"{repo} is in detached HEAD state; pass the branch explicitly"
        )
    return branch


def capture_diff(
    repo: Path,
    branch: str,
    base: str | None = None,
    *,
    max_bytes: int = 600_000,
) -> DiffResult:
    repo = repo_root(repo)
    base_ref = base or detect_base(repo, branch)
    diff_range = f"{base_ref}..{branch}"
    diff = _run(["git", "diff", diff_range], repo)
    bytes_total = len(diff.encode("utf-8"))

    if bytes_total == 0:
        return DiffResult(
            base=base_ref,
            branch=branch,
            diff="",
            files_total=0,
            files_included=0,
            truncated=False,
            bytes_total=0,
        )

    if bytes_total > max_bytes * 5:
        raise GitError(
            f"diff is {bytes_total} bytes (>5x cap of {max_bytes}); "
            "likely contains generated/lock files. Filter via "
            ".gitattributes or split this branch."
        )

    numstat = _run(
        ["git", "diff", "--numstat", "--no-renames", diff_range],
        repo,
    )
    paths = [
        ln.split("\t", 2)[-1].strip()
        for ln in numstat.splitlines()
        if ln.strip()
    ]
    files_total = len(paths)

    if bytes_total <= max_bytes:
        return DiffResult(
            base=base_ref,
            branch=branch,
            diff=diff,
            files_total=files_total,
            files_included=files_total,
            truncated=False,
            bytes_total=bytes_total,
        )

    included: list[str] = []
    chunks: list[str] = []
    used = 0
    for p in paths:
        per_file = _run(
            ["git", "diff", "--no-renames", diff_range, "--", p],
            repo,
        )
        sz = len(per_file.encode("utf-8"))
        if used + sz > max_bytes:
            if not included:
                raise GitError(
                    f"first changed file {p!r} is {sz} bytes, which exceeds "
                    f"the diff cap of {max_bytes}; raise --max-diff-bytes, "
                    "filter generated files, or split this branch."
                )
            break
        chunks.append(per_file)
        included.append(p)
        used += sz
    included_set = set(included)
    omitted = [p for p in paths if p not in included_set]
    footer = (
        f"\n\nTRUNCATED: {len(included)}/{files_total} files included. "
        f"Omitted: {', '.join(omitted)}\n"
    )
    return DiffResult(
        base=base_ref,
        branch=branch,
        diff="".join(chunks) + footer,
        files_total=files_total,
        files_included=len(included),
        truncated=True,
        bytes_total=bytes_total,
    )
