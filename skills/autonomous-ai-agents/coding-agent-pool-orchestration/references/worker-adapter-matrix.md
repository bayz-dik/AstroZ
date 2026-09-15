# Worker adapter matrix

Per-CLI facts needed to write an adapter. Verify against the installed version
before trusting a row — these CLIs move fast. The column that matters most is
"config keys we own": those are the only keys an `apply()` should rewrite, and
the rest of the file must be preserved.

## Claude Code

| | |
|---|---|
| config | `~/.claude/settings.json` |
| keys we own | `env.ANTHROPIC_BASE_URL`, `env.ANTHROPIC_AUTH_TOKEN`, `env.ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU}_MODEL` |
| env for one run | `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY`, `IS_SANDBOX=1` |
| invocation | `claude -p "<task>" --model <id> --output-format json --dangerously-skip-permissions --max-turns 40` |
| parse | last stdout line that parses as JSON; `result` is the text, `session_id` resumes, `total_cost_usd` bills |

Notes: `--dangerously-skip-permissions` is refused for root without
`IS_SANDBOX=1`. Without explicit `--model`, the model from `settings.json` gets a
context suffix (`[1m]`) the gateway rejects as an unknown model. Print mode skips
all interactive dialogs, so no PTY or tmux is needed for pool use.

## Codex

| | |
|---|---|
| config | `~/.codex/config.toml` |
| keys we own | `model`, `model_provider`, `approval_policy`, `sandbox_mode`, and the whole `[model_providers.<name>]` section (`base_url`, `env_key`, `wire_api`) |
| env for one run | `OPENAI_API_KEY` (name must match `env_key`) |
| invocation | `codex exec --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox -m <id> -c 'model_provider="<name>"' -c 'approval_policy="never"' "<task>"` |
| parse | plain stdout; it prints its reasoning and final summary as text |

Notes: `wire_api = "chat"` is rejected on current versions — use `"responses"`.
Codex's bwrap sandbox cannot create its synthetic mounts in a proot container, so
sandboxed reads/writes all fail; bypass it and isolate by working directory.
Codex writes real files via `apply_patch`, so a run that only reports a plan has
not done the work — check the diff.

## OpenCode

| | |
|---|---|
| config | `~/.config/opencode/opencode.json` |
| keys we own | `provider.<name>.options.baseURL`, `provider.<name>.options.apiKey`, `provider.<name>.models.<id>`, `model` (`"<provider>/<id>"`) |
| env for one run | none needed (config carries auth) |
| invocation | `opencode run --auto --model <provider>/<id> "<task>"` |
| parse | plain stdout |

Notes: the provider block needs `"npm": "@ai-sdk/openai-compatible"` alongside
`options`. `--auto` auto-approves permissions, which unattended runs need.
First startup is slow (it boots a local server); a run that prints nothing for a
minute is not necessarily broken — read its `--print-logs` output before killing
it. `opencode auth list` showing zero credentials is fine when the provider is
configured in `opencode.json`.

## OMP (oh-my-pi)

| | |
|---|---|
| config | `~/.omp/agent/models.yml` — **not** a `config.json`; `omp config path` prints the agent dir |
| keys we own | `providers.<name>.{baseUrl,apiKey,api,models[]}` (schema: `src/config/models-config-schema-bundle.ts`) |
| env for one run | none (the provider entry carries its own key) |
| invocation | `omp -p "<task>" --model <provider>/<id> --auto-approve --no-session` |
| parse | plain stdout; `--mode json` also exists |

Notes: `api: openai-completions` for an OpenAI-compatible gateway; each model
entry needs at least `id` (add `contextWindow`, `maxTokens`, `supportsTools`,
`input: [text]` or it falls back to a tiny default context). Without a
`models.yml` entry omp answers `Model "<id>" not found` and tells you to set an
API key env var — that message is misleading: `OPENAI_BASE_URL`/`OPENAI_API_KEY`
only redirect the **built-in** `openai` provider, they do not register a custom
endpoint. The model selector must be written `<provider>/<id>` so it matches the
entry. `--auto-approve` is required for unattended runs (otherwise it blocks on
the first write approval); `--no-session` keeps each task's session storage
clean. The binary is a `#!/usr/bin/env bun` bundle: installing
`@oh-my-pi/pi-coding-agent` is not enough, **bun must be on PATH** or every run
dies with `env: 'bun': No such file or directory`. Verify with
`npm view <pkg> bin` before reporting the binary as unavailable — `oh-my-pi` on
npm is a different project and `@oh-my-pi/omp` does not exist.

## Adapter contract

```python
class Worker:
    key: str; label: str; binary: str
    def probe(self) -> dict          # installed, path, version
    def config_path(self) -> Path
    def current_model(self) -> str
    def apply(self, gateway: dict) -> dict      # rewrite ONLY owned keys
    def env(self, gateway: dict, model: str) -> dict
    def command(self, task, model, cwd) -> list[str]
    def parse(self, raw: str) -> dict           # {"text": ..., extras}
```

Preserve unowned keys: read the existing file, drop only the keys/sections the
adapter owns, and write the rest back. A config writer that round-trips the
whole file must handle a file that is absent, empty, or hand-edited with
comments (JSON with comments needs a strip pass before `json.loads`).
