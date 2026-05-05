import fnmatch
import os
import re
from dataclasses import dataclass
from typing import Any

from ._registry import _FAMILIES, register_family
from .base import Review, Reviewer

# Trigger family registration. Imports are intentionally side-effecting.
from . import anthropic as _anthropic  # noqa: F401
from . import cli as _cli  # noqa: F401
from . import google as _google  # noqa: F401
from . import openai_compat as _openai_compat  # noqa: F401

__all__ = [
    "Reviewer",
    "Review",
    "ResolvedReviewer",
    "register_family",
    "make_reviewer",
    "resolve_reviewer",
]


_INTERP_RE = re.compile(r"\$\{([^}]+)\}")

_FIXED_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
}


@dataclass(frozen=True)
class ResolvedReviewer:
    model: str
    api_model: str
    provider: str
    family: str
    api_key: str | None
    api_key_source: str
    kwargs: dict[str, Any]


def _interp(value: Any, scope: dict) -> Any:
    if not isinstance(value, str):
        return value

    def repl(m: re.Match[str]) -> str:
        path = m.group(1).strip().split(".")
        cur: Any = scope
        for p in path:
            if not isinstance(cur, dict) or p not in cur:
                return ""
            cur = cur[p]
        return "" if cur is None else str(cur)

    return _INTERP_RE.sub(repl, value)


def _env_var_for(provider_name: str) -> str:
    return _FIXED_ENV.get(
        provider_name,
        f"PRC_API_KEY_{provider_name.upper()}",
    )


def _env_key_for(provider_name: str) -> str | None:
    if provider_name in _FIXED_ENV:
        v = os.environ.get(_FIXED_ENV[provider_name])
        if v:
            return v
    return os.environ.get(f"PRC_API_KEY_{provider_name.upper()}")


def resolve_reviewer(
    model: str, providers_cfg: dict, api_keys: dict
) -> ResolvedReviewer:
    """Resolve a model id via config-driven providers.

    `providers_cfg` is the parsed `[providers.*]` table; `api_keys` is the
    `[api_keys]` table. Walks providers in declaration order, picks the first
    whose `match` glob matches the model. Env vars override config keys.
    """
    scope = {"api_keys": api_keys}
    for prov_name, prov in providers_cfg.items():
        for pattern in prov.get("match", []):
            if not fnmatch.fnmatchcase(model, pattern):
                continue
            family = prov.get("family")
            if family not in _FAMILIES:
                raise ValueError(
                    f"unknown family {family!r} in provider {prov_name!r}"
                )
            env_var = _env_var_for(prov_name)
            env_key = _env_key_for(prov_name)
            config_key = _interp(prov.get("api_key"), scope)
            api_key: str | None = None
            api_key_source = "not required"
            if "api_key" in prov:
                api_key = env_key or config_key
                api_key_source = f"env:{env_var}" if env_key else "config"
            if "api_key" in prov and not api_key:
                raise RuntimeError(
                    f"no api_key resolved for provider {prov_name!r} "
                    f"(model={model}); set env var or fill config"
                )
            api_model = model
            prefix = prov.get("strip_prefix")
            if prefix and api_model.startswith(prefix):
                api_model = api_model[len(prefix):]
            kwargs: dict[str, Any] = {"model": api_model}
            if api_key is not None:
                kwargs["api_key"] = api_key
            if "base_url" in prov:
                kwargs["base_url"] = _interp(prov["base_url"], scope)
            return ResolvedReviewer(
                model=model,
                api_model=api_model,
                provider=prov_name,
                family=family,
                api_key=api_key,
                api_key_source=api_key_source,
                kwargs=kwargs,
            )
    raise ValueError(f"no provider matched model {model!r}")


def make_reviewer(
    model: str, providers_cfg: dict, api_keys: dict
) -> Reviewer:
    resolved = resolve_reviewer(model, providers_cfg, api_keys)
    return _FAMILIES[resolved.family](**resolved.kwargs)
