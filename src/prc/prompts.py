from __future__ import annotations

import tomllib
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

REVIEWER_SYSTEM = """\
You are a senior software engineer performing a code review on a pull \
request diff. Focus on correctness, security, concurrency, edge cases, \
and clarity. Avoid pure style nitpicks unless they obscure intent.

Output strict markdown with these sections, in order:

### Issues
For each issue, a bullet starting with `[blocker]`, `[major]`, or `[minor]`, \
followed by file:line and the problem.

### Suggestions
Bullet list of non-blocking improvements.

### Verdict
A single line: `Verdict: approve` | `Verdict: request-changes` | `Verdict: comment`.

Be concise. Assume the reader has the diff.
"""

CROSS_EVAL_SYSTEM = """\
You previously reviewed a pull request diff. Other reviewers reviewed the \
same diff independently. Critique their reviews:

- Which of their points are valid?
- Which are wrong, overstated, or based on a misreading?
- Which important issues did they miss that you raised, or that none of you raised?

Do NOT re-review the diff from scratch. React to peers.

Output markdown with one `### Reviewer X` section per peer, then a final \
`### Consolidated View` paragraph synthesizing where the council agrees and \
where it splits.
"""

CHAIRMAN_SYSTEM = """\
You are the chair of a code-review council. You receive (1) independent \
reviews from N reviewers and (2) each reviewer's critique of the others. \
Produce the final pull-request review for the author.

When reviewers disagree, resolve it: state which side you side with and \
why. Do not paper over conflicts.

Output markdown with these sections, in order:

### Summary
2-4 sentences on what the change does and the council's overall assessment.

### Blocking Issues
Bullet list. Empty if none.

### Non-blocking Suggestions
Bullet list.

### Points of Disagreement
For each split: what the reviewers disagreed on, and the chair's call.

### Verdict
A single line: `Verdict: approve` | `Verdict: request-changes` | `Verdict: comment`.
"""


@dataclass(frozen=True)
class PromptSet:
    reviewer: str
    cross_eval: str
    chairman: str


DEFAULT_PROMPTS = PromptSet(
    reviewer=REVIEWER_SYSTEM,
    cross_eval=CROSS_EVAL_SYSTEM,
    chairman=CHAIRMAN_SYSTEM,
)

APP_CONFIG_DIR = "pr-review-council"


def default_prompts_dir() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home).expanduser() / APP_CONFIG_DIR
    return Path.home() / ".config" / APP_CONFIG_DIR


def default_prompts_path() -> Path:
    return default_prompts_dir() / "prompts.toml"


DEFAULT_PROMPTS_PATH = default_prompts_path()


def create_default_prompts(path: Path | None = None) -> Path:
    if path is None:
        path = default_prompts_path()
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_default_prompts_template())
    return path


def load_prompts(path: Path | None = None) -> PromptSet:
    if path is None:
        path = default_prompts_path()
    if not path.exists():
        return DEFAULT_PROMPTS

    data = tomllib.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: prompts file must be a TOML table")

    return PromptSet(
        reviewer=_prompt_value(path, data, "reviewer", DEFAULT_PROMPTS.reviewer),
        cross_eval=_prompt_value(
            path, data, "cross_eval", DEFAULT_PROMPTS.cross_eval
        ),
        chairman=_prompt_value(path, data, "chairman", DEFAULT_PROMPTS.chairman),
    )


def _prompt_value(
    path: Path, data: dict[str, Any], section: str, default: str
) -> str:
    table = data.get(section)
    if table is None:
        return default
    if not isinstance(table, dict):
        raise ValueError(f"{path}: [{section}] must be a table")

    value = table.get("system")
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: [{section}].system must be a non-empty string")
    return value


def _default_prompts_template() -> str:
    return "\n\n".join(
        [
            _prompt_section("reviewer", DEFAULT_PROMPTS.reviewer),
            _prompt_section("cross_eval", DEFAULT_PROMPTS.cross_eval),
            _prompt_section("chairman", DEFAULT_PROMPTS.chairman),
            "",
        ]
    )


def _prompt_section(name: str, value: str) -> str:
    return f'[{name}]\nsystem = """\n{value.rstrip()}\n"""'
