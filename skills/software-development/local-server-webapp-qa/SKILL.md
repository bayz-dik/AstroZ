---
name: local-server-webapp-qa
description: "Use when building, running, or testing a local Flask/server web app."
version: 1.0.0
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [qa, flask, curl, web, localhost, verification]
    related_skills: [static-webapp-qa]
---

# Local Server-Backed Web App QA & Iteration

Class of task: the user says "lanjutin / continue / fix / test <app>" for an app that runs as a
server process (Flask, FastAPI, WSGI, `python app.py`) and keeps its state server-side in local
files (CSV/JSON) or sessions (OAuth tokens, flash messages). The deliverable is a working app plus
a report of what was actually exercised — not a description of what should work.

Distinct from `static-webapp-qa` (no-build HTML/CSS/JS driven through `browser_exec`): here the
browser adds nothing, because every behaviour you need to prove is reachable over HTTP and the
interesting state is on disk. Verify with `curl`. Ready-to-paste probes: `references/curl-route-recipes.md`.
Provider-specific depth (Gmail scopes, batch fetch, read-receipt/tracking-pixel limits, reading
replies): `references/gmail-api-notes.md`.
CSV/file ingestion and sync robustness (delimiter, encoding, filename case, edit-conflict guard):
`references/csv-ingestion-robustness.md`.
Exposing the localhost server to the internet (cloudflared quick tunnel, port probing/fallback):
`references/public-tunnel.md`; ready-to-copy launcher: `templates/launcher-with-tunnel.sh`.
Publishing the repo to GitHub without leaking secrets/data (gitignore, staged-set and content scans,
remote-side verification): `references/publish-secret-hygiene.md`.
Preparing an image asset the user hands you (alpha cut, palette recolour, per-theme files):
`references/asset-prep.md`.

## Rule 0 — Never trigger the real, irreversible side effect yourself
When the app performs an outbound/irreversible action (sending email, posting, charging, publishing),
the user performs the real action; you do not. This is a standing instruction for this class and the
user states it explicitly.
- Build a DRY-RUN mode FIRST, keyed off an env var (e.g. `APP_DRY_RUN=1`). In dry mode the send path
  logs a simulated result and touches no provider API and no OAuth. Show a visible banner in the UI.
- Do all testing through dry mode. Dry mode needs no credentials, so do not ask for any or run an
  OAuth flow "just to test".
- Acceptance proof: after a dry run, assert the REAL output/log file was NOT created while the DRY
  log WAS. That is what demonstrates nothing real fired.

## Workflow

### Step 0 — Recover state before touching code
1. `session_search(query="<app name>")` to recover the previous session's intent and where it left off.
2. Read the README first, then list the real files (skip `.venv/`): READMEs carry the run command,
   file layout, and a feature list that doubles as the acceptance criteria for "continue the app".
3. Locate the app folder before assuming it is gone; a `session_search` hit plus a file listing is
   faster and more reliable than replaying the transcript.

### Step 1 — Syntax-check before editing
`python -c "import ast; ast.parse(open('app.py').read())"` (or `python -m py_compile app.py`) so a
crash-truncated file is caught before your edits mask it.

### Step 2 — Start the server, then prove it is up
- Start with the terminal tool's own backgrounding: `terminal(background=True, command="cd <dir> &&
  source .venv/bin/activate && python app.py")`. Do NOT use `&`/`nohup`/`setsid` wrappers — the tool
  rejects shell-level backgrounding outright. If the project ships a `run.sh`, launch with it
  (`terminal(background=True, command="cd <dir> && ./run.sh")`) — it activates the venv for you.
- Readiness probe: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:<port>/`. A `000`
  immediately after launch usually means the request raced the bind, not that the server is dead —
  re-check in a SEPARATE call (and read the server log you redirected to) before concluding anything.
- Never interpret app behaviour until readiness is confirmed; a dead server looks identical to a
  broken app from the client side.

### Step 3 — Exercise every route with curl and report status + bytes
- `curl -s -o /tmp/out.html -w "HTTP %{http_code}, %{size_download} bytes\n" <url>` for each GET,
  then each write route (add / save / delete / import / send).
- **Session-gated responses are invisible to a plain curl.** Flask `flash()` writes to the session
  cookie, so without a cookie jar the followed redirect shows NO message and you wrongly conclude the
  handler is silent. Always use `curl -c $J -b $J -L ...` with a cookie jar when asserting a flash
  message or any session-dependent state, and grep the rendered text for the expected string.
- Assert on rendered text or the data file's new contents, not on the HTTP code alone.

### Step 4 — Test destructive routes without corrupting user data
`cp <datafile> /tmp/<datafile>.backup` first, mutate through the route, assert the file changed,
then restore and re-assert the original. Leave the user's data file exactly as you found it.

For an app with real credentials or an irreversible action, go further: copy the whole project
(app + `templates/` + data files) to `/tmp/<app>-test/` and run the server THERE. Never point a test
run at the real project dir or real credentials. Afterwards delete the test dir and confirm the real
dir still has no real output/token files — that is the proof it was untouched.

### Step 5 — Prove validation runs BEFORE the external/credential step
When a route validates input and then calls an external service (OAuth, API, SMTP), feed it invalid
input and confirm it rejects BEFORE touching the credential. That lets you test the whole path with
no real login. Order the code accordingly — validate the rows, THEN build the service — so validation
is reachable without credentials.

### Step 6 — Unit-test pure logic with a fake service
Parsers, pipelines, and label ops are cheaper to prove directly than over HTTP. Monkeypatch the
service factory (`app.gmail_read_service = lambda: FakeSvc()`) with a fake whose `execute()` returns
a fixture and records calls; assert on the parsed output and on the recorded call kwargs.
- Put the test file INSIDE the project dir and run it from there. A test living in `/tmp` that does
  `import app` resolves to some OTHER `app` module and dies with `module 'app' has no attribute ...`;
  the test file's own directory is what lands on `sys.path` first.

### Step 7 — Shut down cleanly
Read the server PID from `pgrep -af <pattern>` and kill that PID. **Never `pkill -f <pattern>` when the
pattern appears in the command you are running** — it matches the invoking shell's own command line, so
the kill lands on your own session (SIGTERM/SIGKILL) and the command you meant to run never completes.

### Step 8 — Prove the app runs for someone who is not you

"Can other people use it?" is answered by cloning into an empty directory and running it as a new
user, never from memory. A repo that runs on the dev machine is not a shareable repo.

```bash
git clone <url> /tmp/uji_pakai && cd /tmp/uji_pakai
./run.sh 8899        # must come up with no pre-made venv and no local config
```

The three failures this catches, in order of how often they bite:

1. **No dependency manifest.** With nothing declaring the imports, the failure surfaces as a raw
   framework traceback. Ship `requirements.txt`, and have `run.sh` check the imports up front and
   print the venv + pip commands instead of dying halfway. Put the check where the user will see it:
   `if ! "$PY" - <<'CEK' ... import fastapi, uvicorn, yaml ... CEK; then <instructions>; exit 1; fi`.
2. **Hardcoded dev-machine paths.** Absolute venv paths in `run.sh`, `tests/*.sh`, and Python helpers
   resolve only on the author's box. Resolve the interpreter in this order: `$PY`, then `.venv`/`venv`
   inside the project, then `python3`. Grep the whole tree for the author's home directory before
   claiming portability.
3. **README commands that only exist locally.** Absolute repo paths and a personal interpreter path
   are meaningless elsewhere; use relative commands. Keep a short "what you need first" section:
   runtime + packages, any external gateway the app cannot ship, at least one worker/provider binary,
   and where the credential goes.

Also confirm the app starts in a DEGRADED state when an optional dependency is absent, with a warning
rather than a crash, and state plainly which parts then cannot work.

### Step 9 — Never leave test servers or the user's own servers behind
A throwaway instance on a second port is easy to forget. After the portability run, kill ONLY the test
PIDs (match the port in `/proc/*/cmdline`, never a bare pattern) and then re-probe the user's real
port to confirm it is still up. Report both facts.

## Rule 1 — Per-machine state is not per-project state

When the app writes configuration into the user's HOME (CLI config files, a `~/.<app>/` directory, a
model cache under `runtime/`), a second install on the same machine inherits the first one's plugins,
skills, and model list. That is a real limitation of the design, and it is the difference between
"works on the author's machine" and "installs cleanly anywhere".
- Check for it by listing what the app writes outside its own directory, then asking what a second
  install would see.
- Say it plainly in the report rather than implying the repo is self-contained, and name the fix
  (move that state under the project directory). Do not quietly leave the impression that a clone is
  all a new user needs.
- When a shared module reads machine-scoped files, an install on a fresh machine will show the
  AUTHOR's plugins and skills, which reads as a bug to the new user. Surface it before they hit it.

## Design convention: single-source-of-truth file ↔ web UI auto-sync
When the app's list/config lives in a file (CSV/JSON) and the UI edits it, "bikin auto sinkron X ke
web UI" means: read the file on every GET, write it back on every mutation, and have the action
buttons use the on-disk file directly (no re-upload step). Render the file's current text into the
edit textarea so a manual edit round-trips. This removes the "upload the CSV again for every send"
friction the user is complaining about.

### Making the sync actually look synced (and not clobber edits)
- **Set no-cache headers on every dynamic HTML response.** The server reads the file fresh on each
  GET, but a browser (especially mobile) serves its cached copy, so the user sees the OLD list and
  reports "tidak sinkron". Add an `@app.after_request` that sets `Cache-Control: no-store,
  must-revalidate` (+ `Pragma: no-cache`, `Expires: 0`) for `text/html`, and give the page an
  explicit reload link.
- **Resolve the data filename case-insensitively.** Android/Windows file managers save `Daftar.csv`
  or `DAFTAR.CSV`; a hard-coded `daftar.csv` path then reads nothing and the page looks empty. Match
  the directory entry case-folded and read/write through the resolved path.
- **Guard the web editor against clobbering an external edit.** Put the file's mtime in a hidden
  field when rendering the edit form; on save, refuse ("reload first") if the file's mtime changed
  since the page loaded. Without this a stale browser tab silently overwrites edits made on the phone.
- **Surface an unreadable file instead of swallowing it.** If the data file has content but cannot be
  parsed, render a visible warning banner, not an empty list — silence is what makes the user believe
  the sync is broken.

## Design convention: background scheduler without a dependency
For "jadwal kirim" (scheduled runs), a daemon thread polling a JSON jobs file every few seconds is
enough — no APScheduler. Job lifecycle: `pending` -> `running` -> `done`/`failed`, plus `cancelled`.
Record `created`/`started`/`finished` and a result string per job. State the limit plainly: the
scheduler only runs while the app process is alive; for reliability point at tmux or cron.

## Design convention: turn a plain Flask UI into a design system
When the user asks to upgrade a bare template ("design frontend dari yang polos jadi design web ui"),
keep the stack (no framework migration) and extract a reusable system instead of restyling inline:
- One stylesheet at `static/style.css` holding CSS custom properties (tokens) for colour, radius,
  shadow, fonts, easing; templates link it via `url_for('static', filename='style.css')`. Move all
  styling out of the templates — no inline `style=` soup.
- One accent colour; an off-white/tinted background (never pure `#000`/`#fff`); tinted shadows; a
  varied radius scale; a subtle grain/gradient so surfaces are not flat.
- A real font pairing with system fallbacks (e.g. Outfit + JetBrains Mono for figures), loaded from
  Google Fonts; monospace + `font-variant-numeric: tabular-nums` for numbers.
- Replace emoji "headings" with a single SVG icon sprite (`templates/_icons.html` with `<symbol
  id=...>`, used via `<svg class="ic"><use href="#i-x"/></svg>`) — one consistent stroke weight.
- Add the states AI omits: hover/active/focus-visible, empty states, inline notices, a skip-link,
  `@media` reflow, and `min-height: 100dvh` (not `100vh`).
- **Prove it renders without breaking functionality.** Load the page in `browser_exec`, read computed
  styles (`getComputedStyle`) for font/accent/radius, then grep the rendered HTML for every `action=`
  and `name=` to confirm no form lost its route or field.

### Responsive pass ("bikin kompatibel di setiap device, mobile sampai desktop")
- **Confirm the viewport actually changed before trusting a size sweep.** `Emulation.setDeviceMetricsOverride`
  does resize the page in some setups and not others, and a sweep built on an unverified assumption
  reports false "ok" for every size. After each override, assert `window.innerWidth` equals the width
  you asked for; if it does not, fall back to measuring in an **iframe at an explicit width**, ONE
  width at a time (loading 20+ iframes at once gives contention and bogus half-loaded readings): set
  `f.style.width='<w>px'`, poll until `contentDocument.readyState==='complete' &&
  contentWindow.innerWidth` is within ~2px of `<w>`, THEN read `documentElement.scrollWidth`.
  Overflow = `scrollWidth > innerWidth + 1` in either mode.
- **Clear the override when the sweep ends** (`Emulation.clearDeviceMetricsOverride`). A leftover
  mobile override silently corrupts every later measurement in the session, including contrast
  audits and element-size checks.
- **The usual root cause of mobile overflow is `min-width: auto` on a grid/flex child**, not a stray
  wide element: a `.section` inside `display: grid` refuses to shrink below the min-content width of
  the table inside it, so the whole document is pinned at ~700px on a 360px phone. Fix with
  `.stack > * { min-width: 0 }` (and `min-width: 0` on the section itself) so the `.table-wrap`
  scrolls instead of the page. The same rule bites on a flex child holding `white-space: nowrap`
  text: `flex: 1` plus `overflow: hidden` still refuses to shrink without `min-width: 0`, and a
  heading alone can pin the document to its own width. Verify by asserting
  `scrollWidth <= innerWidth + 1` at 320/360/390/768/1920.
- **Bisect a blowout by hiding one ancestor at a time and re-reading `scrollWidth`.** Walk down from
  `body`, hide a child, read `documentElement.scrollWidth`, restore it, and descend into whichever
  child made the width collapse. This finds the culprit in a handful of reads; guessing from a list
  of wide elements does not.
- **A breakpoint where three columns no longer fit should drop the third into the existing drawer,
  not squeeze it.** When the middle column falls below roughly 500px the side panel wraps its labels
  one word per line and reads as broken. Hide the panel at that width and re-show the drawer's own
  toggle button there (a `display: none` rule scoped to the narrow range), instead of raising the
  three-column breakpoint and leaving the panel unreachable.
- **Give tables their own scroll, not the document:** `overflow-x: auto` + `-webkit-overflow-scrolling:
  touch` + a CSS-only edge shadow (two `local` + two `scroll` background gradients on the wrapper) as
  the "swipe me" hint, and `overflow-wrap: anywhere` on `.email`/`.mono` so long tokens stop setting
  the table's minimum width.
- **Touch sizing must key off `@media (hover: none)`, not width** — a landscape phone is >640px wide
  yet still has no hover, so a width-only breakpoint leaves 29px tap targets. Verify by emulating the
  media feature: `cdp('Emulation.setEmulatedMedia', features=[{'name':'hover','value':'none'},{
  'name':'pointer','value':'coarse'}])`, then assert every `.btn` height ≥ ~38px; clear with
  `features=[]`.
Depth (token starter + verification probe): `references/frontend-design-system.md`.

## Design convention: matching a named product's look ("bikin semirip mungkin dengan <app>")

When the brief is "make it look like X", the deliverable is X's layout, colour, type, and behaviour
in THIS app, under THIS app's name. Extract the design language from evidence, never from memory.

- **Read the values out of an artefact you actually have.** A design-system repo (`design-systems/<name>/`
  with `DESIGN.md` + `tokens.css` + a `source/evidence.md`) is the good case: copy the rules, and note
  in your own evidence file which values are theirs and which you derived. A CLI binary can hold its
  theme table as plain strings — `data.find(b'rgb(208,180,255)')` anchors it, then print the
  surrounding few kB. State plainly which values you could NOT extract, instead of implying the sweep
  covered everything.
- **Vendor a custom type family's substitute, do not hotlink.** The real faces are licensed and not
  shippable; pick an open substitute per role (serif display / UI sans / mono), fetch the woff2 files
  once into `static/fonts/` with the OFL licences beside them, and serve a local `fonts.css`. A
  `@font-face` sheet requested from the desktop UA returns the woff2 URLs directly. This also keeps
  the look identical without internet.
- **A single accent colour needs up to THREE tokens, because one value cannot pass contrast in both
  themes.** A fill used as a button background, the same hue used as text on the page background, and
  the hue used as a mark or ring have different neighbours: pick the fill so light-on-accent passes
  (>=4.5:1), pick a darker accent for accent-as-text on a light background, and keep the bright
  original for marks. Record each value with the ratio it was chosen for.
- **Recompute every state colour against BOTH themes** rather than reusing the palette's own numbers;
  a grey that passes on the page background can fail on a tinted selected row.
- **Drop the mark when the borrowed app's logo is a brand asset.** Match layout, colour, type, and
  behaviour; draw the app's OWN monogram instead of importing a competitor's glyph, wordmark, or name
  into the UI. Say this out loud when reporting, so "100% mirip" is understood as "same design
  language, own identity".

### Drawing and checking an in-app mark
- Draw it as inline SVG using `currentColor`, so one definition follows the theme instead of needing a
  second asset per theme; a standalone favicon file cannot inherit, so it carries the literal value.
- Geometric construction, not a font glyph or a library icon: stroked paths, butt caps, miter joins,
  explicit coordinates, no enclosing circle.
- **The DOM proves it rendered, not that it looks right.** Check `path` count and computed `color`
  for wiring, then take the element's own bounding box, raise `deviceScaleFactor` to 3, screenshot,
  and ask about that crop only. A loose crop comes back reporting the mark missing or misnaming its
  style. This is what catches letter-spacing defects the DOM check passes: two letters whose feet
  nearly touch at the baseline.
- **When the user supplies their own logo, use it — do not draw a stand-in.** A hand-drawn SVG or
  glyph is a placeholder they will ask you to replace, and it wastes a round trip. A supplied raster
  needs its background separated and its colour moved onto the palette; do that numerically and
  verify from the alpha channel, not from a screenshot (a viewer renders transparency as black).
  Recipe: `references/asset-prep.md`.
- Keep the mark's contrast at >=3:1 against each theme's background (it is a non-text graphic, so the
  text thresholds do not apply) and record both measured ratios.
Depth (token starter + verification probe): `references/frontend-design-system.md`.

## Design convention: one OAuth scope/token per capability
Give send and read their own token files and scopes so each capability is consented and can fail
independently. This keeps the primary path (send) working before the secondary one (read) is granted.

### Consenting a SECOND capability fails with `Scope has changed`
When you request a second scope set (e.g. read after send) with `include_granted_scopes="true"`,
Google returns the UNION of previously-granted scopes (send+read), and oauthlib raises
`Warning: Scope has changed from "read..." to "read...+send"`, which aborts `fetch_token` so the
second token is never written. The first token still works, so it looks like a UI glitch, not an
OAuth bug. Fix both layers:
- Pass `include_granted_scopes="false"` in `flow.authorization_url(...)` so Google stops merging.
- `os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")` at import so a wider-than-requested
grant is accepted instead of fatal.
Reproduce without a live login: `parse_token_response(json.dumps({..., "scope": requested + " extra"}),
scope=requested)` from `oauthlib.oauth2.rfc6749.parameters` — it raises the scope-changed Warning
without the env var and returns a token with it.

### Do the OAuth consent through the WEB, never via a browser auto-launch
`InstalledAppFlow.run_local_server(open_browser=True)` calls `webbrowser.get(...).open(...)`, which on
Termux/proot raises `could not locate runnable browser` BEFORE it ever prints the consent URL — so the
user can never complete consent and every send fails. Never rely on the library opening a browser.
Instead make the app its own OAuth client:
- A `GET /oauth/<kind>` route builds the flow with an explicit `redirect_uri`
  (`http://127.0.0.1:<port>/oauth/callback`, overridable via env) and returns
  `redirect(flow.authorization_url(...)[0])` — the user's CURRENT browser is sent to Google.
- A `GET /oauth/callback` route reads `state`/`code`, pops the stashed flow, calls `fetch_token(code=...)`,
  writes the token file, and redirects home with a flash.
- Stash flows in an in-memory `{state: (flow, token_path)}` map; a restart just means re-consent.
- Show per-capability consent status + a Connect button in the UI, and have the guarded route
  (e.g. `/send`) redirect to `/oauth/<kind>` when consent is missing rather than raising.
- Desktop-app OAuth clients allow the loopback `127.0.0.1` redirect without pre-registering the port;
  only if `redirect_uri_mismatch` appears does the URI need adding in Google Cloud Console.
Prove it with the test client: `GET /oauth/<kind>` returns 302 whose `Location` starts with
`https://accounts.google.com`, and a fake flow whose `fetch_token`/`credentials.to_json` are stubbed
drives the callback to write a token file.

## Design convention: portable run.sh + graceful import guard
Ship a `run.sh` (chmod +x) as the documented way to launch, so the user never hits
`ModuleNotFoundError: No module named 'flask'` by running `python app.py` with system Python (deps
live only in `.venv`).
- Shebang `#!/usr/bin/env bash` — a shebang copied from Termux
  (`/data/data/com.termux/files/usr/bin/bash`) breaks on Ubuntu (permission denied / not found).
- Script: create `.venv` if missing, install `requirements.txt` if deps are absent, then
  `exec .venv/bin/python app.py`.
- In `app.py`, wrap the third-party imports in `try/except ModuleNotFoundError` and print the
  "run ./run.sh" instructions, then `raise SystemExit(1)` — a wrong-python run gets guidance, never a
  raw traceback.
- `chmod +x` is lost when the folder is copied; tell the user to re-run `chmod +x run.sh` once.
- Prove the auto-setup branch without a real install: drop a stub `python3` earlier on `PATH` that
  just echoes its args, run `run.sh`, and confirm it calls `python3 -m venv .venv`.

## Publishing to GitHub without leaking secrets ("push github, jangan munculin secret")
This app class always holds real secrets (OAuth `credentials.json` with the client secret, `token*.json`
with access/refresh tokens) and personal data (recipient emails, sent logs, uploaded CVs). A push
publishes whatever is not ignored, so treat secret hygiene as part of the task, not an afterthought.
Full command set + pattern list: `references/publish-secret-hygiene.md`.

1. **Auth + identity from `gh`, never invent it.** `gh auth status`; then
   `gh api user -q .login` and set `git config user.email "<login>@users.noreply.github.com"` — a
   noreply identity keeps the real address out of the public commit metadata.
2. **Enumerate the secrets BEFORE staging.** List the project dir and identify by kind: OAuth client
   secret file, token files, any `.csv`/`.json` holding real recipients/logs/tracking, `uploads/`,
   `.venv/`, `__pycache__/`. Do not rely on the README's file list alone.
3. **Write `.gitignore` first, covering secrets AND real data**, then `git add -A`. Ignoring only the
   credential files is not enough: a `daftar.csv`/`sent_log.csv` of real companies/emails is a privacy
   leak too. Ship `.example` stand-ins (a placeholder `credentials.json.example`, a `daftar.example.csv`)
   so the format is documented without any real value, and a `uploads/.gitkeep` to keep the dir.
4. **Verify the STAGED set, not the working tree.** `git diff --cached --name-only` and grep it for
   the forbidden names; assert zero matches before committing. `git status` lies about intent — the
   staged list is what will actually ship.
5. **Scan the staged CONTENT for secret shapes**, not just filenames: `git diff --cached` grepped for
   `GOCSPX`, `ya29.`, `1//0g`, `refresh_token"?\s*[:=]`, `client_secret"?\s*[:=]`, `gho_`/`ghp_`,
   `AIza`, `-----BEGIN`, and the OAuth client-id numeric prefix. Also list distinct real email
   addresses and confirm they are only documentation placeholders (`hrd@abc.com`), never the user's.
   Expect the `.example` file's `GANTI-...` placeholder to match `client_secret` — that is fine; a
   match on a real-looking value is not.
6. **Check repo visibility and say it out loud.** `gh repo view <owner>/<name> --json name,visibility`.
   `gh repo create` defaults to PRIVATE, but if the repo already exists and is PUBLIC, pushing
   publishes it — surface that to the user and offer `gh repo edit <repo> --visibility private
   --accept-visibility-change-consequences` rather than letting them assume it is private.
7. **Verify from the GitHub side after pushing, not from local git.** Re-fetch the remote tree
   (`gh api repos/<owner>/<repo>/git/trees/main?recursive=1 -q '.tree[].path'`) and assert no secret
   path is present, then run `gh api "search/code?q=repo:<owner>/<repo>+<secret-value>"` for each real
   secret value and assert `total_count == 0`. Local `.gitignore` only proves intent; the remote read
   proves the result.
8. **A secret that ever hit a remote is compromised even after deletion** — the value lives in history
   and in caches. If any real secret is found pushed, stop and tell the user to ROTATE it (regenerate
   the OAuth client secret / revoke the token), not just delete the file. Prefer never pushing.

## Pitfalls

- **Mobile overflow is usually `min-width: auto`, and an unverified viewport override hides it.** A
  grid/flex child won't shrink below its content, so one wide table or one nowrap heading pins the
  whole page at ~700px on a phone. Assert `window.innerWidth` after each override before trusting a
  sweep, clear the override at the end, and measure in fixed-width iframes when the override does not
  take.
- **A CSS class-name collision can silently break every button, and the contrast audit is what catches
  it.** A text helper (`.kecil`, 13px muted grey) also matched the modifier on a button
  (`class="tombol kecil"`), so every small button rendered grey text on the accent fill at ~1.35:1
  while the DOM looked perfect. Keep text helpers and component modifiers in separate namespaces
  (`.teks-kecil` vs `.tombol.kecil`), and run the composited-background contrast audit over the
  rendered page after any stylesheet change: it is the only check that sees this class of defect.
- **The same collision shape recurs with block-level names.** A log-row text class `.pesan` collided
  with the chat message block `.pesan`, so hundreds of log rows counted as chat messages and the
  empty state was pinned off screen. Before adding a short generic class name, grep the stylesheet
  for it and scope it (`#panel .pesan-log`), or rename it.
- **A flash/session message needs `-c/-b`.** See Step 3 — the single most common false negative in
  this class. Plain curl + `-L` shows a blank page and you report "no feedback".
- **`000` right after launch is a race, not death.** Re-probe in a separate call before restarting.
- **Template variable used but never passed.** A Jinja placeholder (e.g. `{{ rows_text }}`) that the
  view does not supply renders empty without error; after adding a field to a template, re-GET the
  page and confirm the value is actually present in the HTML.
- **"Already pushed?" is answered with evidence, never from memory.** Compare `git rev-parse HEAD`
  against `git ls-remote origin -h refs/heads/<branch>`, then confirm from the HOST itself
  (`/repos/<owner>/<repo>/commits?per_page=3` and `/contents/<dir>`), including the byte sizes of the
  files just added. A clean tree plus a matching hash is the claim; the host listing is the proof the
  right bytes landed. If the local repo has been re-cloned or moved, the hash comparison alone is not
  enough.
- **Do not claim a send/OAuth path was verified when it was not.** If the real end-to-end needs a
  login you did not perform, say so plainly and report exactly what you did exercise (validation,
  UI, file sync) versus what remains untested.
- **Compare case-insensitively on BOTH sides.** Normalizing one side of a comparison (lowercasing a
  parsed sender) but not the other (a stored list with mixed case) silently turns a real match into a
  miss — the feature looks broken while reporting success. Normalize both sides.
- **Kill by PID, not by pattern** — see Step 7.
- **`Address already in use` = a stale server from an earlier test.** A prior backgrounded run that
  was never reaped still holds the port, so the new launch exits while `curl` still answers (from the
  OLD process) and you misread a dead new server as healthy. `pgrep -af app.py`, kill the stale PID,
  confirm the port is free (`curl` returns `000`) BEFORE relaunching.
- **`csv.DictReader` puts overflow columns in a `None` key as a LIST.** A row with more delimiters
  than the header (e.g. a trailing `;` on each line) yields `row[None] = [...]`, and
  `(v or "").strip()` then raises `AttributeError: 'list' object has no attribute 'strip'` — one bad
  row 500s the whole import. Skip `k is None` and coerce list values before stripping.
- **`Scope has changed` when consenting a second capability.** `include_granted_scopes="true"`
  merges already-granted scopes into the token response and oauthlib treats the wider grant as fatal,
  so the second token never saves while the first keeps working (looks like a UI bug). Set
  `include_granted_scopes="false"` and `OAUTHLIB_RELAX_TOKEN_SCOPE=1`.
- **`could not locate runnable browser` is an OAuth consent-path bug, not a missing browser.** Any
  google-auth `run_local_server(open_browser=True)` / `webbrowser.open` call on Termux/proot throws
  this before showing the consent URL, so consent is impossible and the guarded action always fails.
  Replace it with the app's own redirect + `/oauth/callback` routes (see the web-based OAuth
  convention). Do not tell the user to install or configure a browser.
- **Do not hard-code the CSV delimiter or encoding.** Files arrive from Excel/phones with `;`, tab,
  or `|`, and as Latin-1/Windows-1252. Sniff the delimiter from the header line, try UTF-8 then fall
  back to latin-1, and strip a BOM/CRLF. Recipe: `references/csv-ingestion-robustness.md`.
- **A missing-data-file bug is invisible on the server but obvious to the user.** When the user says
  "<file> I edited doesn't sync / upload doesn't work", reproduce BOTH the read path (GET renders the
  file's rows?) and the write path (upload/add/save changes the file?) before theorising — then fix
  the parser/format, not the feature.
- **"Upload ga bisa / file gabisa diakses" on a phone is usually the file picker, not the app.**
  Prove the server route works first: `curl -s -F 'csv_file=@/tmp/x.csv' http://127.0.0.1:<port>/<route>`
  — if the data file changes, the fault is client-side. On Termux+proot the browser picker cannot see
  files inside the proot filesystem, and `accept=".csv"` hides files whose MIME Android can't map.
  Two fixes: drop/loosen the `accept` attribute, and add a path-import route that reads a file
  directly from shared storage (`/sdcard`, `/storage/emulated/0`, `/storage/self/primary`) which proot
  CAN see — bypassing the picker entirely. Allowlist those roots + the project dir; reject
  non-absolute and out-of-allowlist paths. Recipe: `references/csv-ingestion-robustness.md`.
- **Reading the inbox message-by-message is slow (N+1 round-trips).** `list()` then a `get()` per
  message means one HTTPS request per message (30 messages ≈ 30 sequential round-trips, seconds of
  lag on mobile) while file-backed pages answer instantly — the user reports "Cek balasan lemot".
  Fetch metadata in ONE `service.new_batch_http_request()`, and set `request_id=<message id>` on each
  `batch.add(...)` so responses map back (without it the callback cannot be matched). Cache the result
  for a short TTL (e.g. 60s) and offer a `?refresh=1` link to force a live pull. Recipe:
  `references/gmail-api-notes.md`.
- **"Email dibaca apa tidak" has no API answer — only a tracking pixel, and it is unreliable.** Say
  so before building. Embed a 1x1 image in the HTML part pointing at the app's `/track/<id>.png`;
  log each hit. Label it "kemungkinan dibuka" (likely opened), never "read": corporate clients block
  images (miss), Gmail proxies the fetch via `GoogleImageProxy`, Apple Mail auto-loads (false
  positives). Needs a PUBLIC url (see `references/public-tunnel.md`) and only works for mail sent
  AFTER the pixel was added.
- **Don't chain decision prompts while the user is still deliberating.** This class involves many
  forks (which feature, which port, whether to tunnel). Ask ONE question at a time, and when the user
  says they are still reading/deciding ("sebentar", "aku baca dulu"), stop asking, hold all state, and
  wait — do not re-prompt, do not start the work, do not send anything.
- **When the user reports a failure, reproduce it before explaining.** "status gagal", "masih error",
  "lemot" are symptoms; read the app's own log/data file (`sent_log.csv`, `tracks.json`, the server
  log) FIRST — the cause is often in the recorded error (a malformed recipient, a stale server, an
  N+1 fetch), not in the code you were about to rewrite.

- **A launcher must clear stale own processes narrowly and fall back to a free port.**
  `Address already in use` from a never-reaped prior run leaves `curl` answering from the OLD process.
  Probe the port with a real connect (`/dev/tcp/127.0.0.1/<port>` or a Python socket) — `ss`'s silence
  is NOT proof the port is free. Kill only own processes (`pkill -f "python app.py"`, never a pattern
  that matches the invoking shell), then fall back to 5001/5002/... honoring a `PECUT_PORT` override
  and print the chosen port. Ship a `stop.sh` that stops app + tunnel.
- **Recipient validation must be strict enough to catch typos BEFORE the provider call, and provider
  errors must be translated.** A loose `^[^@\s]+@[^@\s]+\.[^@\s]+$` accepts `user@gmail.co.` (a
  trailing dot) and the provider then rejects the send with a raw `HttpError 400 "Invalid To header"`
  that the user reads as "the app is broken". Require a label-structured domain and a ≥2-letter TLD,
  validate ALL rows up front (report every bad row and send none), and map known provider errors to
  plain language ("Alamat email tujuan tidak valid ..."). Verify the regex against the user's real
  address list BEFORE tightening so valid addresses are not rejected.
