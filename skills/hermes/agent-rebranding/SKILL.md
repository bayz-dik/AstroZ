---
name: agent-rebranding
description: Use when rebranding an installed agent app into a persona.
---

# Rebranding an installed agent app into a custom persona

Class: persona-ize an installed agent CLI+TUI in place (rename banners, brand strings, colors, skin — e.g. a stock install becomes a named persona) without forking the repo.

## Standing rules

- Map the real layout with read-only commands before touching anything; never patch paths remembered from a previous session. A patch aimed at a nonexistent path reports success and silently changes nothing — the only symptom is "nothing changed on screen".
- Classify every brand-string occurrence before editing: user-facing text (labels, help text, messages, titles) gets new copy; internal identifiers (env var names, type names, protocol keys, imports, npm package deps) stay untouched — renaming internals breaks the app while the user sees no change.
- Verify in three layers before reporting done: (1) grep audit — zero old brand left in user-facing strings; (2) the app's own typecheck/build gate; (3) an actual render or launch of the surface. A completion claim without rendered output is not completion.

## Procedure

1. Find the surfaces: `which <persona-bin>` (a wrapper may `exec` the real binary with a profile flag), the install root, the TUI project dir, and the per-persona profile dir under the app home.
2. CLI side: grep the old brand across the install root (skip node_modules/tests); patch the banner/version/help modules.
3. TUI side: read the TUI `package.json` scripts FIRST to learn the run model — `tsx src/...` in `start` means it runs from source and patches appear on next launch with no build; only assume a build step if the scripts demand one. Then patch, in order: the banner module (logo/hero art arrays + their gradient arrays), the theme module (BRAND block + dark/light seed palettes), every user-facing occurrence, and the package name.
4. Skin: create `skins/<persona>.yaml` inside the profile dir (copy the bundled skin template from the install's skills tree; its `branding` block carries agent_name/prompt_symbol/goodbye/help_header) and activate with `display.skin: <persona>` in the profile's config.yaml. Load-test it directly through the skin engine (see references file) before claiming it works.
5. Hand the user `<persona> --tui` as the final judge — terminal rendering and taste are theirs to approve.

## Pitfalls

- Replacing the built-in TUI with a custom client: hook `HERMES_TUI_BIN` in `hermes_cli/main_tui_launch.py` `_launch_tui` (external binary replaces the Node TUI; `HERMES_TUI_ARGS` shlex-split appended; exit-42 update relaunch skipped for external). The launcher already assembles the full env contract (HERMES_HOME, HERMES_TUI_* pass-throughs) before the hook, so the custom client inherits profile + provider creds. Dashboard web chat calls `_make_tui_argv` directly and is unaffected. Export the hook in the persona wrapper only when the TUI may launch (`--tui` or default interface tui) and skip it for `--dev` (keeps the built-in Ink dev flow) — never for `--cli`.
- E2E-testing a TUI in tmux: use a dedicated socket (`tmux -L <name>`) — the default socket can be wedged by a prior server and returns "access not allowed". Always `pkill -9 -x <tui-bin>` (NOT `-f`: `-f` matches the test script's own command line and SIGKILLs the harness) + `pkill -9 -f tui_gateway.entry` before a run: a killed tmux server leaves the gateway sidecar orphaned, and two gateways on one profile make prompts hang in "thinking…" forever. Provider latency varies wildly (6s vs 110s for the same prompt) — give reply windows ≥4 min before concluding a bug. If the provider's `/v1/chat/completions` hangs while its root URL answers 200 instantly, check the profile's `logs/errors.log` for `APIConnectionError` before touching the client.
- Bubble Tea bar layout: `lipgloss.Width` counts ANSI escapes on styled strings — compute spacer widths from PLAIN text, and never combine `Padding(0,2)` with `.Width(w)` (the bar becomes w+4 and the right label wraps).
- Reuse the persona's existing banner art in the TUI: generate a Go file from the same generator (`art.go` with raw-string consts + fade ramp) instead of hand-copying braille; render with a per-row fade and center with plain-text width math. Boot screen (hero + wordmark) and empty-chat welcome screen (hero + wordmark + tagline) both show the identity — the boot screen alone is visible for only a few seconds.
- A profile wrapper (`<persona>` -> `hermes -p <profile>`) must also pin `HERMES_HOME=<root>/profiles/<profile>`: Hermes' earliest TUI decision (`_wants_tui_early`) runs BEFORE `-p` is applied and reads `$HERMES_HOME/config.yaml` — without the pin it reads the DEFAULT config, misses `display.interface: tui`, and boots the plain REPL even though `--tui` worked. Pre-setting HERMES_HOME to a `profiles/` child is honoured by `_apply_profile_override`, and `-p` still follows.
- Pull the exact on-disk text (`sed -n`) for large block constants like ASCII-art arrays before constructing an edit — a block rebuilt from memory or from a transcript mismatches and burns a patch cycle.
- Generate ASCII art programmatically (glyph tables composed by code) and validate column alignment/symmetry in the generator before pasting; hand-typed box-drawing art drifts off-grid and the drift is invisible in a code diff.
- Keep gradient arrays in sync with art row counts — the colorizer indexes per row and falls back to muted for out-of-range indexes, so a stale longer/shorter gradient silently recolors rows instead of erroring.
- `background`/`bg` seeds are consumed by derivation, not echoed back — do not "verify" a palette by reading the seed value out of a rendered theme object.

Depth for the Hermes-family install this was exercised on (file map, skin engine mechanics, ASCII art recipe): see `references/hermes-tui-branding.md`.
