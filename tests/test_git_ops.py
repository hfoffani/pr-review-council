from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from prc import git_ops


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": __import__("os").environ.get("PATH", ""),
            "HOME": str(cwd),
        },
    )


@pytest.fixture
def repo_with_branch(tmp_path: Path) -> tuple[Path, str, str]:
    """A repo with `main` and a `feature` branch with one extra commit."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "a.txt").write_text("hello\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "init")
    _git(repo, "checkout", "-b", "feature")
    (repo / "b.txt").write_text("world\n")
    (repo / "a.txt").write_text("hello\nmore\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feature")
    return repo, "main", "feature"


def test_detect_base_falls_back_to_main(repo_with_branch) -> None:
    repo, _, branch = repo_with_branch
    assert git_ops.detect_base(repo, branch) == "main"


def test_detect_base_prefers_master_if_main_absent(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-b", "master")
    (repo / "x").write_text("x")
    _git(repo, "add", "x")
    _git(repo, "commit", "-m", "i")
    _git(repo, "checkout", "-b", "feat")
    (repo / "x").write_text("x2")
    _git(repo, "commit", "-am", "f")
    assert git_ops.detect_base(repo, "feat") == "master"


def test_capture_diff_three_dot(repo_with_branch) -> None:
    repo, base, branch = repo_with_branch
    res = git_ops.capture_diff(repo, branch)
    assert res.base == base
    assert res.files_total == 2
    assert res.files_included == 2
    assert not res.truncated
    assert "+more" in res.diff
    assert "+world" in res.diff


def test_empty_diff(repo_with_branch) -> None:
    repo, _, _ = repo_with_branch
    res = git_ops.capture_diff(repo, "main", "main")
    assert res.diff == ""
    assert res.files_total == 0


def test_truncation(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "seed").write_text("s")
    _git(repo, "add", "seed")
    _git(repo, "commit", "-m", "i")
    _git(repo, "checkout", "-b", "f")
    # Create several files, each ~1KB of distinct content.
    for i in range(6):
        (repo / f"f{i}.txt").write_text(f"line-{i}\n" * 200)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "many")
    res = git_ops.capture_diff(repo, "f", "main", max_bytes=2_500)
    assert res.truncated
    assert res.files_included < res.files_total
    assert "TRUNCATED:" in res.diff


def test_truncation_errors_when_first_file_exceeds_cap(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "seed").write_text("s")
    _git(repo, "add", "seed")
    _git(repo, "commit", "-m", "i")
    _git(repo, "checkout", "-b", "f")
    (repo / "large.txt").write_text("line\n" * 1_200)
    (repo / "small.txt").write_text("ok\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "mixed")
    with pytest.raises(git_ops.GitError, match="first changed file"):
        git_ops.capture_diff(repo, "f", "main", max_bytes=5_000)


def test_oversize_hard_error(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "seed").write_text("s")
    _git(repo, "add", "seed")
    _git(repo, "commit", "-m", "i")
    _git(repo, "checkout", "-b", "f")
    (repo / "huge.txt").write_text("x" * 20_000)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "huge")
    with pytest.raises(git_ops.GitError, match=">5x cap"):
        git_ops.capture_diff(repo, "f", "main", max_bytes=1_000)
