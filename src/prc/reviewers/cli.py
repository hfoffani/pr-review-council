from __future__ import annotations

import subprocess

from ._registry import register_family
from .base import Reviewer


class CLIReviewer(Reviewer):
    command: tuple[str, ...]

    def __init__(self, model: str, **_: object) -> None:
        self.model = model
        self.display_name = model

    def chat(self, system: str, user: str, *, timeout: float) -> str:
        prompt = (
            "<system>\n"
            f"{system}\n"
            "</system>\n\n"
            "<user>\n"
            f"{user}\n"
            "</user>\n"
        )
        try:
            result = subprocess.run(
                [*self.command, "--model", self.model],
                input=prompt,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(
                f"{self.command[0]} timed out after {timeout:g}s"
            ) from e
        except OSError as e:
            raise RuntimeError(f"{self.command[0]} failed to start: {e}") from e

        if result.returncode != 0:
            stderr = result.stderr.strip()
            detail = f": {stderr}" if stderr else ""
            raise RuntimeError(
                f"{self.command[0]} exited with status "
                f"{result.returncode}{detail}"
            )
        return result.stdout


@register_family("codex")
class CodexReviewer(CLIReviewer):
    command = (
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
    )


@register_family("claude")
class ClaudeReviewer(CLIReviewer):
    command = (
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
    )
