# Edge-case matrix for local static web apps

The probes below are the ones that actually surfaced bugs in a real app (multi-test quiz engine,
localStorage persistence, multi-mode screens). Run each against a FRESH document with a clean
`localStorage`, and assert on rendered text. For each probe: reproduce → fix → re-run the probe →
re-run the full happy path (all features) to prove no regression.

## 1. Empty collection reaching a summary/report screen
Probe: build a dataset where a `filter(...)` legitimately yields `[]` and render the summary screen
(e.g. run only a personality test in a "full simulation" that averages cognitive scores).
Bug shape: `done.length ? best.prop : '—'` guards the wrong thing — the array is non-empty but the
filtered subset is empty, so `filter(...)[0].prop` throws on first property access.
Fix shape: guard the filtered result itself (`strong ? ... : '—'`), and skip the dependent analysis
sentence instead of emitting `undefined`.

## 2. "No time limit" / unlimited mode
Probe: start a session with the limit off, then move `startedAt` back beyond the nominal duration
(`s.startedAt -= 30*60*1000`) and finish. Read the elapsed value in the result.
Bug shape: a single `Math.min(limit, elapsed)` clamps both modes, so a 30-minute practice run is
reported as the 20-minute nominal cap. Count-up mode must branch on the mode flag.

## 3. Cross-feature state destruction
Probe: start feature A (leave it in progress, so its snapshot is persisted) → open the preview/brief
screen of feature B → go home and look for the "resume A" card.
Bug shape: the preview screen calls the same cleanup as "start", wiping the other feature's snapshot.
Fix shape: preview renders are read-only; clear persisted state only on explicit start/discard.
Also assert the snapshot bytes are *identical* before and after the preview.

## 4. Hard-coded labels and counts
Probe: compare every displayed count/range against the data (`questions.length`, option counts).
Bug shape: "40 soal · 4 pilihan" while some items have 5 options.
Fix shape: derive it (`Math.min(...)/Math.max(...)` over `q.o.length`), so it cannot drift.

## 5. Optional API entry point called with no argument
Probe: call the new action (`drillWrong()`) on every result type it is not meant for.
Bug shape: throws on the first property access instead of doing nothing.
Fix shape: early `return` when there is nothing to act on; assert "no throw, no state change".

## 6. Generated report / export strings
Probe: build the report text in-page (`r.pctl != null ? ... : ''`) and search it for `NaN` and
`undefined` before trusting the downloaded file. `window.print()` and blob downloads are not
observable, so this is the only honest check.

## 7. Mode-dependent verdict / label
Probe: render the same screen in both modes and assert the mode-specific label text.
Bug shape: a percentile-based verdict shown for a practice run where no percentile exists.
Fix shape: branch the verdict on the mode, and label the suppressed stat (`· tidak dihitung`)
rather than printing `null`.

## 8. Persistence round-trip
Probe: work partially through a feature, reload the page, resume, and assert the position AND the
answer count AND the regenerated random series (or shuffled order) are unchanged.
Bug shape: regenerating a random series on resume shifts every stored answer by one.

## 9. History hygiene for practice modes
Probe: finish a practice/drill run, then read the history array.
Rule: practice runs must not be written to history and must not advance any multi-step sequence,
otherwise the user's recorded scores are polluted. Assert both the count and the absence of a
mode flag in the stored entries.

## 10. Responsive + print
Probe: `Emulation.setDeviceMetricsOverride(width=390, height=844, mobile=True)` and assert
`document.documentElement.scrollWidth <= window.innerWidth + 2`; separately confirm a `@media print`
block exists by walking `document.styleSheets` → `cssRules` → `r.type===4 && r.conditionText.includes('print')`.
Clear the override before returning to desktop assertions.

## Harness hygiene (these masquerade as app bugs)
- Python `True`/`False`/`None` inside a JS expression string → use `true`/`false`/`null`.
- Assertions that raise on a null result → return a helper-wrapped `"ERR: ..."` / `"MISSING"` instead.
- A surviving native `confirm()` after a reload → override `window.confirm` on every load.
- Cached bundle after an edit → `Network.setCacheDisabled` + `?v=N` cache-buster on every navigation.
- Server not running → `curl` returns `000` and the tab sits on `about:blank`; restart the server
  before interpreting any failure.
