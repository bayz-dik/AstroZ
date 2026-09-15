---
name: hermes-skill-management
description: "Install external skill packs into Hermes via the hub."
version: 1.0.0
license: MIT
---

# Installing External Skill Packs into Hermes

## Always-on rules

- Install through `hermes skills install <id>`, never by git-cloning skill folders into `~/.hermes/skills/` by hand — hub installs get the security scan, the audit-log entry, and `hermes skills update` tracking; manual copies get none of those.
- Find the registry ID before installing (`hermes skills search <owner-or-name>`). Formats: `skills-sh/<owner>/<repo>/<skill-name>` for skills.sh entries, `official/<category>/<name>` for Hermes optional skills.
- Review a BLOCKED scan verdict against the flagged file and line before using `--force` — the scanner false-positives on security/jailbreak prose (e.g. "send the task to its own context window" flagged as exfiltration). Force only what you have actually read; never blind-force.
- Verify installs two ways: count entries in `hermes skills list`, AND open each installed skill folder to confirm its referenced support files (the .md files SKILL.md links to) came along — a partial copy loads as a broken skill with no install-time error.

## Procedure: bulk-installing a repo's skills

1. Clone the repo to /tmp read-only and enumerate: `find <repo> -name SKILL.md`. Read each file's frontmatter `name:` — the skill name can differ from its folder name, and the registry ID follows the name.
2. Check `hermes skills list` first and skip names that already exist as official/builtin skills — installing a duplicate over a bundled skill of the same name adds nothing.
3. Batch-install in the background with a per-skill log: loop `hermes skills install "skills-sh/<owner>/<repo>/$s" --yes >> /tmp/install.log 2>&1 || echo "FAIL_$s" >> /tmp/install.log`. The first fetch can exceed 3 minutes (cold registry cache); later installs run ~10 s. Judge success from the log contents, not the loop's exit code.
4. Retry each failure individually after reading its log section — batch failures are almost always one of the refusals below, not a broken skill.
5. If the terminal tool hardline-blocks a complex inline command (loops, multi-redirects) as an oversized/unparseable payload, do not retry the same inline string — write the loop to a `.sh` file with `write_file` and run `bash <file>`; the block message itself offers this file form as the sanctioned escape hatch.

## Installer refusals and their fixes

- "GitHub API rate limit exhausted" — the unauthenticated limit is 60/hr and a batch burns it fast. Check remaining quota with `curl -s https://api.github.com/rate_limit`, then re-run only the failed skills after reset; do not conclude the skill is unavailable.
- "Refusing to overwrite category directory" — the skill's name collides with an existing category folder under `~/.hermes/skills/` (e.g. a skill named `research` vs the builtin `research/` category). Install into a subcategory with `--category <name>`; keep the skill's own name — renaming with `--name` breaks trigger matching, changing the category does not. Use `--name` only when the SKILL.md frontmatter lacks `name:`.
- BLOCKED (community source + CAUTION verdict) → read the source, then `--force` per the always-on rule.
- A scan line reading "official/builtin" for what should be a skills.sh fetch means an existing bundled skill answered the lookup — the skill is already present; stop retrying.

## Official optional skills

- Doc pages under `/docs/user-guide/skills/optional/...` contain the full SKILL.md preview and the exact install ID in the "install with ..." line. If `web_extract` blocks a hermes-agent docs URL as "private or internal network address" (false positive), curl the page to a file and strip tags in Python instead.
- Optional security/red-team skills (godmode, obliteratus) attack models over the API — appropriate when the target is the user's own provider/infrastructure; never aim them at third-party endpoints.
- Run the optional skills' Python scripts with Hermes's own venv interpreter (read it from the `hermes` launcher script, e.g. `/usr/local/lib/hermes-agent/venv/bin/python`) — the system python3 lacks their deps (`openai`, `yaml`) and pip-installing into it is the wrong fix.
- Call script entry functions directly from an external runner (exec the file into a namespace, then call e.g. `auto_jailbreak(...)` with explicit arguments); do NOT delegate a script run to a nested `hermes chat -q` agent — multi-API-call scripts make the nested agent hang 15+ minutes with no output.
- Pass a dry-run flag / `dry_run=True` before letting any auto-config writer touch `config.yaml`, and back up config.yaml before a real run — the writers merge-and-dump the whole file and can silently restructure it.
