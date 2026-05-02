import fnmatch
import os
import re
from typing import Any

from ._registry import _FAMILIES, register_family
from .base import Review, Reviewer

# Trigger family registration. Imports are intentionally side-effecting.
from . import anthropic as _anthropic  # noqa: F401
from . import google as _google  # noqa: F401
from . import openai_compat as _openai_compat  # noqa: F401

__all__ = ["Reviewer", "Review", "register_family", "make_reviewer"]


_INTERP_RE = re.compile(r"\$\{([^}]+)\}")

_FIXED_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
}


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


def _env_key_for(provider_name: str) -> str | None:
    if provider_name in _FIXED_ENV:
        v = os.environ.get(_FIXED_ENV[provider_name])
        if v:
            return v
    return os.environ.get(f"PRC_API_KEY_{provider_name.upper()}")


def make_reviewer(
    model: str, providers_cfg: dict, api_keys: dict
) -> Reviewer:
    """Resolve a model id to a Reviewer instance via config-driven providers.

    `providers_cfg` is the parsed `[providers.*]` table; `api_keys` is the
    `[api_keys]` table. Walks providers in declaration order, picks the first
    whose `match` glob matches the model, then instantiates the family class.
    Env vars override config keys.
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
            api_key = _env_key_for(prov_name) or _interp(
                prov.get("api_key"), scope
            )
            if not api_key:
                raise RuntimeError(
                    f"no api_key resolved for provider {prov_name!r} "
                    f"(model={model}); set env var or fill config"
                )
            kwargs: dict[str, Any] = {"model": model, "api_key": api_key}
            if "base_url" in prov:
                kwargs["base_url"] = _interp(prov["base_url"], scope)
            return _FAMILIES[family](**kwargs)
    raise ValueError(f"no provider matched model {model!r}")
