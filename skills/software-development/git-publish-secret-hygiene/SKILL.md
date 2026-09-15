---
name: git-publish-secret-hygiene
description: "Push a project to GitHub/GitLab without leaking secrets."
version: 1.0.0
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [git, github, secrets, security, publish, gitignore]
    category: software-development
    related_skills: [github, local-server-webapp-qa]
---

# Publishing a project without leaking secrets or personal data

Class of task: the user says "push ke GitHub, jangan sampai secret / data pribadi bocor".
The deliverable is a remote repo whose tracked files AND FULL HISTORY contain no
credentials and no personal data — proven by reading the REMOTE, never assumed from a
clean local `git status`.

## Procedure

### 1. Inventory the secrets BEFORE the first `git add`
List the project and classify every file. Typical offenders:
- OAuth/API credentials: `credentials.json`, `client_secret*.json`, `*.pem`, `service-account*.json`.
- Tokens: `token.json`, `token_read.json`, `*.token` — anything holding `refresh_token`/`access_token`.
- Personal data: recipient lists (`daftar.csv`), send/inbox logs (`sent_log.csv`), tracking files, uploaded documents (`uploads/*.pdf`).
- Env & local state: `.env`, `*.local`, `schedule.json`, `.venv/`, `__pycache__/`.
Confirm what a credential file holds by reading its KEYS, not its values:
`python3 -c "import json;print(list(json.load(open('credentials.json'))['installed']))"`.

### 2. Write `.gitignore` FIRST, plus `.example` stubs
Ignore every offender from step 1. For a directory that must exist, use `uploads/*` + `!uploads/.gitkeep`.
Ship redacted `credentials.json.example` / `daftar.example.csv` so the repo stays usable without
real values — placeholders like `GANTI-DENGAN-CLIENT-SECRET`.

### 3. Stage, then audit the staged SET
```
git init -q -b main && git add -A
git diff --cached --name-only | grep -E "credentials\.json$|token(_read)?\.json$|daftar\.csv$|sent_log|\.env$|\.pdf$|\.venv" \
  && echo "LEAK" || echo "clean"
```
`grep` exits 0 on a match, so the `&&` branch is the leak. Fix `.gitignore` and re-add until clean.

### 4. Scan staged CONTENT, not just filenames
Filenames miss secrets embedded in code, templates, or READMEs. Grep the diff for real values:
- Credential prefixes: `GOCSPX`, `ya29.`, `1//0g`, `gho_`, `ghp_`, `sk-`, `AIza`, `-----BEGIN`,
  inline `refresh_token`/`client_secret`, GCP project numbers.
- Personal data: the author's real name, real `@gmail.com` addresses, phone numbers.
Full pattern catalog + commands: `references/secret-scan-patterns.md`.
Expect hits on your own `.example` placeholders — distinguish placeholder from real value; only a
real value is a leak.

### 5. Set a non-identifying committer identity
A real email in `git config user.email` is itself a leak. Use the GitHub noreply form:
```
LOGIN=$(gh api user -q .login)
git config user.name  "$(gh api user -q '.name // .login')"
git config user.email "$LOGIN@users.noreply.github.com"
```

### 6. Push, then verify from the REMOTE
Local cleanliness is not proof; the remote is. After `git push`:
```
R=<owner>/<repo>
gh api repos/$R/git/trees/main?recursive=1 -q '.tree[].path' | grep -E '<offenders>' && echo LEAK || echo clean
```
Strongest check: clone to `/tmp` and grep every revision — `git grep -nE '<patterns>' $(git rev-list --all)` —
then delete the clone. Use `gh api "search/code?q=repo:$R+<value>"` as corroboration only.

### 7. Removing a value from a LATER commit does NOT remove it from history
A string deleted in commit N still lives in commit N-1; a direct link to the old SHA
(`github.com/<owner>/<repo>/commit/<sha>`) still renders it. `.gitignore` stops FUTURE commits only.
Prove the residue first with `git grep -n '<value>' <old_sha> -- <path>`. To truly purge, pick one:
- **Rewrite history** (same repo): `git checkout --orphan fresh && git add -A && git commit -m "..."`,
  then `git branch -D main && git branch -m main && git push -f origin main`.
- **Delete + recreate** (strongest): needs the `delete_repo` token scope —
  `gh auth refresh -h github.com -s delete_repo` (device flow: show the one-time code, the user enters
  it at `github.com/login/device`, wait for "Authentication complete"), then
  `gh repo delete <owner>/<repo> --yes` and `gh repo create <owner>/<repo> --public --description "..."`, then push.
Verify: `gh api repos/$R/commits/<old_sha>` must return `422 No commit found`.

### 8. Confirm the user's data still exists locally
A purge touches only the remote. Re-list the real credential/data files on disk and re-probe the
running app, so the user knows nothing local was lost.

## Pitfalls
- **A placeholder can carry a real person's name.** The author's name inside a template's example text
  (e.g. an email-body placeholder) is personal data and gets committed — grep for it in step 4 and
  replace with a generic label like "Nama Kamu".
- **`gh api repos/.../contents` returning `404 This repository is empty`** means the repo exists but has
  no commits. Check with `gh repo view` before `gh repo create` — creating an existing repo fails.
- **`gh api search/code` lags right after a push** (indexing). Treat the tree listing + a fresh clone's
  `git grep` as authoritative; the search API as corroboration.
- **An unset `git config user.email` blocks the commit**, and a real one leaks identity — set the
  noreply form in step 5.
- **Never force-push over a collaborator's work.** A history purge is safe here only because it is the
  user's own solo repo — confirm that before `-f`.
- **The remote being public is a separate decision from secrecy.** With secrets properly gitignored,
  public is fine; do not conflate "don't leak secrets" with "make it private" — ask which the user wants.
