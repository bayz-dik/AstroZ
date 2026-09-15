---
name: static-webapp-qa
description: "Audit/fix local static web apps with browser_exec."
version: 1.0.0
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [qa, browser, web, vanilla-js, verification, localhost]
    related_skills: []
---

# Static Web App QA & Iteration

Class of task: the user says "lanjutin / continue / fix / test <web app>" for an app that is
plain HTML + CSS + JS with no build step, served from a folder over a local HTTP server
(e.g. `/root/psikotes`, `python3 -m http.server 8100`). The deliverable is a working app plus a
report of what was actually exercised — not a description of what should work.

If the app instead runs as a server process with server-side state (Flask/WSGI, routes, files or
sessions), use `local-server-webapp-qa` — verify those over HTTP with curl, not through the browser.

## Workflow

### Step 0 — Read state before touching code
1. `search_files(target=files, pattern=*<app>*)` to locate the folder, then read its README first.
   These READMEs carry the run command, file layout, and a feature bullet list that doubles as
   the acceptance criteria for "continue the app".
2. `session_search(query=...)` to recover the previous session's intent. If the app was built in an
   earlier session, the README + file list is faster than replaying the transcript.
   Scrolling inside the *current* session lineage is rejected (`anchor lives in the current session
   lineage`) — don't spend a call on it.
3. Syntax-check every script before editing, so a crash-truncated file is caught first:
   `for f in js/*.js js/data/*.js; do node --check $f; done` (and `node --check` on the main bundle).

When locating user-provided web assets on Android-backed environments, check `/storage/emulated/0/Download` and `/data/data/com.termux/files/home/storage/downloads` in addition to `/root/Downloads` and `/root/downloads`; Android shared storage may be mounted outside the agent home, so a home-only search can falsely report a missing file. Use an exact-name search first, for example `find /storage/emulated/0/Download /data/data/com.termux/files/home/storage/downloads -maxdepth 2 -type f \( -iname 'web1.zip' -o -iname 'web1.jpg' \) -print`.
When the report is only "mau jalanin, gabisa" / "it won't run", establish whether anything serves
the port BEFORE reading a line of app code — a missing server is the top cause and the app is
usually fine. One call gets the evidence: port probe + `curl -s -o /dev/null -w "%{http_code}"`
against `/` and every asset (all should be 200) + one deliberate 404.
- `curl` `000` means dead. Restart with
  `terminal(background=True, command="cd <dir> && python3 -m http.server <port> --bind 127.0.0.1")`,
  then re-check in a separate call.
- Port probe: trust `curl` first. Inside a proot/Termux container a listening-port listing can come
  back completely empty, so never conclude "the port is free" from that — confirm with a socket probe:
  `(exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && echo UP || echo DOWN`. Any launcher's
  port-in-use guard must use this probe, not the listing, or the guard silently never fires.
- Do not use `nohup`/`setsid`/`&` wrappers: the terminal tool rejects shell-level backgrounding and
  the command is refused outright. Use the tool's own `background=True`.
- A dead server makes the browser sit on `about:blank` with `window.<NS>` undefined — that looks like
  an app failure but is a readiness failure. Check readiness before interpreting anything.
- **Ship a launcher as part of the fix** so the user can restart it themselves; a one-command script
  kills this whole class of "can't run it" reports. Copy `templates/jalankan-webapp.sh`, adjust the
  app name/port, `chmod +x`, and prove both paths (busy port refuses with a suggested alternative,
  free port serves 200). Tell the user the two failure signatures are different: server down =
  the page cannot open at all; app broken = the page opens but is blank/throwing.

### Step 2 — Drive the app through the browser harness
Paste-ready driver: `templates/browser-exec-driver.py`. Non-negotiable pieces of it:
1. **Disable cache and cache-bust the URL** before testing after an edit:
   `cdp('Network.setCacheDisabled', cacheDisabled=True)` then `goto_url(url + '?v=N')`. Without this
   you re-test the old bundle and conclude the fix didn't work.
2. **Install an error trap and neutralise dialogs on every page load:**
   `window.__errs=[]; window.onerror=(m,s,l)=>{window.__errs.push(m+' @'+l)};` and
   `window.confirm=()=>true; window.alert=()=>{};`. A `confirm()` that survives a reload blocks the
   whole `Runtime.evaluate` and surfaces as a 5s timeout, not as a dialog error.
   If one slips through anyway, every later evaluate times out too (even `Page.enable`) — recover with
   `cdp('Page.handleJavaScriptDialog', accept=True)`. The pending click has usually already applied,
   so re-read the rendered state instead of clicking again, or you double-submit.
3. **Reset state between scenarios**: `localStorage.clear()` + a second load, then assert again. A
   leftover resume/banner from the previous scenario makes the next assertion meaningless.
4. **Drive via the app's exposed namespace** (`window.NS.foo()`) for speed, but keep at least one real
   DOM path (click / `KeyboardEvent`) per feature so you are not testing only the API surface.
5. **Assert rendered text, not return values**: `document.querySelector('.verdict').innerText`.
   A scoring function returning fine while the render throws is the most common failure mode here.
6. **Fast-forward time by mutating state** (`s.startedAt -= 30*60*1000`) instead of sleeping.
7. **End every scenario with `print("errs:", window.__errs)`.** Clean console + rendered text is the
   evidence; "it should work" is not.
8. **Identify the screen from rendered text, not the URL.** This app class has no routing
   (`location.hash` stays empty, the URL never changes). Regex the container instead —
   `document.getElementById('app').innerText.match(/SOAL (\d+) DARI (\d+) · TERJAWAB (\d+)/)` — and use
   the same capture to drive the loop and as the assertion. Build bulk loops to read the counter each
   iteration and stop on the last item, so a re-render that swallows a click cannot spin forever.
9. **Clear the state your own run created before handing over** (`Object.keys(localStorage).filter(k =>
   k.startsWith('<appprefix>_'))`), reload, and assert the clean home screen — a leftover resume
   snapshot makes the app look like it kept or lost the user's session. Say plainly whether the
   harness browser shares the user's profile: if it is a separate automation profile, their data was
   never touched, so state that instead of claiming you cleaned it.

### Step 3 — Hunt the edge cases, then fix
Use `references/edge-case-matrix.md` — it lists the probes that reliably find real bugs in this app
class (empty collection, unlimited-mode clamping, cross-feature state destruction, hard-coded labels,
optional API with no args, `NaN`/`undefined` in generated reports, responsive, print CSS).
Reproduce → fix → re-run the same probe → re-run the full happy path (all features) to prove no
regression. Report the observed values, not the intent.

### Step 4 — Finish the feature, not just the code
A new feature is not done until it is in all three places:
- the code path, exercised end-to-end in the browser;
- the in-app guide/help panel (the modal the "Panduan"/"About" button opens);
- the README feature bullet list.
Also keep the new feature out of the user's saved statistics if it is a practice/drill mode
(do not write it to history) — mixing practice runs into recorded scores is a silent correctness bug.

## Pitfalls

- **Generated JS literals must be lowercase.** When building a JS expression from Python, `True`,
  `False`, `None` are a JS `ReferenceError`/syntax problem that mimics an app crash. Emit `true`,
  `false`, `null` (or `json.dumps` the value). A whole test batch "failing" is usually this, not the app.
- **Never let an assertion decide by raising.** Wrap every `js()` call in a helper that catches and
  returns `"ERR: ..."`, and return an explicit `"MISSING"` when the result is `None`. A `null` from a
  broken render and a `null` from a wrong selector look identical when an exception is the only signal.
- **Filtered-then-indexed arrays must be guarded.** Any render path that does `items.filter(...)[0].prop`
  or `done.length ? best.prop : '—'` crashes on the first property access when the filter yields `[]`.
  Test every summary/report screen with a dataset where the filter legitimately yields nothing.
- **"Unlimited" modes must not clamp to the nominal duration.** `Math.min(limit, elapsed)` on a
  no-time-limit session silently reports the cap as the elapsed time (a 30-minute run shown as 20:00).
  Branch on the mode flag, don't reuse the limited path.
- **Preview screens must not destroy other sessions' persisted state.** A brief/instruction screen
  that clears the resume snapshot makes the "Lanjutkan" card disappear for an unrelated in-progress
  session. Clear state only on explicit start/discard, not on render of a preview.
- **Hard-coded counts and option ranges are a bug class.** "30 soal · 4 pilihan" while some items have
  5 options. Derive the label from the data (`Math.min/Math.max` over option counts).
- **Optional API entry points need a no-op guard.** `drillWrong()` called on a non-drillable result must
  silently do nothing, not throw; test it on every incompatible result type.
- **Assert on the mode too.** When a screen can be rendered in two modes, check the label text you
  expect for each (`· tidak dihitung` vs a percentile number) — a stale verdict from the other mode is
  easy to miss.
- **`window.print()` and downloads can't be asserted visually.** Verify what you can observe:
  the `@media print` rule exists (walk `document.styleSheets` → `cssRules` → `r.type===4`), and build
  the report string in-page to grep it for `NaN`/`undefined` before trusting the download.
- **Mobile check**: `cdp('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=2, mobile=True)`
  then assert `document.documentElement.scrollWidth <= window.innerWidth + 2`; clear with
  `Emulation.clearDeviceMetricsOverride` before the next desktop assertion.
- **Never `pkill -f <pattern>` when the pattern appears in the command you are running.** The pattern
  matches the invoking shell's own command line, so the kill lands on your own session (SIGTERM, exit
  -15) and the command you meant to run never completes. Read the PID from the process listing and
  kill that PID.
- **A no-build app with relative script tags usually also runs from `file://`** — verify it and mention
  it: a zero-setup fallback is worth a lot to a user who cannot keep a server process alive. Skip the
  claim if the app uses `fetch` or ES modules, which `file://` blocks.
