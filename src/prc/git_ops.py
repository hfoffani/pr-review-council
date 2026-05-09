from __future__ import annotations

import os
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


@dataclass
class _DiffFile:
    path: str
    diff: str


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


def _run_diff(cmd: list[str], cwd: Path) -> str:
    res = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if res.returncode not in {0, 1}:
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


def detect_base(
    repo: Path, branch: str, *, allow_same_commit: bool = False
) -> str:
    """Return the likely target ref for a two-dot review diff."""
    scores: list[tuple[int, int, int, int, str]] = []
    branch_commit = _run(["git", "rev-parse", "--verify", branch], repo).strip()

    for idx, candidate in enumerate(BASE_CANDIDATES):
        try:
            candidate_commit = _run(
                ["git", "rev-parse", "--verify", candidate], repo
            ).strip()
            if candidate_commit == branch_commit and not allow_same_commit:
                continue
            numstat = _run(
                [
                    "git",
                    "diff",
                    "--numstat",
                    "-z",
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
    for line in _numstat_lines(numstat):
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


def _numstat_lines(numstat: str) -> list[str]:
    if "\0" in numstat:
        return [line for line in numstat.split("\0") if line]
    return numstat.splitlines()


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
    include_dirty: bool = False,
    max_bytes: int = 600_000,
) -> DiffResult:
    repo = repo_root(repo)
    if include_dirty:
        checked_out = current_branch(repo)
        if branch != checked_out:
            raise GitError(
                "--include-dirty can only review the checked-out branch "
                f"({checked_out!r}), not {branch!r}"
            )
    base_ref = base or detect_base(
        repo, branch, allow_same_commit=include_dirty
    )
    diff_ref = base_ref if include_dirty else f"{base_ref}..{branch}"
    files = _diff_files(repo, diff_ref, include_untracked=include_dirty)
    diff = "".join(file.diff for file in files)
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

    paths = [file.path for file in files]
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
    for file in files:
        p = file.path
        per_file = file.diff
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


def _diff_files(
    repo: Path,
    diff_ref: str,
    *,
    include_untracked: bool,
) -> list[_DiffFile]:
    numstat = _run(
        ["git", "diff", "--numstat", "-z", "--no-renames", diff_ref],
        repo,
    )
    paths = [
        ln.split("\t", 2)[-1].strip()
        for ln in _numstat_lines(numstat)
        if ln.strip()
    ]
    files = [
        _DiffFile(
            path=p,
            diff=_run(["git", "diff", "--no-renames", diff_ref, "--", p], repo),
        )
        for p in paths
    ]
    if include_untracked:
        files.extend(_untracked_diff_files(repo))
    return files


def _untracked_diff_files(repo: Path) -> list[_DiffFile]:
    raw = _run(["git", "ls-files", "--others", "--exclude-standard", "-z"], repo)
    paths = [p for p in raw.split("\0") if p]
    return [
        _DiffFile(
            path=p,
            diff=_run_diff(
                ["git", "diff", "--no-index", "--", os.devnull, p], repo
            ),
        )
        for p in paths
    ]
