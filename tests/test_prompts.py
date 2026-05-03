from __future__ import annotations

from pathlib import Path

import pytest

from prc import prompts


def test_load_prompts_uses_defaults_when_file_missing(tmp_path: Path) -> None:
    loaded = prompts.load_prompts(tmp_path / "missing.toml")

    assert loaded == prompts.DEFAULT_PROMPTS


def test_load_prompts_applies_partial_overrides(tmp_path: Path) -> None:
    path = tmp_path / "prompts.toml"
    path.write_text(
        '[reviewer]\nsystem = "custom reviewer"\n'
    )

    loaded = prompts.load_prompts(path)

    assert loaded.reviewer == "custom reviewer"
    assert loaded.cross_eval == prompts.DEFAULT_PROMPTS.cross_eval
    assert loaded.chairman == prompts.DEFAULT_PROMPTS.chairman


def test_load_prompts_rejects_bad_shapes(tmp_path: Path) -> None:
    path = tmp_path / "prompts.toml"
    path.write_text('[reviewer]\nsystem = ["bad"]\n')

    with pytest.raises(ValueError, match="reviewer.*system"):
        prompts.load_prompts(path)


def test_create_default_prompts_does_not_overwrite_existing_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "prompts.toml"
    path.write_text("# mine\n")

    created = prompts.create_default_prompts(path)

    assert created == path
    assert path.read_text() == "# mine\n"


def test_default_prompts_path_respects_xdg_config_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    assert (
        prompts.default_prompts_path()
        == config_home / "pr-review-council/prompts.toml"
    )


def test_create_default_prompts_uses_xdg_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_home = tmp_path / "xdg"
    expected = config_home / "pr-review-council/prompts.toml"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    created = prompts.create_default_prompts()

    assert created == expected
    assert expected.exists()
    assert "[reviewer]" in expected.read_text()
