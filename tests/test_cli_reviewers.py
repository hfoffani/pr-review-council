from __future__ import annotations

import subprocess

import pytest

from prc.reviewers.cli import ClaudeReviewer, CodexReviewer


def test_codex_reviewer_sends_prompt_on_stdin(monkeypatch) -> None:
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="review markdown",
            stderr="codex tool chatter",
        )

    monkeypatch.setattr("prc.reviewers.cli.subprocess.run", run)

    out = CodexReviewer("gpt-5.1").chat("sys", "user", timeout=12)

    assert out == "review markdown"
    [args], kwargs = calls[0]
    assert args == [
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--model",
        "gpt-5.1",
    ]
    assert kwargs["input"] == (
        "<system>\n"
        "sys\n"
        "</system>\n\n"
        "<user>\n"
        "user\n"
        "</user>\n"
    )
    assert kwargs["text"] is True
    assert kwargs["capture_output"] is True
    assert kwargs["timeout"] == 12
    assert kwargs["check"] is False


def test_claude_reviewer_uses_print_mode(monkeypatch) -> None:
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="claude review",
            stderr="",
        )

    monkeypatch.setattr("prc.reviewers.cli.subprocess.run", run)

    out = ClaudeReviewer("claude-sonnet-4-6").chat("sys", "user", timeout=8)

    assert out == "claude review"
    [args], _kwargs = calls[0]
    assert args == [
        "claude",
        "-p",
        "--tools",
        "",
        "--permission-mode",
        "plan",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--output-format",
        "text",
        "--model",
        "claude-sonnet-4-6",
    ]


def test_cli_reviewer_reports_stderr_on_failure(monkeypatch) -> None:
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=2,
            stdout="partial stdout",
            stderr="bad credentials",
        )

    monkeypatch.setattr("prc.reviewers.cli.subprocess.run", run)

    with pytest.raises(RuntimeError, match="bad credentials"):
        CodexReviewer("gpt-5.1").chat("sys", "user", timeout=1)


def test_cli_reviewer_maps_subprocess_timeout(monkeypatch) -> None:
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr("prc.reviewers.cli.subprocess.run", run)

    with pytest.raises(TimeoutError, match="codex timed out"):
        CodexReviewer("gpt-5.1").chat("sys", "user", timeout=1)
