---
name: astroz-stack
description: Use when working on the /root/AstroZ worker stack.
---

# AstroZ stack (Hermes orchestrator + 4 worker CLIs)

Covers /root/AstroZ (renamed from /root/ai-team): Hermes as orchestrator plus a
claude/codex/opencode/omp worker pool behind 9Router, driven from a mobile-first
UI on :8799. Repo: https://github.com/bayz-dik/AstroZ (public). Hermes plugin:
`~/.hermes/plugins/astroz` (renamed from `ai-team`), tool `coding_team`,
slash commands `/team*`.

## Port architecture, get the direction right

Two ports, and clients point at the SANITISER, not at 9Router:

```
project / codex / opencode / omp
        |
        v
 :20129  proxy.py   <- SSE sanitiser, the "front door" for clients
        |
        v
 :20128  9Router    <- never dials out; does not know :20129 exists
```

- `:20128` = 9Router itself (`PORT = 20128` hardcoded in cli.js). Dashboard,
  `/api/*`, model sync, keys live here.
- `:20129` = `proxy.py`, forwards to 20128 and drops the DUPLICATE
  `data: [DONE]` terminator.
- 9Router is NOT listening on two ports. `grep -c 20129 cli.js` == 0.

Why the sanitiser exists: 9Router closes a stream with `data: [DONE]` twice.
opencode's parser dies on it. Verified: raw 20128 = 2x `[DONE]`; via 20129 = 1x.

Which client needs which port (all verified by running them):

| client   | :20128 raw        | :20129 sanitiser |
|----------|-------------------|------------------|
| opencode | `JSON parsing failed: Text: [DONE]\n[DONE]` | works |
| claude   | works             | works |

So "one port for everything" is only safe if that one port is the SANITISER.
One raw 9Router port + opencode = error.

Hermes deliberately stays on 20128 (direct). Rationale: it tolerates the double
`[DONE]`, gains nothing from the sanitiser, and it is the repair tool for this
stack, so it must not depend on the component most likely to be broken.

## Run it

```bash
/root/AstroZ/run.sh                 # 9Router + sanitiser + UI :8799
```

Keep it alive with the watchdog (probes real TCP, not `ss`, because `ss` reports
nothing in this proot container):

```bash
cd /root/AstroZ && /usr/local/lib/hermes-agent/venv/bin/python watchdog.py --loop --interval 30
```

It restarts only what is down. Verified: killing the UI brings it back in ~13s.

## One model for all five places

The UI is the single source of truth. Tab Model -> pick a row -> Terapkan ke
semua (`POST /api/gateway/model {model, apply_workers:true}`), or `POST /api/apply`.
One call rewrites all five:

| target   | file | endpoint written |
|----------|------|------------------|
| claude   | `~/.claude/settings.json` | 20128 (raw) |
| codex    | `~/.codex/config.toml` | 20129 |
| opencode | `~/.config/opencode/opencode.json` | 20129 |
| omp      | `~/.omp/agent/models.yml` | 20129 |
| hermes   | `$HERMES_HOME/config.yaml` | 20128 (direct) |

Ports differ per client; the MODEL ID is the same string everywhere. Port is the
door, model is who you ask for inside.

## Pitfalls (each cost real debugging time)

### PWD beats cwd for opencode, worker edits the wrong directory

opencode resolves its working directory as
`path.resolve(process.env.PWD ?? process.cwd())`, and PWD WINS.
`subprocess.Popen(cwd=...)` changes the process cwd but does NOT update the
inherited `PWD` env var, so a worker launched with `cwd=/root/AstroZ/workspace`
actually edited `/root/AstroZ`: files landed one level above the project, the
later test/git steps saw nothing, and the task still reported success.

Fix (in `orchestrator.run_worker`, right after building `env`): `env["PWD"] = cwd`.

Verify by checking WHERE the artifact lands, not that the task said done:

```bash
ls -la /root/AstroZ/workspace/<file>   # must be here
ls -la /root/AstroZ/<file>             # must NOT be here
```

### Apply used to move Hermes onto the sanitiser

`gateway.apply_hermes()` used `gw["api_base"]` (=20129) for Hermes, so every
press of Apply silently dragged Hermes behind proxy.py. It now uses
`hermes_base = gw.get("hermes_api_base") or base_url + "/v1"`. After any Apply,
assert Hermes is still on 20128: `grep -m1 base_url /root/.hermes/config.yaml`.

### Moving the directory breaks running processes (stale absolute paths)

`server.py` resolves `WEB = Path(__file__).parent / "web"` at import, and
`watchdog.py` resolves `ROOT` the same way. `mv` the tree and both keep pointing
at the OLD path string: the UI serves 404 on `/` and the watchdog cannot spawn
anything (its `cwd=ROOT` no longer exists). After any move:

1. kill the old uvicorn and watchdog (find PIDs from `/proc/*/cmdline`),
2. start `run.sh` again from the new path,
3. start the watchdog from the new path,
4. re-check `/api/state` and load `/` in a browser before believing it is up.

### Grep/kill self-matching

`pkill -f "uvicorn server:app"` matches the invoking shell too (its own command
line contains the pattern) and kills your session. Kill by PID discovered from
`/proc/*/cmdline` instead.

### The model list must include the model in use

`/api/gateway/models` used to read ids only from `gateway.models` in team.yaml.
That list can be empty (and 9Router's live catalog does not contain every
`oc-prod/*` id), so the model currently in use disappeared from the UI list and
the "teruji hidup" filter always showed 0 rows, a dead control. The endpoint now
builds ids from: current model, then `gateway.models`, then `model_meta` keys
(probe results live there), deduped in order.

### The model list needs BOTH 9Router endpoints

`/api/models` (dashboard, CLI token) is the rich catalog (name, caps, pricing)
but only covers providers whose credentials the dashboard knows.
`/v1/models` ([OI] surface, API key) is the authoritative callable id list and
includes providers the catalog misses (kenari-id, dvvai, cavoti-ai, kr, harbor,
code-craft). Reading only the first is why a working provider never appeared in
the picker. `Gateway.models()` now unions both, keyed by id, and backfills caps
by matching the model suffix. Verified: 2267 ids, 677 callable.

### Provider ids are endpoint uuids, not the prefix people know

`/api/models` entries carry `provider: openai-compatible-chat-<uuid>` while the
model ids use the short prefix. Only `/api/providers` pairs them
(`connections[].provider` + `providerSpecificData.prefix`). `Gateway.provider_map()`
builds that map and `sync()` stores it as `provider_names`; the models endpoint
and `models()` both translate through it. Never derive a provider label from the
catalog alone, and never from the model suffix (a model name can exist under
several providers).

### A dead gateway model makes every worker look broken

Symptom: tasks hang for minutes, the worker CLIs produce no output, and the UI
shows nothing useful. Cause found by probing `/v1/chat/completions` directly:
the selected model was answering HTTP 404 `No active credentials for provider`
(`oc-prod/*` went dead mid-session; `cavoti-ai` answered 503; `kr/*` 404). The
workers were waiting on a reply that would never come.

Check the model before blaming the stack:

```bash
curl -s -X POST http://127.0.0.1:20128/v1/chat/completions \
  -H "Authorization: Bearer <key>" -H 'Content-Type: application/json' \
  -d '{"model":"<id>","messages":[{"role":"user","content":"ok"}],"max_tokens":64}'
```

A 404/503 means pick another model (UI: Model pane -> Tes mana yang hidup ->
Terapkan). `kenari-id/deepseek-v4-1-flash` was the one that worked here, and it
is also what the user's Hermes runs.

### What each worker can actually do (measured)

All four are installed and working: [CC] 2.1.270, Codex CLI 0.154.0, opencode
1.18.30, omp 18.1.19. One compound task (read a file, write a derived file, run
`wc -l` into a third file) run per worker, each in its own directory, with a live
model:

| worker   | ok  | time  | artifacts |
|----------|-----|-------|-----------|
| codex    | yes | 34s   | both files, correct content |
| omp      | yes | 74s   | both files, correct content |
| opencode | yes | 95s   | both files, correct content |
| claude   | yes | 262s  | both files, correct content |

So they read files, write files, run shell commands, and report back in
Indonesian, each at its own speed (codex is ~8x faster than claude on the same
task, which is why `worker_cost` / `worker_order` matter). A `large` task with
four parallel subtasks built a 4-page static site (HTML, CSS, JS, SVG mark) in
`workspace/site/`.

What they do NOT have: working web search (omp and opencode both expose a search
backend that needs `EXA_API_KEY` / `UMANS_WEBSEARCH_PROVIDER`, neither set here,
so a worker asked to look something up answers from training data and says so).
They also only touch the workspace directory, never the user's own folders.

### Stall guard: progress chatter is not progress

A wedged CLI does not fail, it waits: omp prints `Working...` forever, opencode
sits in state D printing nothing, codex blocks on stdin. `run_worker` therefore
kills a worker whose last MEANINGFUL line is older than `workflow.stall_seconds`
(240). Counting any byte would disable the guard (omp's noise kept it alive).
On a stall the worker is not retried on other models: the result carries
`stalled: True`, `_worker_prompt` stops walking the model chain, and `_run`
escalates to the next workers in `worker_order`, up to `workflow.escalate_tries`
(2). Verified: with a dead model, omp stall -> opencode stall -> codex, task
finished in 100s instead of hanging for 900s.

Do not conclude from a stall that a CLI is broken. In this container every
stall traced back to the dead model (see above); with a live model all four
finish the same task. Check the model first, then the CLI.

### Reasoning models answer in `reasoning`, not `content`

`deepseek-v4-1-flash` and friends return `content: null` with the text in
`reasoning` / `reasoning_content`. `gateway.chat` accepts all three; a None text
used to crash the review step (`'NoneType' has no attribute 'splitlines'`) and
silently break planning. Also normalise the verdict: a model that echoes the
template back (`VERDICT: PASS|FAIL`) has not decided, so it is UNKNOWN.

### A task answer is not a work log

Worker stdout carries ANSI escapes, `> build · model` headers, `Working...` and
bare file echoes. `orchestrator.clean_output()` strips them (also used at emit
time for `phase="out"` so the activity boxes stay clean), and `_answer()` asks the
gateway model to turn the log into 1 to 4 plain sentences, falling back to
`best_answer_text()` when the gateway is unreachable. Without this the chat shows
`tests: PASS · review: PASS` and the user never sees the actual answer. Store it
as `task["answer"]` and expose it in `/api/sessions/{id}` messages.

### Chat sessions are task ids, not a second message store

`sessions.py` keeps only `{id, title, created, updated, tasks[]}`. The user turn
is the task prompt and the AstroZ turn is `task["answer"]`, so messages are
derived in `server._task_messages()`. A session title is the first message,
truncated. `POST /api/chat` creates or reuses the session, submits the task with
`session_id`, and attaches the task id.

### Filter server-side, not over the visible window

The UI shows `models[:300]`. Filtering "healthy only" in the browser over those
300 rows hid the one healthy model. `/api/gateway/models` now takes
`only_healthy=1` and filters before slicing. Rule: if the API paginates, filter
on the server.

### A filter that only waits for new events looks like an empty panel

Log tab: changing the filter cleared the panel and waited for the next SSE
event, so history vanished. Fix pattern: on filter change (and at boot) fetch
`/api/events/recent?limit=N&kind=...`, render it, remember the max event id, and
have the SSE handler skip ids already rendered. Any "filter" over a live stream
needs that history load, or it reads as broken.

### `hostname -I` first field can be IPv6

`run.sh` printed `http://2400:9800:...:8799/` as the phone URL. Pick the first
IPv4 instead:
`hostname -I | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -1`.

### Plugins (MCP) and GitHub skills, all from the UI

`plugins.py` owns both. Verified formats per CLI (add one server, then read the
config back; do not guess):

| worker | file | shape |
|---|---|---|
| claude | `~/.claude.json` | `mcpServers.<name>` (or `claude mcp add --scope user`) |
| codex | `~/.codex/config.toml` | `[mcp_servers.<name>]` |
| opencode | `~/.config/opencode/opencode.json` | `mcp.<name>` `{type: local, command: [...]}` |
| omp | `~/.omp/agent/mcp.json` | `{$schema, mcpServers.<name>}` (agent-plugins 1.0.0 schema) |

Skill packs: clone into `~/.astroz/skills/<slug>`, then symlink every folder
holding `SKILL.md` into `~/.claude/skills`, `~/.agents/skills`,
`~/.codex/skills`, `~/.omp/agent/skills`, `~/.omp/skills`. Those are the
folders the four CLIs actually scan. `orchestrator._worker_brief` lists the
installed skill names in every task prompt, which is what makes a worker use
them without being told. Verified end to end: `anthropics/skills` installed
from the UI (20 skills), then a chat task used the `docx` skill and produced a
valid `ringkas.docx`.

Long work (clone, package download) runs as a background job in `JOBS` and is
polled from the UI via `/api/jobs/<id>`, so the HTTP request never waits.

### First MCP connection fails unless the package is warmed first

Measured: a fresh `npx`/`uvx` MCP server fails with `CONNECTION_CLOSED` or
hits the 30s timeout on first connect, because the package downloads during
that connect. `mcp_panaskan()` runs the command once with stdin at DEVNULL
before writing it as an active plugin. Two container facts came out of this:
`uvx` lives in `~/.hermes/bin` and is NOT on the worker PATH (omp logged
`Executable not found in $PATH: "uvx"`), and `uv` fails to install with
hardlinks here (`Operation not permitted`), so `UV_LINK_MODE=copy` must be set
in the environment used for plugin installs.

### A dead fallback model costs three timeouts per task

Gateway answers `unrecognized_model` for ids that are still in
`fallback_models`. The chain then walks several dead models, one timeout each,
before failing. `orchestrator._model_ditolak` detects that answer,
`tandai_model_ditolak` records the id in `gateway.model_rejected`, and
`model_chain` skips those ids. The model list is pruned again on a successful
health probe, so a model that comes back is usable immediately.

### Two class names that silently broke the buttons

`.baris-data .kecil` (13px, muted grey) also matched `class="tombol kecil"`,
so every small button got grey text on the terracotta fill: 1.35:1 contrast.
Text helpers must not share a token with button modifiers; the text class is
now `.teks-kecil`. Same class of bug: `.kejadian .pesan` collided with
`.pesan` (the chat message block), which made 280 log rows count as chat
messages and pinned the empty screen off. Log text is `.pesan-log`.

### A flex child with nowrap text widens the whole page

`.chat .kepala-chat h1` had `flex: 1` plus `overflow: hidden` and
`white-space: nowrap`. Without `min-width: 0` the flex item refuses to shrink
below its content width, so the page laid out at 749px inside a 375px viewport:
horizontal scroll on the phone, and every later measurement taken on a page
that had already blown out. Fix is `min-width: 0` on the flex item (and
`grid-template-columns: minmax(0, 1fr)` instead of `1fr` for the same reason in
grid). Verify with `document.documentElement.scrollWidth - clientWidth == 0`,
and bisect a blowout by hiding each ancestor in turn and re-reading
`scrollWidth`.

### Measure contrast on the composited background, in a real browser

A contrast audit that reads `backgroundColor` without alpha reports false
failures: the selected session row is `rgba(201,100,66,0.08)` over paper, and a
naive reader compares text against the raw translucent value. Walk every text
node, composite the ancestor background layers bottom-up, and skip nodes whose
`color` is `rgba(0,0,0,0)` (gradient-clipped text such as the shimmer). Real
findings from doing it properly: `#87867F` from OpenDesign is only 3.47:1 on
paper, and a meta grey that passes on paper fails at 4.43:1 on the tinted row.

### 1000-1199px is not wide enough for three columns

At 1100px the chat column was 456px and the activity column squeezed every
label onto its own line. `body.sempit-lebar` (set from a `matchMedia` listener
next to `susun()`) hides `.aktivitas` and re-shows the `.hanya-hp` drawer
buttons. Do not just raise the three-column breakpoint: the drawer needs the
buttons back at that width too.

### The Claude Code palette lives inside the CLI binary

`@anthropic-ai/claude-code` ships one Bun binary with the theme table as
strings. Read it without running it: `data.find(b'rgb(208,180,255)')` anchors
the colour table, then print the surrounding few kB. Found this way: accent
`#D97757` / `#D77757`, shimmer `#F59575`, green `#69DB7C`, yellow `#FFC107`,
red `#FF6B80`, dark surfaces in the `rgb(38,38,38)` family. The full token
table is NOT stored as literals, so `#262624` / `#30302E` come from the known
dark theme, not from the binary; say so in `evidence.md` instead of implying
the extraction covered everything.

### Verify, don't trust the event log

A task can log `auto-commit ok` while nothing was committed (the file was outside
the repo). Always confirm the artifact and the commit:

```bash
cd /root/AstroZ/workspace && git log --oneline -2 && git show --stat HEAD
```

## Layout: `.isi` has two children, and only sometimes two columns

`.aktivitas` is NOT in `.isi` in the HTML. `susun()` moves it:

- `>=1280px`: `.isi` = `chat`, `#wadah-aktivitas` (empty, `hidden`), `.aktivitas`
  -> columns `minmax(0,1fr) var(--lebar-aktivitas)`.
- `<1280px`: `.aktivitas` goes back inside `#wadah-aktivitas`, which lives in
  `#lembar-alat` (menu garis tiga). `.isi` = one column, `1fr`.

Rules that each cost a real bug:

- The wrapper stays in the sheet in HTML. Never `isi.insertBefore(wadah, null)`:
  an extra grid child pushes `.chat` into column 1, so at >=1280px the chat is
  pinned to 292px on the left and the panel takes 780px in the middle.
- A `display:none` grid child does not count toward the columns, so `hidden` on
  the wrapper is the mechanism that keeps `.isi` two columns at >=1280px. It
  must therefore be `hidden = layar.aktivitas.matches`, NOT
  `!(alat.matches && !aktivitas.matches)` (the old form left the wrapper visible
  at 1000-1279px, giving a dead 292px column next to the chat).
- `@media (min-width:1000px) and (max-width:1279px)` must not put
  `--lebar-alat` in the template: the alat list has no column in the markup any
  more. Keep `.aktivitas { display: flex }` there (it is inside the sheet) and
  `#wadah-aktivitas { display: block }`.
- `pindahAlat()` must hide only `#badan-alat > .panel`. Without the `>`, the
  selector also matches `#panel-proses/berkas/catatan/model`, which are nested
  inside `#alat-aktivitas`, so the section `pindahTab()` just revealed is hidden
  again and the panel looks empty.
- Branch on `layar.aktivitas.matches` first, then open the sheet. Opening the
  sheet while the panel is the right column shows an empty sheet.
- Grid tracks that hold log text need `minmax(0, 1fr)`: plain `1fr` refuses to
  shrink below its content, so one long log line widens the whole page.

Verify in the browser at 375 / 1100 / 1440px: `getComputedStyle(.isi)` template,
child widths, and `documentElement.scrollWidth - clientWidth == 0`.

## Worker list, install, and the `/api/workers` shape

- `/api/workers` returns `{workers: [...], cfg: {<key>: {enabled, model}}}`. The
  worker objects have `key`/`label`/`installed`/`version`, NOT `name` and NOT
  `available`. Using `w.name` made probe/enable calls hit `/api/workers/undefined`
  and the row render as "tidak ada" for installed CLIs. `model` and `enabled`
  live in `cfg`, so the UI has to merge them itself.
- `kirim(url)` with no body sends no JSON header, so FastAPI answers 422 for a
  `payload: dict` route. Always pass `{}`.
- Install from the UI: `npm install -g <paket>`. Measured on this device,
  `@oh-my-pi/pi-coding-agent` took 5.7 minutes (codex/claude/opencode are much
  faster), so it must stay a background job. It reported `ok` even while npm had
  replaced `/usr/local/bin/omp` with a temporary `.omp-XXXX` symlink and no final
  name: probe then said "not installed" although the package was fine.
  `adapters._cari_di_prefix()` covers this (looks for the final name, then the
  `.name-*` temp pattern, then links it into `/usr/local/bin`).
- Do not offer "pasang ulang" for installed workers: a hung `npm install -g`
  gives a button that runs for hours. The install path is for missing CLIs only.
- `omp` version matters here: 18.1.21 crashes on this device (`Bun has crashed` /
  Bus error while loading `pi_natives.linux-arm64.node`), 18.1.19 works. Probe
  reports `installed=True` with a garbage `version` (Bun banner) and a long
  `error` in that state. If omp misbehaves, pin it back to 18.1.19 before
  blaming the stack.

## Secrets and process hygiene

- The UI server binds `0.0.0.0`, so anything in `/api/state` is readable by
  every host on the LAN. The gateway `api_key` is stripped there; only
  `has_key` goes out. Keep it that way.
- Killing by pattern is dangerous twice over: `pkill -f "uvicorn server:app"`
  matches the invoking shell, and so does `for d in /proc/*; case "$cmd" in
  *uvicorn*)`. Kill by PID found in `/proc/*/cmdline` from `execute_code` with
  `os.kill`, and skip any cmdline containing `hermes`.
- After the `/root/ai-team` -> `/root/AstroZ` rename the venv's `pip` shebang
  still pointed at the old path, so `run.sh` reported missing packages although
  they were installed. Recreate it: `rm -rf .venv && python3 -m venv .venv &&
  .venv/bin/pip install -r requirements.txt`.

## Verifying the UI in a real browser

The browser daemon drops the tab between calls (`location.href` becomes
`about:blank`). A single `browser_exec` call must re-navigate and wait for a
known element before measuring:

```python
for _ in range(25):
    if js("!!document.querySelector('.isi')"): break
    time.sleep(1)
```

Also call `cdp("Network.setCacheDisabled", cacheDisabled=True)` and append a
cache-busting query: otherwise `getComputedStyle` and `document.styleSheets`
keep reporting the previous `app.css`, and a fixed rule looks unfixed. Confirm
which rule wins by walking `document.styleSheets` for the media query.

## Live work strip: the user must SEE workers working

The requirement that drove it: a running task must be visible without opening
any menu. The old design hid progress behind menu garis tiga -> Proses kerja, so
while claude/codex/opencode/omp worked the screen looked idle.

- `GET /api/tasks/running` returns `{running: [{id, prompt, size, model, created,
  session, tahap, pekerja[], langkah[]}]}`. `pekerja[].aktif` is derived from each
  worker's LAST event: a phase not in `end`/`stall`/`error` means still working.
  The assignment list (`t["workers"]`) alone cannot tell who finished.
- UI: `#strip-kerja` sits under the header, `hidden` when nothing runs. Polls
  every 2.5s while working, 6s while idle; the elapsed clock ticks every second
  locally. Header = `sedang bekerja` + worker chips + elapsed + task id; clicking
  it expands the last steps in place (no sheet, no menu). It hides itself when the
  task ends. Measured: appears ~6s after submit, gone on done, 44px tall at
  375px, no horizontal overflow.
- Route order matters: `/api/tasks/{tid}` declared BEFORE `/api/tasks/running`
  swallows `running` as a task id and answers 404 `not found`. Fixed paths must
  be registered before dynamic ones. Symptom to recognise: the endpoint answers
  correctly in a direct `import server` test but 404s over HTTP.

## Restarting the UI: identify the process by cwd, not by the word "hermes"

The UI runs sometimes on `/root/AstroZ/.venv/bin/python`, sometimes on
`/usr/local/lib/hermes-agent/venv/bin/python`. Identify it by cmdline (`uvicorn`
+ `server:app`) AND `os.readlink('/proc/<pid>/cwd') == '/root/AstroZ'`.
Filtering out processes whose command line contains `hermes` skips the UI itself
(it uses the Hermes venv), so the old server keeps the port and the new one dies
with `[Errno 98] address already in use` while still answering requests.

Kill by PID from `/proc/*/cmdline` via `os.kill` in `execute_code`, then verify
with `GET /api/tasks/running` returning `{"ok":true...}`. An open port proves
nothing: a stale process keeps it open. Stop `watchdog.py` first if it is
running, or it races you to respawn the old server.
- Contrast: measure the strip separately. `--tinta-meta` on the warm strip
  background is only 4.40:1 in light mode, so the worker chips, the elapsed
  clock and the step times use `--tinta-2` / `--tinta-lembut` (8.71 / 5.27 light,
  8.41 / 5.50 dark). Keep the accent on the chip ring, not on its text.
- Verify the whole matrix after touching the sheet or the strip: at 1440px
  Berkas/Catatan/Model must switch the RIGHT column (`#aktivitas .panel`) and
  must NOT open the sheet; Kerja/Pekerja/Obrolan open the sheet. At 1100px and
  375px every section opens the sheet with `#badan-alat > .panel` = `alat-aktivitas`.
- Reload during a run works: after F5 the strip reappears with the running
  worker, because it reads `/api/tasks/running` rather than in-page state.
- Animations (`dot denyut`, ticker) are killed by the global
  `prefers-reduced-motion` rule. Emulated `no-preference` does not always
  restore them in the CDP session; do not chase that as a bug.
- When driving the UI from `browser_exec`, wait for readiness (`typeof keadaan
  !== 'undefined'` and the model pill filled) before dispatching a synthetic
  submit: right after navigation the handler is not attached yet and the click
  is silently lost.

## Useful checks

```bash
for p in 20128 20129 8799; do (echo > /dev/tcp/127.0.0.1/$p) 2>/dev/null && echo "$p OPEN" || echo "$p CLOSED"; done
curl -s http://127.0.0.1:8799/api/state
curl -s "http://127.0.0.1:8799/api/gateway/models?limit=5&only_healthy=1"
for w in claude codex opencode omp; do curl -s -m 90 -X POST http://127.0.0.1:8799/api/workers/$w/probe; echo; done
```

Model list: use the UI's "Tes mana yang hidup" to filter, not every gateway model
answers. `kenari-id/deepseek-v4-1-flash` is the one that works here.

## UI: chat first, tools behind the hamburger

The UI is a chat app shaped like the Claude mobile app. Three surfaces that are
deliberately NOT merged (the user rejected the earlier single-feed version):

- **chat column** (`#kolom-chat` inside `#alur`): one `.pesan` block per turn,
  `Kamu` bubble on warm surface, `AstroZ` answer as plain text. Below each answer
  a `.skrip` line summarises plan/worker/test/review steps. The column scrolls
  itself and stays pinned to the newest turn. `.pesan.aku .isi-pesan` is the
  warm block; do NOT put the answer in a bubble, that is what made the old UI
  look stacked.
- **empty screen** (`.kosong-hero`): star glyph, time-based greeting, one line
  of help, composer below. Absolutely positioned over the chat area, so
  `#alur` gets `visibility: hidden` while it shows.
- **tool menu** (`#lembar-alat`, opened by the hamburger): Obrolan, Plugin MCP,
  Skill dari GitHub, Berkas dan tes, Catatan kejadian, Model dan pekerja. One
  section at a time. Berkas/catatan/model move the SAME `#aktivitas` node into
  the sheet (or close the sheet and flash the right column at >=1280px); never
  duplicate those panels, a copy goes stale.
- **composer** (`.kotak-isian`): one bordered rounded box holding the textarea
  plus one button row: `+` (attachments, plugin, skill), model pill, size select
  (hidden below 560px), send. Keep it to one row.

Files: `web/index.html` (shell), `web/app.css`, `web/app.js`, served by the
catch-all `GET /{path:path}` in server.py. No build step. All copy Indonesian.

Design source of truth: `design-systems/claude-code/` in the repo holds
`DESIGN.md` (rules), `tokens.css` (values), `source/evidence.md` (where every
value came from). Read it before touching colours. `DESIGN.md` at the repo root
now only points there; the old Swiss-print direction is dead.

Design facts (all verified, re-check after touching colours):

- Two themes, same roles. Light: paper `#FAF9F5`, surface `#FFFFFF`, warm
  surface `#E8E6DC`, ink `#141413`, ink-2 `#3D3D3A`, soft `#5E5D59`, meta
  `#6A6963`, line `#E8E6DC`, line-strong `#8E8C84`. Dark: `#262624`, `#30302E`,
  `#3E332E`, ink `#F5F4ED`, soft `#B0AEA5`, meta `#A2A099`, line `#3E3E3B`,
  line-strong `#7C7A73`.
- One accent, terracotta. It needs THREE values, not one: `--aksen` for marks
  and rings (`#C96442` / `#D97757`), `--aksen-isi` for a button fill (light
  `#B4553A`, so ivory text on it is 4.63:1), `--aksen-teks` for accent text
  (light `#A8492F` 5.45:1, dark `#E08B6E` 5.09:1).
- State colours: done `#146C2E` / `#69DB7C`, running `#A8492F` / `#FFC107`,
  error `#B53333` / `#FF6B80`. Focus ring `#2563EB` / `#3898EC` is the only
  cool colour in the system.
- Type: Fraunces 500 for headings, Inter for prose, JetBrains Mono for time,
  counts, code and file contents. Self-hosted in `web/fonts/` with `fonts.css`
  (OFL licences beside them); the Google Fonts `<link>` is gone on purpose.
- Depth is a ring (`0 0 0 1px`), never a drop shadow except `--naik` for the
  floating message. Radius 8/12/16px. `alert()`/`prompt()` are banned: the UI
  uses `pesanSingkat()` (the toast). Em dashes are banned everywhere in copy.
- Tap targets >=44px on narrow screens (the composer buttons and the textarea
  were 32 to 36px and had to be raised), no horizontal overflow at 375px,
  keyboard focus visible on every control, Escape closes the sheets and the
  overflow menu.
- Animation only marks work in progress (the `.bars` indicator, the ticker line,
  the README banner), and stops when the task ends. `prefers-reduced-motion`
  kills all of it.
- Verify with the browser before claiming done: send a real message, watch the
  ticker, the answer replacing the working state, and the activity drawer; then
  check 375px and 1280px, keyboard Tab order, and the console for errors.
  A real task through the UI is the only end-to-end proof: `workspace/halo.txt`
  on disk plus `task["answer"]` in the bubble means the chain worked.
- Publishing: `.gitignore` excludes `team.yaml` (holds the 9Router key),
  `.9r_token`, `runtime/`, `logs/`, `workspace/`; `team.yaml.example` ships
  instead. Verify from a fresh clone with `git grep` over all revisions.
- Attachments: the `+` button uploads to `workspace/lampiran/` through
  `POST /api/upload` (base64, no multipart lib) and the prompt gets the path, so
  a worker can read it with the `lihat` tool.
- `POST /api/chat` with `baru: true` creates a NEW session. Without it the UI
  reuses whatever session id it holds, which is how every message used to pile
  into one thread. A new chat is the default the user asked for.
