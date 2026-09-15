# Publishing a credential-bearing app to GitHub safely

Commands for the "push github, jangan munculin secret" task. Adapt the repo path; everything else is
copy-paste. The rule is: never stage blindly, scan the staged set and its CONTENT, then verify from the
GitHub side after the push.

## 1. Auth + noreply identity
```bash
gh auth status
git config user.name "$(gh api user -q '.name // .login')"
git config user.email "$(gh api user -q .login)@users.noreply.github.com"
```

## 2. Enumerate secrets and personal data in the project dir
```bash
ls -la                      # credentials.json, token*.json, daftar.csv, sent_log*.csv, tracks.json, uploads/
```
Kinds to treat as secret/data:
- OAuth client secret file (contains `client_secret`, `GOCSPX-...`)
- token files (contain `token` `ya29...` and `refresh_token` `1//0g...`)
- data files with real recipients / logs / tracking (`*.csv`, `schedule.json`, `tracks.json`)
- `uploads/` (personal documents), `.venv/`, `__pycache__/`, `.env*`

## 3. .gitignore that covers secrets AND data
```gitignore
credentials.json
token.json
token_read.json
.env
.env.*
da *.csv  -> ignore the real data files, keep .example
sent_log.csv
sent_log_dry.csv
schedule.json
tracks.json
uploads/*
!uploads/.gitkeep
.venv/
__pycache__/
*.py[cod]
```
Ship stand-ins: `credentials.json.example` (placeholder `GANTI-DENGAN-CLIENT-SECRET`),
`daftar.example.csv`, `uploads/.gitkeep`.

## 4. Verify the STAGED set (not the working tree)
```bash
git add -A
git diff --cached --name-only
git diff --cached --name-only | grep -E "credentials\.json$|token(_read)?\.json$|daftar\.csv$|sent_log|schedule\.json|tracks\.json|\.pdf$|\.venv|\.env" \
  && echo "LEAK: something slipped in" || echo "clean"
```

## 5. Scan staged CONTENT for secret shapes
```bash
git diff --cached | grep -nE "GOCSPX|ya29\.|1//0g|gho_|ghp_|AIza|-----BEGIN|refresh_token\"?\s*[:=]\s*\"[A-Za-z0-9_/+-]{20}|client_secret\"?\s*[:=]\s*\"[A-Za-z0-9_-]{10}|<oauth-client-id-prefix>"
git diff --cached | grep -oE "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}" | sort -u
```
The second lists every email in the staged content — confirm they are all placeholders
(`hrd@abc.com`), never real recipients. A match on the `.example` placeholder is expected; a match on a
real-looking value is a stop signal.

## 6. Visibility + push
```bash
gh repo view <owner>/<repo> --json name,visibility
# existing public repo -> pushing publishes it; offer to switch:
#   gh repo edit <owner>/<repo> --visibility private --accept-visibility-change-consequences
git remote add origin https://github.com/<owner>/<repo>.git   # or set-url
git push -u origin main
```

## 7. Verify from GitHub after the push (authoritative)
```bash
gh api repos/<owner>/<repo>/git/trees/main?recursive=1 -q '.tree[].path' \
  | grep -E "credentials\.json$|token(_read)?\.json$|daftar\.csv$|sent_log|\.venv|\.env" \
  && echo "LEAK in remote tree" || echo "remote tree clean"

for v in GOCSPX ya29. '1//0g' <oauth-client-id-prefix> refresh_token; do
  n=$(gh api "search/code?q=repo:<owner>/<repo>+$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$v")" -q '.total_count')
  echo "$v -> $n"   # every count must be 0
 done
```
Local `.gitignore` proves intent; the remote tree read and code search prove the result. Never claim
"no secrets pushed" from the local diff alone.

## 8. If a real secret was pushed
Rotate it — regenerate the OAuth client secret and revoke the token — then force-push a cleaned
history. Deleting the file in a later commit does NOT remove it from history or GitHub caches.
