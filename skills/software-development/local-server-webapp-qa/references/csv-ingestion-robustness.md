# Robust CSV ingestion for user-supplied files

When a local web app ingests a CSV the user produces (Excel export, phone editor, hand-typed),
the file's shape is unknown. Assume `,`-only + UTF-8 and one bad file looks like a broken feature.

## The parser (one function, reused by every read path)
```python
import csv, io

def _read_csv_rows(raw):
    raw = (raw or "").lstrip("\ufeff")          # strip BOM
    if not raw.strip():
        return []
    first = raw.splitlines()[0] if raw.splitlines() else ""
    delim = ","
    for cand in [",", ";", "\t", "|"]:        # sniff delimiter from the header line
        if cand in first:
            delim = cand
            break
    reader = csv.DictReader(io.StringIO(raw), delimiter=delim)
    fields = [(x or "").strip().lower() for x in (reader.fieldnames or [])]
    if "email" not in fields or "subject" not in fields:   # required columns
        raise ValueError(f"CSV wajib punya kolom 'email' dan 'subject'. "
                         f"Kolom terbaca: {reader.fieldnames} (delimiter '{delim}')")
    rows = []
    for row in reader:
        norm = {}
        for k, v in row.items():
            if k is None:            # overflow columns land in None as a list -> skip
                continue
            if isinstance(v, list):
                v = " ".join(str(x) for x in v if x)
            norm[str(k).strip().lower()] = (v or "").strip()
        if not any(norm.get(c) for c in ("email", "subject", "cv")):
            continue
        rows.append({"email": norm.get("email", ""),
                     "subject": norm.get("subject", ""),
                     "cv": norm.get("cv", "")})
    return rows
```

## Decoding uploads
```python
try:
    raw = f.read().decode("utf-8-sig")
except UnicodeDecodeError:
    f.seek(0)
    raw = f.read().decode("latin-1", errors="replace")
```

## Why each guard exists
- **Delimiter sniff** — Excel in many locales exports `;`; phone apps may emit tab. A `,`-only parser
  reports "missing columns" on a perfectly good file.
- **`k is None` / list coercion** — a row with MORE delimiters than the header (e.g. a trailing `;`
  on every line) makes `DictReader` collect the extra fields into `row[None]` as a list, so
  `(v or "").strip()` raises `AttributeError: 'list' object has no attribute 'strip'` and the import
  500s on the whole file. This is the exact bug that reads to the user as "upload doesn't work".
- **BOM / CRLF / latin-1** — BOM prepends to the first header cell; Windows/Android write CRLF;
  some exports are Windows-1252.
- **Case-insensitive header** — `Email,Subject,Cv` is valid input.

## Failure must be visible, never silent
- `read_*()` (the GET path) must catch parse errors and return `[]` so the page still renders — but
  pair it with a `*_problem()` helper that re-parses and returns the error string, rendered as a
  warning banner. An empty list with no explanation is what the user reports as "not syncing".
- The upload route should distinguish: no file chosen / file parsed but zero data rows / parse error
  — three different messages.

## Case-insensitive filename resolution
```python
def resolve_daftar():
    target = "daftar.csv"
    for p in BASE.iterdir():
        if p.is_file() and p.name.lower() == target:
            return p
    return BASE / target
```
Read and write through the resolved path everywhere; a hard-coded name misses `Daftar.csv`.

## Getting the file to the server: browser picker vs proot path
On Termux+proot (Android) the browser's file picker frequently cannot see files inside the proot
filesystem (the project dir), and `<input type="file" accept=".csv">` hides files whose MIME type
Android fails to map. The user then reports "file gabisa diakses / upload ga bisa" even though the
route is fine.
- **Diagnose first:** `curl -s -F 'csv_file=@/tmp/x.csv' http://127.0.0.1:<port>/<upload-route>`.
  If the data file changes, the server side works and the fault is the client's file access.
- **Fix 1 — drop/loosen the `accept` attribute** so any file is selectable.
- **Fix 2 — add a path-import route:** the user pastes an absolute path and the server reads it
directly. proot CAN read shared storage at `/sdcard`, `/storage/emulated/0`, `/storage/self/primary`.
Allowlist those roots plus the project dir; reject non-absolute and out-of-allowlist paths, and
report "file not found" with the resolved path.
```python
IMPORT_ROOTS = ["/sdcard", "/storage/emulated/0", "/storage/self/primary"]
real = Path(user_path).expanduser().resolve()
allowed = any(str(real).startswith(r) for r in IMPORT_ROOTS) or real.parent == BASE
```

## Self-check before reporting done
1. Parse a string with a trailing delimiter (`...;Lamaran;`) — must not raise.
2. Upload a `;`-delimited file over HTTP multipart — assert the flash reports N rows.
3. Put a `;`/tab file on disk, GET the page — assert its rows render.
4. Point the app at a header-less file — assert a warning banner, HTTP 200 (not 500).
5. Rename the file to `Daftar.csv` — assert it is still found.
6. Import by absolute path from `/sdcard/...` — assert it works; assert an out-of-allowlist path
   (`/etc/passwd`) and a relative path are rejected with a clear message.
