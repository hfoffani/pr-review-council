# PR Review LLM Council (`prc`)

![prreviewllmcouncil](images/banner-pr-council.png)

Multi-LLM council code review for local git branches. Inspired by Andrej Karpathy's
[LLM Council](https://github.com/karpathy/llm-council),
`prc` takes a repo + branch, computes the diff against the auto-detected base,
sends it to a panel of LLMs (Claude, GPT, Gemini, Grok, ...) for independent review in parallel,
has them critique each other, then a configurable Chairman LLM synthesizes
the council's reviews into a final markdown PR review printed to stdout.


## Usage

```bash
cd repo
git checkout my-new-feature
prc review
```

![Output](images/pr-council.gif)


## How it works

1. **Diff capture** — `git diff <base>...<branch>`. Base auto-detected: `<branch>@{upstream}` → `main` → `master` → `origin/main` → `origin/master`. Override with `--base`.
2. **Round 1 (parallel)** — every council member reviews the diff blind.
3. **Round 2 (parallel)** — each member is shown the others' reviews (anonymized as Reviewer A/B/C, own review excluded) and critiques peers.
4. **Round 3** — the Chairman receives the diff + all R1 + all R2 (still anonymized) and synthesizes the final markdown.

Models never see real identities of peers; the orchestrator holds the letter mapping in memory only.


## Install

Requires `uv` 0.1.28 or newer. Install `uv` from the
[official installation guide](https://docs.astral.sh/uv/getting-started/installation/).

```bash
uv tool install git+https://github.com/hfoffani/pr-review-council.git
```

Then run `prc` directly:

```bash
prc config
prc review /path/to/repo my-feature-branch
```

Shortcut installer:

```bash
curl -fsSL https://raw.githubusercontent.com/hfoffani/pr-review-council/main/install.sh | bash
```

The installer is a thin wrapper around `uv tool install` and asks for
confirmation before installing. To inspect it first:

```bash
curl -fsSL https://raw.githubusercontent.com/hfoffani/pr-review-council/main/install.sh
```

If `prc` is not found after installation:

```bash
uv tool update-shell
```

Upgrade or uninstall:

```bash
uv tool upgrade pr-review-council
uv tool uninstall pr-review-council
```

## Configure

First run with no config creates `~/.local/pr-review-council/config.toml` with placeholders and exits with code 5. Edit it to fill in API keys (or leave them blank and use env vars).

Lookup order:
1. `--config PATH` if given
2. `./prc.toml` in the current working directory
3. `~/.local/pr-review-council/config.toml`

Default config:

```toml
[council]
models = ["claude-sonnet-4-6", "gpt-5.1", "gemini-2.5-pro", "grok-4"]

[chair]
model = "claude-opus-4-7"
on_council = false           # if true, chair also reviews R1 (review reused for R3)

[api_keys]
anthropic  = "sk-ant-..."
openai     = "sk-..."
google     = "..."
xai        = "xai-..."
openrouter = "sk-or-..."

[providers.anthropic]
family   = "anthropic"
api_key  = "${api_keys.anthropic}"
match    = ["claude-*"]

[providers.openai]
family   = "openai-compatible"
base_url = "https://api.openai.com/v1"
api_key  = "${api_keys.openai}"
match    = ["gpt-*", "o[0-9]*"]

[providers.google]
family   = "google"
api_key  = "${api_keys.google}"
match    = ["gemini-*", "gemma-*"]

[providers.xai]
family   = "openai-compatible"
base_url = "https://api.x.ai/v1"
api_key  = "${api_keys.xai}"
match    = ["grok-*"]

# Aggregator: "openrouter/<vendor>/<model>" → OpenRouter. The "openrouter/"
# prefix is stripped before the API call.
[providers.openrouter]
family       = "openai-compatible"
base_url     = "https://openrouter.ai/api/v1"
api_key      = "${api_keys.openrouter}"
match        = ["openrouter/*"]
strip_prefix = "openrouter/"
```

To put an OpenRouter model on the council, add e.g. `"openrouter/deepseek/deepseek-chat"` to `[council].models`.

### Adding a new direct provider — zero code

Append a `[providers.<name>]` block; that's it. Example for DeepSeek's own API:

```toml
[providers.deepseek]
family   = "openai-compatible"
base_url = "https://api.deepseek.com/v1"
api_key  = "${api_keys.deepseek}"
match    = ["deepseek-*"]
```

Then add `deepseek-v3` (or whichever id) to `[council].models`.

`strip_prefix` (optional) lets a single provider front many models behind a routing tag — see the OpenRouter block above. Useful for any aggregator API where the natural model id is `vendor/model` and you want `<provider>/vendor/model` in the council list for clarity.

### Env vars override config

`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY`, and `PRC_API_KEY_<NAME>` (uppercased provider name) take precedence over the corresponding config value, so secrets can stay off disk.

### ⚠️ Never commit a project-local `prc.toml`

API keys live in this file. The included `.gitignore` excludes `prc.toml` and `.prc.toml`. If you copy the config into another repo, add it to that repo's `.gitignore` first.

### Custom prompts

To tune the reviewer, peer-critique, or chair prompts, run:

```bash
prc config --edit-prompts
```

If `~/.local/pr-review-council/prompts.toml` does not exist, `prc` creates it
from the built-in prompts first. Missing prompt sections fall back to the
built-ins.

## Run

```bash
prc review /path/to/repo my-feature-branch -v
```

With no positional arguments, `prc review` uses the current directory and
current git branch.

CLI:

```
prc
    review      Review the current repo/branch with the configured council.
    config      Show configuration, provider routing, and API-key presence.
    help        Show help for a subcommand.

prc review [repo] [branch]
    [--base BASE]                       # target branch/ref to compare against
    [--council MODEL[,MODEL...]]        # override config council
    [--chairman MODEL]                  # override config chair
    [--chair-on-council]                # include chair as a council voice
    [--disclose]                        # append reviewer identity mapping
    [--config PATH]                     # explicit config file
    [--max-diff-bytes N]                # truncation cap, default 600000
    [--timeout SECS]                    # per-call, default 180
    [-v]                                # progress to stderr

prc config
    [--edit]                            # open config in $EDITOR
    [--edit-prompts]                    # create/open custom prompts in $EDITOR
    [--config PATH]                     # explicit config file
    [--council MODEL[,MODEL...]]        # override displayed council
    [--chairman MODEL]                  # override displayed chair
    [--chair-on-council]                # include chair in displayed council

prc help review
prc help config
```

`prc config` checks that every active chair/council model matches a provider
and has an API key resolved from config or env vars. It does not make network
calls or validate the key with the provider, so it does not consume LLM tokens.

Exit codes: `0` ok · `2` chair failed · `3` council collapsed (<2 R1 survivors) · `4` git/diff error · `5` config or missing API key.


## Development

From a cloned repo, use the project environment:

```bash
uv sync
uv run prc review /path/to/repo my-feature-branch -v
```

## Tests

Run tests:

```bash
uv run pytest
```
