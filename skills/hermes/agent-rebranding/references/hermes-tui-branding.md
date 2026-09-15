# Hermes-family install: branding file map and mechanics

Concrete anchors for rebranding a Hermes Agent install into a persona (paths assume the standard install root `/usr/local/lib/hermes-agent`).

## Persona entry point

- Persona bin is a wrapper: `exec <real-bin> -p <profile> "$@"`. Profile lives at `~/.hermes/profiles/<name>/` with its own config.yaml, skills/, skins/, sessions/.
- CLI-side branding lives in the Python install: grep the brand string under the root (`grep -rn 'OldBrand' --include='*.py' .`), patch banner/version/help modules there.

## TUI (`ui-tui/`)

- Run model: `"start": "tsx src/entry.tsx"` — executes TypeScript from source, so every patch is visible on next launch; no build. `build:ink` only rebuilds the `packages/hermes-ink` library (not branding).
- `src/banner.ts`: `LOGO_ART` (6-row block-letter logo), `CADUCEUS_ART` (hero art — repurpose for the persona glyph), `LOGO_GRADIENT`/`CADUC_GRADIENT` (per-row color indexes into `[primary, accent, border, muted]`). `logo()`/`caduceus()` accept custom-markup overrides; `LOGO_WIDTH` is derived, not hardcoded.
- `src/theme.ts`: `BRAND` ThemeBrand block (name, icon, welcome, goodbye, helpHeader) and `DARK_SEEDS`/`LIGHT_SEEDS` palettes. Secondary tones are DERIVED from seeds by a mix ladder (`buildPalette`) — change seeds, and the whole palette follows; never hand-edit derived tones.
- User-facing occurrences to sweep: slash-command help strings, transcript tags, window/tab titles, setup-panel copy, wake-word help, billing/journey/demo texts. Leave functional identifiers: `HERMES_BIN` env, `HermesSkin` type, `@hermes/*` imports, `launchHermesCommand`, gateway protocol names.
- Gate: `npm run typecheck` inside `ui-tui/`.

## Skin system (Python side)

- Engine: `hermes_cli/skin_engine.py`. `load_skin(name)` resolves user skins FIRST at `<profile>/skins/<name>.yaml`, then built-ins, then default. Activation: `display.skin: <name>` in the profile's config.yaml.
- Template with every supported key: `skills/autonomous-ai-agents/hermes-agent/templates/skin.yaml` inside the install. `branding` keys: agent_name, welcome, goodbye, response_label, prompt_symbol, help_header. `banner_logo`/`banner_hero` (rich-markup strings) override the TUI's art at runtime without touching code.
- Direct test without launching the app: `HERMES_HOME=<profile-dir> <venv-python> -c "import sys; sys.path.insert(0,'<install-root>'); from hermes_cli.skin_engine import load_skin; s=load_skin('<name>'); print(s.branding)"`.

## ASCII art generation recipe

No figlet-family package is reliably importable here; compose glyphs directly. Per letter, a 6-row ANSI-Shadow glyph dict; join rows with a one-space intra-word gap and a wider word gap; for custom glyphs (psi, etc.) place strokes by column index with a `row([(col, text), ...])` composer, then assert: max width uniform, shared verticals occupy identical columns across rows, and left/right mirror symmetry for symmetric glyphs. Print and eyeball before writing into source.

## Full palette migration (recolor, not just rebrand)

- Sweep by hex value, not by brand string: grep every old hex across `ui-tui/src` (theme seeds), `hermes_cli/*.py` (banner art markup + `_skin_color(key, fallback)` call sites), and the profile skin YAML. Fallback hexes hide in call sites and only surface when the skin key is absent.
- Migrate DARK_SEEDS and LIGHT_SEEDS as a pair from one palette family (e.g. Rosé Pine main + Dawn), then fix the provenance comments sitting next to them — stale comments contradicting the new palette are user-visible debt.
- Verify with three renders: programmatic (`npx tsx` importing DARK_THEME/LIGHT_THEME + `logo`/`caduceus`), Rich (`build_welcome_banner` with a fake `Console(file=buf, width=140)`, strip ANSI, grep for model-line strings), and a real TUI launch in tmux (`capture-pane -p` for text; `-e` shows ANSI but tmux quantizes truecolor to 256 unless RGB overrides land — quantization is the capture's artifact, not the palette's).
- tmux can be missing in minimal PRoot distros: `apt-get install -y tmux` first; `kill-server` between runs; append `; sleep 600` to the TUI command so the pane survives if the app exits.
- Read `git status`/diffs for STATE, not direction: a rebrand living in the working tree renders stock content as the `-` side. Confirm what is on disk before concluding branding was lost.
- A mid-task user paste can override the palette choice: re-run the same sweep-by-hex procedure against the named family as a DARK/LIGHT pair (Kanagawa wave/lotus was the second pass). Pull hexes from the project's official port files, never from memory.
- Demo/preview recording: `vhs` needs headless Chromium (fails as root / in PRoot even with a no-sandbox wrapper); `agg` needs Rust ≥1.86 (apt ships older). Working path: `asciinema rec` → `.cast` → `npx svg-term-cli --in x.cast --out x.svg` (animated SVG, truecolor preserved). Consume the capture with `sed 's/\x1b\[[0-9;:]*m//g'` to eyeball text.
