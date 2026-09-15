---
name: coding-agent-pool-orchestration
description: "Orchestrate Claude/Codex/OpenCode/OMP as one worker pool."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Orchestration, Coding-Agent, Worker-Pool, Gateway, Multi-Agent]
    related_skills: [claude-code, codex, opencode, hermes-plugin-authoring]
---

# Orchestrating a coding-agent worker pool

Use when the ask is "one UI/task queue drives several coding CLIs" — a worker
pool of Claude Code / Codex / OpenCode / OMP behind a single LLM gateway, with
planning, parallel execution, review, and tests. Each CLI is an independent
program with its own config format and its own non-interactive mode; the job is
to make them interchangeable without flattening their differences.

Shape that works: **gateway → per-worker adapter → orchestrator → event feed →
UI**. One process owns config, one owns execution, one owns events. A second
front end (a Hermes plugin, a CLI) talks to the same HTTP API instead of
re-implementing any of it.

## Procedure

1. **Inventory what is already installed before building anything.**
   `for c in claude codex opencode omp; do printf '%s: ' $c; command -v $c || echo NO; done`
   Then `--version` each. Missing binaries are an install step, not a design
   constraint — do not design around a worker you have not installed.
2. **Inspect each worker's real config path and non-interactive invocation.**
   Do not assume they share an API. Run `--help` and read the config file it
   actually reads. See `references/worker-adapter-matrix.md` for the verified
   matrix (paths, keys, invocation flags) — copy it, then re-verify with
   `--version` and `--help` because these CLIs change.
3. **Write one adapter per worker** with the same four methods:
   `probe()` (installed? version? path?), `apply(gateway)` (rewrite that
   worker's config), `env(gateway, model)` (env vars the CLI reads),
   `command(task, model, cwd)` (argv for one non-interactive run). Keep
   everything worker-specific inside the adapter; the orchestrator only ever
   calls these four.
4. **Drive the gateway from one config, not per worker.** Store
   `base_url` / `api_base` / `api_key` / `model` once; `apply_all()` fans it out
   to every adapter. The user changes the model in one place.
5. **Stream worker stdout into one append-only JSONL event feed** and fan it out
   to the UI over SSE. Tag every event with `task`, `worker`, `phase`
   (`start`/`out`/`end`/`retry`/`fallback`) so the UI can filter without
   parsing prose.
6. **Escalate failures instead of ending the task**: model fallback chain →
   retry → different worker. See "Failure handling" below.
7. **Verify with a real task that changes real files**, then read the diff,
   the test result, and the review verdict back from the API. A pool that only
   passes a "say OK" smoke test has not been tested.
   A full task takes minutes and a multi-worker `large` task takes tens of them,
   so run the end-to-end verification as ONE tracked background process (a wait
   loop that polls the task status and exits when it leaves `running`) rather
   than a foreground sleep loop per check. For progress while it runs, filter
   the append-only event feed by task id instead of re-querying endpoints: the
   feed already carries `plan`/`worker`/`discuss`/`test`/`review` events with
   `phase`, so one read reconstructs the whole run. Report the outcome from the
   task record (status, test ok, review verdict, worker list) plus `git status`
   — never from the worker's own prose, which claims success it may not have
   delivered.

## Failure handling (this is most of the value)

- **Fallback chain, not retry-on-the-same-model.** One saturated upstream turns
  into a dead task. Build an ordered model list (selected → configured
  fallbacks → models that answered the last health probe) and walk it per
  subtask; a 429 is a routing problem, not a capability problem.
- **Classify before retrying.** Retry only transient conditions (429/503/502,
  "all providers busy", rate limit, timeout, connection reset). Retrying a
  permanent error (401 invalid key, 404 model not found, bad request) just
  burns the budget and hides the real cause.
- **Escalate to a different worker** when every worker on a subtask failed —
  different CLIs route through different providers, so the second one often
  succeeds where the first was blocked.
- **A failing test is a work item, not an end state.** On red tests, feed the
  failing output back to a worker that has not touched the task yet and re-run;
  report PASS only if it passes afterwards.
- **Never let the planner block the task.** If the planning LLM is unreachable,
  fall back to a heuristic single-subtask plan and keep going.

## Cost-tiered worker selection

Worker CLIs differ by an order of magnitude in both latency and price (tens of
seconds vs minutes; cents vs ~half a dollar per request), so make the default
assignment cheapest-first and configurable, not hardcoded:

```yaml
workflow:
  worker_order: [omp, opencode, codex, claude]   # subtask assignment order
  worker_cost:  {omp: 0.01, opencode: 0.02, codex: 0.05, claude: 0.45}
```

- **Subtask assignment** follows `worker_order`. This user's standing preference
  is cheapest-first by default — put the expensive CLI last so a routine edit
  does not cost a frontier request.
- **Repair rounds** (red tests, review FAIL) pick the cheapest worker that has
  not touched the task yet: a small fix is not worth the expensive CLI.
- **Escalation keeps the full pool.** Cheap-first is a preference, not a
  restriction — when every cheap worker fails, fall back to the whole installed
  pool so the expensive worker is still reachable.
- **Surface the ranking in the UI** (`#1 pick · ~$0.01/run` per worker card). An
  invisible ordering makes the user think routing is random.
- Keep the cost numbers in the config, not in code: they are the user's estimate
  of their own gateway's pricing and will drift.

## Task queue durability

The task store is the UI's and the plugin's shared state, so keep it on disk, not
only in a process dict:

- Persist a slim record per task (id, prompt, status, size, workers, plan,
  results, test, review, summary, timestamps) to `runtime/tasks.json` on submit
  and on finish. Restarting the orchestrator otherwise empties the task list the
  user is watching.
- On boot, load that file and rewrite any task still marked `running` to
  `interrupted`. A task that was mid-flight when the process stopped is not
  running any more, and a permanently "running" row makes the UI lie.
- Keep the event feed (JSONL) and the task store separate: the feed is an
  append-only log for replay, the task store is current state.

## Keeping the multi-process stack alive

Gateway + framing proxy + UI are separate processes and each can die alone while
the others stay healthy; from outside the symptom is identical ("worker produced
nothing", "UI unreachable") and nothing says which layer went. Run one
idempotent supervisor instead of hand-checking ports:

- Probe each service's port **and** its health path (`/api/health`,
  `/api/state`) — a bare TCP connect passes for a process that is wedged.
- Restart only the service that is down, in dependency order (gateway → proxy →
  UI), waiting for each port before the next.
- Make it re-runnable (`--status` for report-only, `--loop --interval` for
  supervision) and write a small JSON report per pass, so the last check is
  inspectable after the fact and a "fixed" verdict is provable.

## Pitfalls

- **A finished task is not a commit.** Workers leave the project tree dirty; a
  PASS verdict plus green tests still means uncommitted files. Expose an explicit
  commit action (`POST /api/git/commit` + a UI button) rather than auto-committing
  under the user, and after a task read `git status` / the diffstat to confirm
  what actually landed before reporting the work as done.
- **Claude Code refuses `--dangerously-skip-permissions` as root** unless
  `IS_SANDBOX=1` is set. Set it (plus the auth env vars) in the adapter's `env()`
  so unattended runs do not die on the guard.
- **Pass the model explicitly to every worker; never rely on the config file's
  model.** Claude Code appends a context suffix (e.g. `[1m]`) to the model read
  from `settings.json`, and the gateway rejects the decorated id. Explicit
  `--model` also makes per-subtask model overrides possible.
- **Codex rejects `wire_api = "chat"`** on current versions — use
  `"responses"`. Check the CLI's own error text: it names the accepted value.
- **Codex's bwrap sandbox cannot create its mounts inside proot/Termux-style
  containers**, so every sandboxed read/write fails and the worker narrates its
  own confusion for minutes. Give it `--dangerously-bypass-approvals-and-sandbox`
  and rely on the per-worker working directory for isolation.
- **A bare `python -m pytest` is the wrong interpreter** on PEP-668 systems
  (and in the Hermes venv, which has no pytest). Detect a project `.venv` and
  rewrite the leading `python`/`python3` token to it before running tests, and
  prefer the detected command over whatever the planner proposed.
- **`git diff` is empty when workers create new files** — the common case — so a
  reviewer shown only the diff reviews nothing. Summarize tracked diff *plus*
  the contents of untracked files.
- **Keep bulk caches out of the human-edited config file.** A synced model list
  plus per-model metadata turns a 40-line YAML into thousands of lines that are
  re-parsed on every request. Store them beside it (`runtime/*.json`) and merge
  on load.
- **A router may return several concatenated JSON objects** in one response body
  (retry/fallback concatenation), which makes strict `json.loads` fail on a
  perfectly good answer. Parse with `JSONDecoder().raw_decode` and use the first
  object; a health probe using `json.loads` reports working models as broken.
- **A model list is not a list of working models.** Many entries have no active
  credentials or a saturated upstream. Probe with a 4-token request before
  offering them, and let the UI filter to models that answered.
- **A gateway may emit a duplicate SSE terminator.** Verified: 9Router ends a
  stream with `data: [DONE]` **twice**; lenient clients ignore it, opencode dies
  with `JSON parsing failed: Text: [DONE] [DONE]` and returns no answer at all.
  Fix it once, in front of every worker, with a small pass-through proxy that
  forwards the stream and drops the second terminator — cheaper and more faithful
  than patching each CLI. Route **only the strict-parser clients** through that
  proxy: a client that already tolerates the duplicate ([CC], Codex, OMP, Hermes
  itself) gains nothing from the hop and inherits the proxy as a new way to fail.
  Keep both URLs in config (`api_base` = proxy, `upstream_base_url` = gateway)
  and say which client uses which.
- **The framing proxy is a single point of failure; probe its port first.** When
  a worker returns no answer while the gateway itself answers, the usual cause is
  the proxy being down: every client pointed at it fails identically and the
  gateway's own logs show nothing wrong. Check the proxy port before
  re-configuring any worker, and keep the stack's supervisor watching it.
- **Two ports on this stack are intentional — identify the owner before
  "fixing" a port.** A gateway often bakes its default port into its own bundle
  (9Router ships `PORT = 20128`, `--port` overrides it) and the sanitiser is a
  separate process on its own port, so a report that "the gateway moved to
  :20129" is almost always the proxy mistaken for the gateway. Read the owning
  process per port (`/proc/<pid>/cmdline` plus the launcher script) and reply
  with that measured fact, in the user's own language, instead of moving a port
  and re-configuring every client to match a misread report.
- **A config value that is a list cannot be patched with dotted-key `config set`.**
  Hermes stores `custom_providers` as a **list** of `{name, base_url, key_env}`;
  `hermes config set custom_providers.<name>.base_url` exits 0 and changes
  nothing. Rewrite the matching entry in the YAML directly, and prefer an inline
  `api_key` over `key_env` (a `key_env` name that is not exported silently 401s).
  After any config write, re-read the file and print the value — "exit 0" is not
  "applied".
- **Green tests are not a met task.** A worker can satisfy its own test while
  violating the request (real case: "write exactly X, no trailing newline" — the
  worker added the newline and wrote a test that passed anyway). Treat a review
  FAIL as a work item too: hand the reviewer's issue list to a different worker,
  then re-review — but only when files actually changed, or it loops on nothing.
- **Do not hardcode worker flags in the smoke test.** A test that hardcodes
  `claude -p ...` without the adapter's `IS_SANDBOX=1`, or `omp --model <id>`
  without the provider prefix, reports FAILs that are test bugs and sends you
  debugging workers that work. Generate command and env from the same adapter
  code the orchestrator uses.
- **A smoke test must state an unambiguous requirement.** An end-to-end smoke
  prompt like "a file containing exactly X" leaves the reviewer free to FAIL on
  a trailing newline, so the suite reports a product bug that is really a
  test-authoring bug. Word the smoke requirement byte-exactly and have its
  check script assert that (compare against `printf`, not a loose match); a
  smoke test you have to interpret is not a regression test.
- **Route config writes through the owning CLI** (`<tool> config set key value`)
  when the tool owns its schema, and keep a direct-write fallback. Check the
  file after writing: a CLI that silently ignores an unknown key leaves the old
  value in place and the change looks applied.
- **Cheap-first routing can collapse a parallel plan onto one worker.** If the
  planner puts every subtask on the same cheapest worker, the parallel batch and
  the discussion round become theatre: one CLI wrote everything and has nobody
  to disagree with. Spread subtasks round-robin across the chosen pool whenever
  a batch would otherwise use a single worker; inter-agent discussion is only
  worth its cost when different CLIs actually did the work.
- **Long-lived background servers**: launch them as tracked background
  processes (a shell-level `nohup … &` inside a foreground command is refused),
  and stop them with `pkill -f "<module>:app"` — killing by the recorded pid
  leaves the child uvicorn/node process holding the port.
- **Probe listening state with a real TCP connect, not `ss`.** Inside
  proot/Termux-style containers `ss` reports no listening sockets at all, so a
  readiness check built on it declares every healthy service down and a watchdog
  on top of it restarts a working stack in a loop. Use
  `socket.create_connection((host, port))` (or `>/dev/tcp/host/port`), plus an
  HTTP GET on the service's own health path for a real liveness signal.

## Working with the user's model gateway

- Read the model list, the provider connections, and the API key from the
  gateway's own management API/database rather than asking the user to paste
  them, when the gateway is local.
- A local gateway that gates `/api/*` behind a token derives it deterministically
  (e.g. `sha256(machine-id + fixed-salt + cli-secret)[:16]`); compute it from the
  files it reads instead of guessing or disabling auth.
- Report which models actually answered. A UI that shows 1500 models and no
  liveness signal makes the user debug the gateway by hand.

## Supporting files

- `references/worker-adapter-matrix.md` — verified per-CLI config paths, keys,
  env vars, and non-interactive invocation flags; read it before writing an
  adapter and re-verify the flags against the installed version.
- `references/gateway-sse-sanitizer.md` — recipe for the pass-through proxy that
  repairs a gateway's stream framing (duplicate `[DONE]`, bad terminators) for
  every worker at once, plus how to verify it with a raw streaming request.
