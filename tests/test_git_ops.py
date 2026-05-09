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


def _git_output(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": __import__("os").environ.get("PATH", ""),
            "HOME": str(cwd),
        },
    ).stdout


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


def test_detect_base_prefers_origin_main_before_local_main(
    repo_with_branch,
) -> None:
    repo, _, branch = repo_with_branch
    _git(repo, "update-ref", "refs/remotes/origin/main", "main")

    assert git_ops.detect_base(repo, branch) == "origin/main"


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


def test_detect_base_chooses_smallest_candidate_diff(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "app.txt").write_text("base\n")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-m", "init")
    _git(repo, "checkout", "-b", "develop")
    (repo / "develop.txt").write_text("develop\n")
    _git(repo, "add", "develop.txt")
    _git(repo, "commit", "-m", "develop")
    _git(repo, "checkout", "-b", "feature")
    (repo / "feature.txt").write_text("feature\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feature")

    assert git_ops.detect_base(repo, "feature") == "develop"


def test_detect_base_ignores_feature_upstream(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    remote = tmp_path / "remote.git"
    repo.mkdir()
    remote.mkdir()
    _git(remote, "init", "--bare")
    _git(repo, "init", "-b", "main")
    _git(repo, "remote", "add", "origin", str(remote))
    (repo / "x").write_text("x\n")
    _git(repo, "add", "x")
    _git(repo, "commit", "-m", "init")
    _git(repo, "push", "-u", "origin", "main")
    _git(repo, "checkout", "-b", "feature")
    (repo / "x").write_text("x\nfeature\n")
    _git(repo, "commit", "-am", "feature")
    _git(repo, "push", "-u", "origin", "feature")

    assert git_ops.detect_base(repo, "feature") == "origin/main"


def test_numstat_score_rejects_malformed_lines() -> None:
    with pytest.raises(git_ops.GitError, match="malformed git numstat line"):
        git_ops._numstat_score("1\tmissing-path\n")

    with pytest.raises(git_ops.GitError, match="malformed git numstat line"):
        git_ops._numstat_score("x\t2\tfile.txt\n")


def test_current_branch(repo_with_branch) -> None:
    repo, _, branch = repo_with_branch
    assert git_ops.current_branch(repo) == branch


def test_repo_root_resolves_from_subdirectory(repo_with_branch) -> None:
    repo, _, _ = repo_with_branch
    sub = repo / "nested" / "deeper"
    sub.mkdir(parents=True)
    assert git_ops.repo_root(sub).resolve() == repo.resolve()


def test_repo_root_rejects_non_repo(tmp_path: Path) -> None:
    with pytest.raises(git_ops.GitError, match="is not a git repository"):
        git_ops.repo_root(tmp_path)


def test_current_branch_from_subdirectory(repo_with_branch) -> None:
    repo, _, branch = repo_with_branch
    sub = repo / "nested"
    sub.mkdir()
    assert git_ops.current_branch(sub) == branch


def test_capture_diff_two_dot(repo_with_branch) -> None:
    repo, base, branch = repo_with_branch
    res = git_ops.capture_diff(repo, branch)
    assert res.base == base
    assert res.files_total == 2
    assert res.files_included == 2
    assert not res.truncated
    assert "+more" in res.diff
    assert "+world" in res.diff


def test_capture_diff_from_subdirectory(repo_with_branch) -> None:
    repo, base, branch = repo_with_branch
    sub = repo / "nested"
    sub.mkdir()
    res = git_ops.capture_diff(sub, branch)
    assert res.base == base
    assert res.files_total == 2
    assert "+more" in res.diff


def test_capture_diff_two_dot_includes_base_drift(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "a.txt").write_text("base\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "init")
    base_commit = _git_output(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-b", "feature")
    (repo / "feature.txt").write_text("feature\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feature")
    _git(repo, "checkout", "main")
    (repo / "main.txt").write_text("main drift\n")
    _git(repo, "add", "main.txt")
    _git(repo, "commit", "-m", "main drift")

    res = git_ops.capture_diff(repo, "feature", "main")

    assert "index 0000000.." in res.diff
    assert "feature.txt" in res.diff
    assert "main.txt" in res.diff
    assert _git_output(repo, "merge-base", "main", "feature").strip() == base_commit


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
