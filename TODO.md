# pr-review-council — Implementation TODO

- [ ] 1. `pyproject.toml` + `src/prc/__init__.py` + `__main__.py`; install in editable mode.
- [ ] 2. `reviewers/base.py` — `Reviewer` ABC, `Review` dataclass.
- [ ] 3. `reviewers/__init__.py` — `register_family` decorator + `_FAMILIES` registry + `make_reviewer(model, providers_cfg, api_keys)` resolver (glob match + `${api_keys.X}` interp + env override).
- [ ] 4. `reviewers/anthropic.py` — `AnthropicReviewer` (system-prompt caching enabled).
- [ ] 5. `reviewers/openai_compat.py` — `OpenAICompatibleReviewer` (used for OpenAI, Grok, etc.).
- [ ] 6. `reviewers/gemini.py` — `GeminiReviewer`.
- [ ] 7. `config.py` — TOML lookup precedence; default-create at `~/.local/pr-review-council/config.toml` with all 4 default providers; env-var overlay; validation.
- [ ] 8. `git_ops.py` — base detection (`@{u}` → `main` → `master`), three-dot diff capture, char-budget truncation w/ per-file inclusion + footer.
- [ ] 9. `prompts.py` — three template strings (R1, R2, R3).
- [ ] 10. `context.py` — `ContextProvider` ABC + `DiffOnlyContext` impl.
- [ ] 11. `council.py` — `ThreadPoolExecutor` fan-out for R1 + R2; A/B/C blinding map; partial-failure handling; chair-on-council R1 reuse.
- [ ] 12. `chairman.py` — single R3 call with full bundle.
- [ ] 13. `cli.py` — Typer app: arg parsing, exit codes, `-v` stderr progress, empty-diff short-circuit, missing-config first-run path.
- [ ] 14. Tests (`pytest`): `config` lookup + env overlay + default-create; `git_ops` base fallbacks; `reviewers/__init__` glob routing + `${api_keys.*}` interp; `council` mock-Reviewer blinding + partial failure + chair-on-council reuse.
- [ ] 15. `README.md` — install, configure, run, security note about config file + `.gitignore`.
- [ ] 16. Live smoke test against a real branch with all 4 keys set; verify all 8 verification steps in PRD.
