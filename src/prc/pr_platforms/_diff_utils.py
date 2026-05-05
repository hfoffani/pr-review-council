from __future__ import annotations

from .base import PRPlatformError


def truncate_diff(diff: str, *, max_bytes: int) -> tuple[str, bool, int]:
    bytes_total = len(diff.encode("utf-8"))
    if bytes_total <= max_bytes:
        return diff, False, bytes_total
    if bytes_total > max_bytes * 5:
        raise PRPlatformError(
            f"remote PR diff is {bytes_total} bytes (>5x cap of {max_bytes}); "
            "raise --max-diff-bytes or split the pull request"
        )
    chunks: list[str] = []
    used = 0
    for line in diff.splitlines(keepends=True):
        line_bytes = len(line.encode("utf-8"))
        if used + line_bytes > max_bytes:
            break
        chunks.append(line)
        used += line_bytes
    truncated = "".join(chunks)
    if not truncated:
        truncated = diff[: max(1, max_bytes // 4)]
    return (
        truncated.rstrip()
        + "\n\n"
        + f"TRUNCATED: remote PR diff capped at {max_bytes} bytes "
        + f"(original {bytes_total} bytes).\n",
        True,
        bytes_total,
    )


def count_diff_files(diff: str) -> int:
    return sum(1 for line in diff.splitlines() if line.startswith("diff --git "))
