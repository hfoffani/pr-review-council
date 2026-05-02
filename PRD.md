# pr-review-council (`prc`) — MVP plan

## Context
Greenfield. Empty dir at `/Users/hernan/MisProyectos/pr-review-council`.
Goal: CLI tool. Input = local repo path + branch. Auto-detect base, diff branch vs base, ask N council LLMs to review in parallel, ask same LLMs to cross-evaluate peers, then a Chairman LLM synthesizes final markdown to stdout. MVP = diff-only, no GitHub/BitBucket fetch, no `pull-request.md` skill loading (clean seam for later).

## Layout
```
pr-review-council/
├── pyproject.toml
├── README.md
├── .gitignore
├── src/prc/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py            # Typer entry, orchestrates rounds
│   ├── config.py         # TOML lookup/load/create-default
│   ├── git_ops.py        # base detect + three-dot diff
│   ├── context.py        # ContextProvider seam (DiffOnlyContext now)
│   ├── council.py        # round 1 + 2 fan-out (ThreadPoolExecutor), blinding map
│   ├── chairman.py       # round 3 single-shot
│   ├── prompts.py        # 3 prompt templates
│   └── reviewers/
│       ├── __init__.py   # @register_family registry + make_reviewer()
│       ├── base.py       # Reviewer ABC, Review dataclass
│       ├── anthropic.py  # family: "anthropic"
│       ├── openai_compat.py  # family: "openai-compatible" — used by OpenAI, Grok, DeepSeek, etc.
│       └── gemini.py     # family: "gemini"
└── tests/
```
No per-model files. Adding a new OpenAI-API-compatible provider = config block, zero code.

## Reviewer abstraction & registration
```python
# reviewers/base.py
class Reviewer(ABC):
    model: str            # canonical id, e.g. "claude-opus-4-7"
    display_name: str
    @abstractmethod
    def chat(self, system: str, user: str, *, timeout: float) -> str: ...

# reviewers/__init__.py
_FAMILIES: dict[str, type[Reviewer]] = {}
def register_family(name):                    # decorator
    def deco(cls): _FAMILIES[name] = cls; return cls
    return deco

# in each module:
@register_family("anthropic")
class AnthropicReviewer(Reviewer): ...        # ctor: model, api_key
@register_family("openai-compatible")
class OpenAICompatibleReviewer(Reviewer): ... # ctor: model, base_url, api_key
@register_family("gemini")
class GeminiReviewer(Reviewer): ...           # ctor: model, api_key
```
Same `chat()` used in R1/R2/R3 — only prompt differs. Anthropic class enables prompt caching on the system prompt.

### Routing (config-driven, no code changes for new OpenAI-compat providers)
Default config seeds a `[providers.*]` table. Each entry: `family`, optional `base_url`, `api_key` (or `${api_keys.<name>}` ref), `match` (list of glob patterns for model names). `make_reviewer(model)` walks `[providers.*]` in declaration order, picks the first whose `match` glob matches, instantiates `_FAMILIES[entry.family](model, …)`. Examples (these go in the auto-created `config.toml`):
```toml
[providers.anthropic]
family   = "anthropic"
api_key  = "${api_keys.anthropic}"
match    = ["claude-*"]

[providers.openai]
family   = "openai-compatible"
base_url = "https://api.openai.com/v1"
api_key  = "${api_keys.openai}"
match    = ["gpt-*", "o*"]

[providers.gemini]
family   = "gemini"
api_key  = "${api_keys.gemini}"
match    = ["gemini-*"]

[providers.xai]
family   = "openai-compatible"
base_url = "https://api.x.ai/v1"
api_key  = "${api_keys.xai}"
match    = ["grok-*"]

# user adds DeepSeek with zero code:
# [providers.deepseek]
# family   = "openai-compatible"
# base_url = "https://api.deepseek.com/v1"
# api_key  = "${api_keys.deepseek}"
# match    = ["deepseek-*"]
```

### Future plugin path (post-MVP, no work now)
`importlib.metadata.entry_points(group="prc.reviewers")` scanned at import time. Third-party packages can register a brand-new `family` (e.g., a Bedrock or Vertex client) by exposing a `Reviewer` subclass under that group. Mentioned only to confirm the registry shape supports it; no code in MVP.

## Workflow
1. **Diff capture** — `git -C <repo> diff <base>...<branch>`. Base detection: `@{u}` merge-base → `main` → `master`. `--base` overrides.
2. **Round 1** (parallel, `ThreadPoolExecutor`) — each reviewer gets diff, returns markdown review w/ `Issues / Suggestions / Verdict`.
3. **Round 2** (parallel) — each reviewer gets the diff + peers' round-1 reviews (anonymized A/B/C, **own review excluded**), critiques peers.
4. **Round 3** — Chairman gets diff + all round-1 + all round-2, outputs final markdown.

## Prompts (`prompts.py`, plain strings)
- **Reviewer (R1)**: senior-engineer code review; sections Issues (severity-tagged), Suggestions, Verdict (approve/request-changes/comment).
- **Cross-eval (R2)**: critique peers — what's valid, wrong, missed; do not re-review from scratch; per-reviewer sections + brief Consolidated View.
- **Chairman (R3)**: receives bundle, resolves disagreements explicitly; sections Summary / Blocking / Suggestions / Disagreements / Verdict.

## CLI
```
prc <repo> <branch>
    [--base BASE]
    [--council MODEL[,MODEL...]]    # overrides config
    [--chairman MODEL]              # overrides config
    [--chair-on-council]            # opt-in; chair's R1 review reused, no double call
    [--config PATH]                 # explicit config path
    [--max-diff-bytes N]            # default 600000 (~150k tok)
    [--timeout SECS]                # default 180
    [-v]
```

## Configuration
File format: TOML (`tomllib` stdlib). Lookup order:
1. `--config PATH` if given
2. `./prc.toml` in CWD
3. `~/.local/pr-review-council/config.toml`

If none found → create `~/.local/pr-review-council/config.toml` with placeholders, print path to stderr, exit 5.

Schema (top level — `[providers.*]` table shown in Routing section above):
```toml
[council]
models = ["claude-sonnet-4-6", "gpt-5.1", "gemini-2.5-pro", "grok-4"]

[chair]
model = "claude-opus-4-7"
on_council = false           # if true, chair also reviews R1 (review reused for R3)

[api_keys]
anthropic = "sk-ant-..."
openai    = "sk-..."
gemini    = "..."
xai       = "xai-..."
```
`[api_keys]` is just a named-secrets store; `[providers.*]` references entries via `${api_keys.<name>}`. Env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`, plus `PRC_API_KEY_<NAME>` for custom) override resolved values when set, so secrets can stay off disk. Missing key for a selected model → fail fast (exit 5). README warns against committing `./prc.toml` and recommends `.gitignore` entry.

## Blinding
Models never see real identities of peers. Orchestrator assigns Reviewer A/B/C... mapping per run, kept only in memory. If chair is also on council (`on_council=true`), its own R1 review is included in the bundle as Reviewer X like any other; the chair in R3 sees the bundle as A/B/C and does not know which letter was itself. No double API call: chair's R1 result is reused; R3 is one extra call.

## Diff sizing
Char-based budgeting (skip per-provider tokenizers). ≤ cap → send whole. > cap → per-file inclusion in `git diff --numstat` order until budget hit, append `TRUNCATED: N/M files included` footer, stderr warning. > 5× cap → hard error (likely lockfile/generated). Single LLM call per reviewer per round (no chunk-merge).

## Error handling
Member fails R1 → drop from R2/R3, log stderr.
Member fails R2 → still include their R1 in chair input.
Abort only if council < 2 after R1 (exit 3) or chairman fails (exit 2).
Exit codes: `0` ok, `2` chair fail, `3` council collapse, `4` git/diff fail, `5` config/key. Retry: 1× on transient net/5xx (2s backoff); no retry on 4xx.
Empty diff → exit 0 with stderr "no changes", no model calls.

## Packaging (`pyproject.toml`)
Python ≥3.11, hatchling. Deps: `anthropic`, `openai`, `google-genai`, `typer`, `rich` (stderr progress only). Console script: `prc = "prc.cli:app"`. Dev extras: `pytest`, `pytest-mock`, `ruff`.

## Critical files
- `src/prc/cli.py` — orchestration, exit codes
- `src/prc/config.py` — TOML lookup, default-create, env-var overlay
- `src/prc/council.py` — R1/R2 fan-out, blinding (A/B/C) map, chair-on-council reuse
- `src/prc/chairman.py` — R3
- `src/prc/reviewers/base.py` — Reviewer ABC
- `src/prc/reviewers/{anthropic,openai_compat,gemini}.py`
- `src/prc/prompts.py`
- `src/prc/git_ops.py`
- `pyproject.toml`

## Verification
1. `pip install -e ".[dev]"`. First run with no config → expect creation of `~/.local/pr-review-council/config.toml` + exit 5; fill in keys.
2. Real branch w/ upstream `origin/main`: `prc /path/to/repo my-feature -v`. Expect stderr: base detected, diff size, `R1 4/4 ok`, `R2 4/4 ok`, chair ok. Stdout: markdown.
3. Base detection paths: with upstream / without upstream / `--base` override (assert byte-equal to `git diff <base>...<branch>`).
4. Failure: unset `XAI_API_KEY` → council shrinks to 3, still ships.
5. Council of 1: round 2 skipped, chair note added.
6. Empty diff: friendly exit 0, zero model calls.
7. Big diff (~100 files refactor): truncation warning + footer matches `git diff --name-only | head`.
8. `--chair-on-council`: confirm chair's R1 review appears in the bundle (as one of A/B/C/...) and only one extra API call (R3) happens, not two.
9. Unit tests: `config` (lookup precedence, default-create, env overlay), `git_ops` (base fallbacks), `reviewers.__init__` (prefix routing), `council` (mock Reviewer, blinding map, chair-on-council reuse, partial-failure path).

## Unresolved questions
None — all six prior questions answered.
