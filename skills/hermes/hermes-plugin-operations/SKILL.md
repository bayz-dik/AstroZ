---
name: hermes-plugin-operations
description: Use when running or explaining an installed Hermes plugin.
---

# Operating an installed Hermes plugin

For when a plugin is already installed and the user asks how to *run* it, *use*
it, or *see* what it does. This is the operations side; building/debugging a
plugin's hooks and manifest is a different job (see the authoring skill).

## A plugin is not "run" — say so before anything else

A plugin is **not launched**. Once its key is in `plugins.enabled` its hooks and
commands load with every session; there is nothing for the user to start. The
only thing the user *starts* is a **consumer** of the plugin's output — a viewer,
a TUI, a dashboard. Draw the three-part model explicitly:

- **plugin = engine** — enable once (`hermes plugins enable <key>`), then it is
  always on. Never tell the user to "run the plugin".
- **viewer = screen** — the process the user opens to *see* it.
- **feed = wire** — the artifact between them (e.g. a JSONL file the hooks
  append to); any tool (`jq`, `tail`, a custom dashboard) can consume it.

When the user says "I'm confused how to run it", they have almost certainly
conflated the engine with the screen. Name the distinction in the first line.

## A slash command is usually a SNAPSHOT, not a live view

Before promising a realtime panel from a plugin's slash command, read the
handler. A `ctx.register_command(name, fn)` callback returns a **string once** —
it renders in-chat and ends. If `fn` just returns `snapshot_text(limit=N)` there
is no refresh loop, and it will never be realtime, by design.

So when a plugin offers both:

- in-chat slash command → one-shot snapshot ("a photo");
- separate viewer process / tmux pane → the live, self-refreshing view ("a
  video").

State which surface is which. If the user expects live updates and reaches for
the slash command, tell them the live view is the other one.

## The agent's shell has no TTY — it cannot attach a TUI for the user

Interactive TUI programs (tmux, htop, an editor, a full-screen viewer) fail from
a tool-call shell because stdin is not a TTY: `exec tmux attach` errors out.

- Create/launch **detached** (`--detach`, or `new-session -d`) and verify with
  `list-panes` / `capture-pane`.
- Then hand the user the **literal command** to run in their own terminal
  (`tmux attach -t <sess>`, or the in-chat snapshot command).
- Never present the agent's detached run as "it's live for you now" — it is
  running, but the user is not seeing it until they attach.

## Asymmetric splits are intentional — name the knob, don't "fix" them

Sidebar/task-pane layouts default to ~30–33% of the screen (opencode ratio), not
50/50. If the user reads ~68/32 as a bug, explain it is deliberate and give the
exact override rather than silently changing it:

```bash
<launcher> --kill                          # tear down
HERMES_PANEL_PCT=50 <launcher>             # percentage
HERMES_PANEL_COLS=40 <launcher>            # fixed columns
```

Layout also flips automatically: side-by-side when the terminal is wide enough
(~≥64 cols), stacked below that (a horizontal split starves the main pane on a
narrow screen). Mention `--layout h|v` when the user wants to force one.

## Verify before you claim it works

Prove the plugin is live rather than asserting it:

```bash
hermes plugins list                 # Status column: enabled / not enabled
hermes plugins doctor <dir> --ci    # "registrations: N tool(s), M hook(s)"
<viewer> --once                     # one snapshot, proves the feed is flowing
wc -l $HERMES_HOME/runtime/*.jsonl  # feed growing = events arriving
```

Run the viewer yourself only for `--once` verification; a persistent viewer must
be started by the user in their own terminal (see the TTY rule above).
