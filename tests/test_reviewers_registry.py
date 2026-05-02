from __future__ import annotations

import pytest

from prc.reviewers import _registry, make_reviewer


class _Fake:
    """Stand-in family class used by tests."""

    instances: list[dict] = []

    def __init__(self, **kwargs):
        type(self).instances.append(kwargs)
        self.model = kwargs.get("model", "?")


@pytest.fixture
def fake_family(monkeypatch: pytest.MonkeyPatch):
    saved = dict(_registry._FAMILIES)
    _registry._FAMILIES["fake"] = _Fake  # type: ignore[assignment]
    _Fake.instances = []
    yield _Fake
    _registry._FAMILIES.clear()
    _registry._FAMILIES.update(saved)


def test_glob_routing_picks_first_match(fake_family) -> None:
    providers = {
        "anthropic": {
            "family": "fake",
            "api_key": "${api_keys.anthropic}",
            "match": ["claude-*"],
        },
        "openai": {
            "family": "fake",
            "base_url": "https://api.openai.com/v1",
            "api_key": "${api_keys.openai}",
            "match": ["gpt-*"],
        },
    }
    api_keys = {"anthropic": "AK", "openai": "OK"}
    r = make_reviewer("gpt-5", providers, api_keys)
    assert r.model == "gpt-5"
    [call] = fake_family.instances
    assert call["api_key"] == "OK"
    assert call["base_url"] == "https://api.openai.com/v1"


def test_interp_resolves_api_keys(fake_family) -> None:
    providers = {
        "x": {
            "family": "fake",
            "api_key": "${api_keys.custom}",
            "match": ["custom-*"],
        }
    }
    make_reviewer("custom-1", providers, {"custom": "SECRET"})
    assert fake_family.instances[0]["api_key"] == "SECRET"


def test_env_var_overrides_config(
    fake_family, monkeypatch: pytest.MonkeyPatch
) -> None:
    providers = {
        "anthropic": {
            "family": "fake",
            "api_key": "${api_keys.anthropic}",
            "match": ["claude-*"],
        }
    }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "FROM_ENV")
    make_reviewer("claude-x", providers, {"anthropic": "FROM_CONFIG"})
    assert fake_family.instances[0]["api_key"] == "FROM_ENV"


def test_generic_env_override(
    fake_family, monkeypatch: pytest.MonkeyPatch
) -> None:
    providers = {
        "deepseek": {
            "family": "fake",
            "api_key": "${api_keys.deepseek}",
            "match": ["deepseek-*"],
        }
    }
    monkeypatch.setenv("PRC_API_KEY_DEEPSEEK", "FROM_ENV")
    make_reviewer("deepseek-v3", providers, {})
    assert fake_family.instances[0]["api_key"] == "FROM_ENV"


def test_no_match_raises(fake_family) -> None:
    with pytest.raises(ValueError, match="no provider matched"):
        make_reviewer("mystery-1", {}, {})


def test_missing_key_raises(fake_family) -> None:
    providers = {
        "x": {
            "family": "fake",
            "api_key": "${api_keys.missing}",
            "match": ["x-*"],
        }
    }
    with pytest.raises(RuntimeError, match="no api_key"):
        make_reviewer("x-1", providers, {})


def test_openai_glob_does_not_swallow_openrouter(fake_family) -> None:
    """o[0-9]* matches o1/o3/o4-mini but not openrouter/..."""
    providers = {
        "openai": {
            "family": "fake",
            "base_url": "https://api.openai.com/v1",
            "api_key": "${api_keys.openai}",
            "match": ["gpt-*", "o[0-9]*"],
        },
        "openrouter": {
            "family": "fake",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "${api_keys.openrouter}",
            "match": ["openrouter/*"],
            "strip_prefix": "openrouter/",
        },
    }
    api_keys = {"openai": "OAI", "openrouter": "OR"}
    make_reviewer("o3-mini", providers, api_keys)
    assert fake_family.instances[-1]["base_url"].startswith("https://api.openai.com")
    make_reviewer("openrouter/deepseek/deepseek-chat", providers, api_keys)
    last = fake_family.instances[-1]
    assert last["base_url"].startswith("https://openrouter.ai")
    assert last["model"] == "deepseek/deepseek-chat"


def test_strip_prefix_removes_routing_tag(fake_family) -> None:
    providers = {
        "openrouter": {
            "family": "fake",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "${api_keys.openrouter}",
            "match": ["openrouter/*"],
            "strip_prefix": "openrouter/",
        }
    }
    make_reviewer(
        "openrouter/deepseek/deepseek-chat",
        providers,
        {"openrouter": "OR"},
    )
    [call] = fake_family.instances
    assert call["model"] == "deepseek/deepseek-chat"
    assert call["base_url"] == "https://openrouter.ai/api/v1"


def test_unknown_family_raises(fake_family) -> None:
    providers = {
        "x": {
            "family": "nope",
            "api_key": "k",
            "match": ["x-*"],
        }
    }
    with pytest.raises(ValueError, match="unknown family"):
        make_reviewer("x-1", providers, {})
