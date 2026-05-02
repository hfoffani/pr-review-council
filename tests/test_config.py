from __future__ import annotations

from pathlib import Path

import pytest

from prc import config as cfg


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


VALID = """\
[council]
models = ["claude-x", "gpt-y"]

[chair]
model = "claude-z"

[api_keys]
anthropic = "ant-key"
openai = "oai-key"

[providers.anthropic]
family = "anthropic"
api_key = "${api_keys.anthropic}"
match = ["claude-*"]

[providers.openai]
family = "openai-compatible"
base_url = "https://api.openai.com/v1"
api_key = "${api_keys.openai}"
match = ["gpt-*"]
"""


def test_load_valid(tmp_path: Path) -> None:
    p = tmp_path / "prc.toml"
    p.write_text(VALID)
    c = cfg.load(explicit=p)
    assert c.council == ["claude-x", "gpt-y"]
    assert c.chair_model == "claude-z"
    assert c.chair_on_council is False
    assert "anthropic" in c.providers
    assert c.api_keys["anthropic"] == "ant-key"


def test_lookup_prefers_cwd_over_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    (cwd / "prc.toml").write_text(VALID)
    fallback = home / ".local/pr-review-council/config.toml"
    _write(fallback, VALID)
    monkeypatch.setattr(cfg, "DEFAULT_CONFIG_PATH", fallback)
    found = cfg.find_config(cwd=cwd)
    assert found == cwd / "prc.toml"


def test_lookup_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    fallback = tmp_path / "home/.local/pr-review-council/config.toml"
    _write(fallback, VALID)
    monkeypatch.setattr(cfg, "DEFAULT_CONFIG_PATH", fallback)
    found = cfg.find_config(cwd=cwd)
    assert found == fallback


def test_missing_creates_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fallback = tmp_path / "home/.local/pr-review-council/config.toml"
    monkeypatch.setattr(cfg, "DEFAULT_CONFIG_PATH", fallback)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    with pytest.raises(cfg.ConfigMissing) as exc:
        cfg.load(cwd=cwd)
    assert exc.value.created_at == fallback
    assert fallback.exists()
    assert "[providers.anthropic]" in fallback.read_text()


def test_missing_chair_model(tmp_path: Path) -> None:
    body = """\
[council]
models = ["x"]
[chair]
[providers.x]
family = "anthropic"
match = ["x"]
"""
    p = tmp_path / "prc.toml"
    p.write_text(body)
    with pytest.raises(ValueError, match="chair.model"):
        cfg.load(explicit=p)


def test_empty_council(tmp_path: Path) -> None:
    body = """\
[council]
models = []
[chair]
model = "z"
[providers.x]
family = "anthropic"
match = ["x"]
"""
    p = tmp_path / "prc.toml"
    p.write_text(body)
    with pytest.raises(ValueError, match="council.models is empty"):
        cfg.load(explicit=p)
