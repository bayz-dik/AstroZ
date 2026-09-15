# Secret & personal-data scan patterns

## Credential / token patterns (`grep -nE`)
```
GOCSPX                        # Google OAuth client secret
ya29\.                        # Google access token
1//0g                         # Google refresh token
gho_|ghp_|ghu_                # GitHub tokens
sk-                           # [OI]-style API key
AIza                          # Google API key
xox[baprs]-                   # Slack token
AKIA                          # AWS access key id
-----BEGIN                    # PEM private key
refresh_token"?\s*[:=]\s*"[A-Za-z0-9_/+-]{15}   # inline refresh token
client_secret"?\s*[:=]\s*"[A-Za-z0-9_-]{10}     # inline client secret
```

## Personal-data patterns
```
<author's real name>                              # names hide in template placeholders, READMEs, comments
[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}   # emails — filter out example domains (*.com placeholders)
0[0-9]{8,}                                        # phone numbers (Indonesian format)
```

## Commands
```
# staged content (before commit)
git diff --cached | grep -nE "<patterns>"

# entire history (strongest)
git grep -nE "<patterns>" $(git rev-list --all)

# remote file set
gh api repos/$R/git/trees/main?recursive=1 -q '.tree[].path'

# remote code search (corroboration; may lag behind a push)
gh api "search/code?q=repo:$R+<value>" -q '.total_count'

# does an old commit still hold a value?
git grep -n '<value>' <old_sha> -- <path>
gh api repos/$R/commits/<old_sha>          # 422 = purged
```

## Reading a credential file without exposing it
```
python3 -c "import json;d=json.load(open('credentials.json'));k=list(d.keys())[0];print(list(d[k].keys()))"
```
