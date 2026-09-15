---
name: hermes-plugin-authoring
description: Use when building or debugging a native Hermes plugin.
---

# Authoring a native Hermes plugin

For plugins that add hooks/tools/slash commands/CLI subcommands. Read the
upstream guide at `hermes-agent/website/docs/developer-guide/plugins/index.md`
for the full API; this skill carries the steps that cost real time.

## Where plugins live and why nothing loads

A plugin is a directory with `plugin.yaml` + `__init__.py` exposing
`register(ctx)`. Search order (later wins): bundled `plugins/<name>/` →
`$HERMES_HOME/plugins/` → `./.hermes/plugins/` (needs
`HERMES_ENABLE_PROJECT_PLUGINS`) → pip entry points.

**Discovery is not activation.** A user plugin dropped in
`~/.hermes/plugins/` is *found* but skipped — `gate_manifest` requires the key
in `plugins.enabled`. Log line to look for:
`Plugin discovery complete: N found, M enabled`. If your count didn't move, it
is not enabled. Fix:

```bash
hermes plugins enable <key>      # writes plugins.enabled in config.yaml
hermes plugins list              # Status column: enabled / not enabled
```

`plugins.enabled` is read at startup, so a running session never picks it up —
"takes effect on next session" is literal.

## Validate before running a real session

```bash
hermes plugins doctor <dir> --ci   # discovery + manifest + import + register(ctx)
hermes plugins show <key>          # status, hooks, tools
```

`doctor` runs the real loader in a temp `HERMES_HOME` and reports
`registrations: N tool(s), M hook(s)`. Unknown hook names and callbacks without
`**kwargs` are flagged here rather than failing silently at runtime.

Note: `hermes plugins show` prints **Emits/Listens from the manifest's
`emits:`/`listens:` keys** — not from `provides_hooks`. "Listens: (none)" on a
plugin that declares `provides_hooks` is expected, not a bug. Don't add unknown
manifest fields just to silence it (unknown fields warn).

## Prove it loaded, don't guess

Registration is invisible from outside. Probe the live manager:

```python
import os; os.environ["HERMES_HOME"] = "<home>"
import model_tools                     # triggers discover_plugins()
from hermes_cli.plugins import get_plugin_manager
pm = get_plugin_manager()
for key, p in pm._plugins.items():
    if p.manifest.name == "<name>":
        print(p.enabled, p.error, p.hooks_registered, p.commands_registered)
print(sorted(k for k, v in pm._hooks.items() if v))
```

`discover_plugins()` runs only as a side effect of importing `model_tools` —
import it first or the manager looks empty.

## Hook payloads worth knowing (all keyword, all additive)

Signatures are signature-inspected: declare only the fields you want, always
accept `**kwargs`.

| hook | fires | useful fields |
|---|---|---|
| `on_session_start` / `on_session_end` | session lifecycle | `session_id`, `model`, `platform`, `completed` |
| `pre_llm_call` | once per turn, before the tool loop | `session_id`, `user_message`, `is_first_turn`, `model` |
| `pre_api_request` | before EACH raw provider call | `session_id`, `model`, `provider`, `api_call_count`, `message_count`, `tool_count`, `approx_input_tokens` |
| `post_api_request` | after each provider call | + `api_duration`, `finish_reason`, `usage`, `assistant_tool_call_count` |
| `api_request_error` | provider call raised | `status_code`, `retry_count`, `max_retries`, `reason`, `error` |
| `pre_tool_call` / `post_tool_call` | around every tool | `tool_name`, `args`, `result`, `task_id`, `duration_ms` |

Gotchas:

- `pre_tool_call`/`post_tool_call` carry `task_id`, **not** `session_id`. Track
  the last session id yourself if you need to correlate.
- There is **no** `tool started` line in `agent.log` — only `tool X completed`.
  Don't build a log parser expecting both; use the hooks instead.
- `pre_llm_call` is the ONLY hook whose return value matters (returns
  `{"context": ...}` to inject text into the user message). Return `None` from
  every observer hook so you never accidentally inject.
- Log lines from `conversation_loop` may lack `latency=`/`cache=` depending on
  provider path. Parse defensively.

## Hot-path rules for observer plugins

- Hooks fire per tool call and per API call — keep callbacks to one syscall.
  Open an `O_APPEND` fd lazily, `os.write` one pre-encoded line under a lock.
- Wrap every callback body in `try/except` and log at debug. A broken monitor
  must never break the agent.
- Never return a directive from an observer hook; a `pre_tool_call` dict return
  can block the call.

## Testing without burning API calls

Load the plugin package directly and call the hook functions with the payload
shapes from the table above — that validates the writer/format. Then do ONE real
E2E: `hermes chat -Q -q "..."` in the background and read the artifact it
produced. Startup takes ~40s (model metadata probing) before the first turn, so
poll the artifact rather than assuming failure at 15s.

## Full-screen TUI renderers: the wrap bug

A line written with exactly the pane width auto-wraps, scrolling the pane and
leaving ghost characters from the previous frame. Two rules for any
in-place-redraw panel:

- Render to `width - 1`, and end each line with `\033[K` (erase to EOL) instead
  of padding with spaces.
- Redraw with `\033[H` + the joined lines and `end=""`; clear with `\033[2J`
  only on first paint and on resize.

Also re-check pane geometry on resize via `shutil.get_terminal_size()`, and
follow the newest session by resetting state when a `session_start` event for a
different session id arrives.

## Live panels must not report a dead process as running

An observer plugin that folds start/end event pairs into a phase will lie when the
process dies mid-event: no `tool_end` arrives, so the phase spins `RUNNING`
forever with a live spinner. Detect it by tracking `last_event_ts` (max of every
folded event's `ts`) and flagging a busy phase (`thinking`/`tools`/`error`) as
STALLED once `now - last_event_ts` passes a threshold. Exempt idle/waiting:
silence there is legitimate and carries no signal. Set the threshold above real
tool durations, not at an arbitrary small number (real feeds showed browser_exec
avg 32s, terminal up to 122s), and make it env-overridable so a long tool can be
tolerated without a code change.

## Payload fields that are NOT populated the way the docs suggest

- `task_id` on `pre_tool_call`/`post_tool_call` was **empty in every event** of a
  real 2400-event feed, even during `delegate_task` runs. Do not use it as the
  session key. `session_id` is populated on `pre_api_request`,
  `post_api_request`, and `api_request_error`, so correlate through that. A
  plugin falling back to `task_id` silently loses subagent activity.
- `first_chunk_at` on `post_api_request` exists (TTFB = `first_chunk_at -
  started_at`) but is easy to miss; it is the only way to separate model latency
  from tool latency.

## Do not display a cost the host cannot price

`agent.usage_pricing.estimate_usage_cost` returns `status="unknown"` (and
`amount_usd=None`) for custom/aggregator models, while returning a real figure
for known ones. Test it with the actual model id before adding a cost column: a
blank or wrong dollar figure is worse than no column. Run it through the Hermes
venv python (`/usr/local/lib/hermes-agent/venv/bin/python`), not the system
python, which lacks `yaml`.

**Where the real prices actually are.** Custom OpenAI-compatible providers often
publish their own price list at `GET /v1/models`, one entry per model:

```json
"pricing": {"unit": "micro_idr_per_1m_tokens", "currency": "IDR",
            "input": 150000000, "output": 300000000,
            "cache_read": 21000000000, "free": false}
```

Parse the unit string, do not assume it: `micro_idr_per_1m_tokens` means the
value is millionths of the currency unit **per 1M tokens**, so divide by 1e6 to
get the per-1M-token price (150000000 -> Rp150/1M). A `"free": true` entry has
`null` rates and must render as zero, not as unknown. Convert to USD with a live
rate feed (`https://open.er-api.com/v6/latest/USD` returns `rates.IDR`); a
converted figure is a different claim from a billed one, so mark it (`~$`).

Sanity-check a parsed price against a model whose list price is known
independently (Claude Sonnet at Rp210,000/1M input is plausible for an IDR
reseller; Rp2.10 would not be). This catches an off-by-1e6 before it ships.

**Unknown price means show nothing, not zero.** Return `None` for an unpriced
model and print `?` with a count of unpriced calls, so the panel never implies a
cheaper session than reality. Backfilling old events is fine when both inputs are
real (recorded token counts times the provider's published rate); it is a
computation, not an estimate, but say so in the docs.

**Cache tokens must use the cache rate, and this is the easiest way to ship a
wrong number.** The provider reports `prompt_tokens` INCLUDING cached tokens. The
hook's usage dict is already canonical (`agent.usage_pricing.CanonicalUsage`):
`input_tokens` = UNCACHED prompt, `cache_read_tokens` = cached part,
`prompt_tokens` = their sum. Reading `prompt_tokens` as "input" and ignoring the
cache bucket bills cached tokens at the full input rate; on one real provider the
rates were Rp150/1M input vs Rp4/1M cache read (37x), which overstated a session
by 2x. Keep the buckets separate: display the full prompt, price the buckets at
their own rates. When the split is absent, leave the call unpriced rather than
billing it at the input rate, and report "no price" and "no cache split" as two
different reasons so the panel never blames the wrong one.

**Cross-check token totals against Hermes's own DB, not just your own feed.**
`$HERMES_HOME/state.db` has `sessions` and `session_model_usage` with
`input_tokens` / `output_tokens` / `cache_read_tokens` / `api_call_count`. Two
facts worth knowing: its `input_tokens` EXCLUDES cache (so `input + cache_read`
is the prompt total), and `estimated_cost_usd` is `0.0` with
`cost_status="unknown"` on custom providers, confirming the host cannot price
them. A mismatch between your feed and the DB is the fastest signal that a token
bucket is being read wrong.

Cache the fetch on disk with a TTL so the observer hot path never does network
I/O, and keep a stale cache rather than dropping to nothing when the fetch fails.

## Prove a regression test actually catches the bug

After writing the test, temporarily break the fix (e.g. replace the stall
predicate body with `return False`), re-run, and confirm the specific checks
fail. A test that passes both with and without the fix locks nothing. Restore the
file and assert the restore (`p.read_text() == src`) in the same script.

## Verifying a tmux launcher headlessly

Give the launcher a `--detach` flag (create the session, skip `tmux attach`),
then prove the layout with real captures:

```bash
./launcher.sh --detach
tmux list-panes -t <sess> -F '#{pane_index} #{pane_width}x#{pane_height} #{pane_current_command}'
tmux capture-pane -t <sess>:0.1 -p     # the panel
./launcher.sh --kill
```

Under `set -euo pipefail`, never write `[ cond ] && var=1` as a standalone line
— when `cond` is false the list exits 1 and kills the script. Use
`if [ cond ]; then var=1; fi`.

Use a `while [ $# -gt 0 ] ... shift` loop, not `for arg in "$@"`, whenever an
option takes a value: `for` cannot consume the following argument, so
`--layout v` silently falls through to the error branch while `--layout=v`
works.

## Split geometry: account for the tmux divider

A side-by-side split spends one column on the border, so the main pane is
`COLS - PANEL - 1`, not `COLS - PANEL`. A `MAX_PANEL=$(( COLS - 40 ))` guard
still leaves the main pane at 39. Subtract the divider:

```bash
MAX_PANEL=$(( COLS - MIN_MAIN - 1 ))
```

To test geometry for a screen size your current terminal does not have, run the
launcher *inside* a tmux pane of that size (a nested session; `unset TMUX`
first) and read the created session's `list-panes` output — `stty size` reports
the real pane, so this exercises the actual code path.

## Sidebar layouts (opencode-style)

When the ask is "a narrow task pane beside the main area, not a 50/50 split":

- Default to side-by-side at ~30–33% (opencode's ratio), a fixed column count
  or a percentage with floor/cap (e.g. min 22, max 46), plus a
  `MIN_MAIN` guard so the main pane never starves.
- Fall back to stacked only below ~64 cols; a horizontal split at 80 cols is
  still fine (54 / 25) but at 60 it is not.
- Make the renderer **width-adaptive**: below ~46 cols switch to a compact
  layout (current task on top, active tool + its brief in the middle, recent
  steps below), above it render the full timeline. One renderer with two modes
  beats two scripts.
- Wrap long tool arguments with a word-wrapper capped at ~3 lines; a single
  long command otherwise eats the whole sidebar.
