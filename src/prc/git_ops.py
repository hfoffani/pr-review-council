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


def _run(cmd: list[str], cwd: Path) -> str:
    res = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if res.returncode != 0:
        raise GitError(
            f"git failed: {' '.join(cmd)}\n{res.stderr.strip()}"
        )
    return res.stdout


def detect_base(repo: Path, branch: str) -> str:
    """Return a ref usable on the left of `<base>...<branch>`."""
    try:
        upstream = _run(
            ["git", "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"],
            repo,
        ).strip()
        if upstream:
            return upstream
    except GitError:
        pass
    for candidate in ("main", "master", "origin/main", "origin/master"):
        try:
            _run(["git", "rev-parse", "--verify", candidate], repo)
            return candidate
        except GitError:
            continue
    raise GitError(
        f"could not detect base ref for branch {branch!r}; "
        "pass --base explicitly"
    )


def capture_diff(
    repo: Path,
    branch: str,
    base: str | None = None,
    *,
    max_bytes: int = 600_000,
) -> DiffResult:
    if not (repo / ".git").exists():
        raise GitError(f"{repo} is not a git repository")
    base_ref = base or detect_base(repo, branch)
    diff = _run(["git", "diff", f"{base_ref}...{branch}"], repo)
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
        ["git", "diff", "--numstat", "--no-renames", f"{base_ref}...{branch}"],
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
            ["git", "diff", "--no-renames", f"{base_ref}...{branch}", "--", p],
            repo,
        )
        sz = len(per_file.encode("utf-8"))
        if used + sz > max_bytes:
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
