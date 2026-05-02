from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = (
    Path.home() / ".local" / "pr-review-council" / "config.toml"
)

DEFAULT_TEMPLATE = """\
[council]
models = ["claude-sonnet-4-6", "gpt-5.1", "gemini-2.5-pro", "grok-4"]

[chair]
model = "claude-opus-4-7"
on_council = false

[api_keys]
anthropic = ""
openai    = ""
google    = ""
xai       = ""

[providers.anthropic]
family   = "anthropic"
api_key  = "${api_keys.anthropic}"
match    = ["claude-*"]

[providers.openai]
family   = "openai-compatible"
base_url = "https://api.openai.com/v1"
api_key  = "${api_keys.openai}"
match    = ["gpt-*", "o*"]

[providers.google]
family   = "google"
api_key  = "${api_keys.google}"
match    = ["gemini-*", "gemma-*"]

[providers.xai]
family   = "openai-compatible"
base_url = "https://api.x.ai/v1"
api_key  = "${api_keys.xai}"
match    = ["grok-*"]
"""


@dataclass
class Config:
    council: list[str]
    chair_model: str
    chair_on_council: bool
    providers: dict[str, dict[str, Any]]
    api_keys: dict[str, str]
    source: Path


class ConfigMissing(Exception):
    """No config file existed; one was created at `created_at` for the user."""

    def __init__(self, created_at: Path) -> None:
        super().__init__(str(created_at))
        self.created_at = created_at


def find_config(
    explicit: Path | None = None, cwd: Path | None = None
) -> Path | None:
    if explicit is not None:
        if not explicit.exists():
            raise FileNotFoundError(explicit)
        return explicit
    cwd = cwd or Path.cwd()
    local = cwd / "prc.toml"
    if local.exists():
        return local
    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH
    return None


def create_default_config(path: Path | None = None) -> Path:
    if path is None:
        path = DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_TEMPLATE)
    return path


def load(
    explicit: Path | None = None, cwd: Path | None = None
) -> Config:
    found = find_config(explicit, cwd)
    if found is None:
        created = create_default_config()
        raise ConfigMissing(created)

    data = tomllib.loads(found.read_text())

    council_raw = (data.get("council") or {}).get("models") or []
    if not isinstance(council_raw, list) or not all(
        isinstance(m, str) for m in council_raw
    ):
        raise ValueError(f"{found}: council.models must be a list of strings")
    if not council_raw:
        raise ValueError(f"{found}: council.models is empty")

    chair_raw = data.get("chair") or {}
    chair_model = chair_raw.get("model")
    if not isinstance(chair_model, str) or not chair_model:
        raise ValueError(f"{found}: chair.model is required")
    chair_on_council = bool(chair_raw.get("on_council", False))

    providers = data.get("providers") or {}
    if not isinstance(providers, dict) or not providers:
        raise ValueError(f"{found}: [providers.*] table is required")
    for name, prov in providers.items():
        if not isinstance(prov, dict):
            raise ValueError(f"{found}: provider {name!r} is not a table")
        if "family" not in prov:
            raise ValueError(f"{found}: provider {name!r} missing 'family'")
        if "match" not in prov or not isinstance(prov["match"], list):
            raise ValueError(
                f"{found}: provider {name!r} missing 'match' list"
            )

    api_keys = data.get("api_keys") or {}
    if not isinstance(api_keys, dict):
        raise ValueError(f"{found}: [api_keys] must be a table")

    return Config(
        council=council_raw,
        chair_model=chair_model,
        chair_on_council=chair_on_council,
        providers=providers,
        api_keys=api_keys,
        source=found,
    )
