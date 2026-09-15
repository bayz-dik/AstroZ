---
name: pecut-lamaran-gmail
description: Use when working on pecut-lamaran-gmail Flask app.
---

# Pecut Lamaran Gmail

Flask app at `/root/pecut-lamaran-gmail/`: sends the same email body to many company addresses from one Gmail account. `daftar.csv` (columns `email,subject,cv`) is the single source of truth for recipients; `uploads/` holds CVs; `sent_log.csv` (real) and `sent_log_dry.csv` (simulation) hold results; `schedule.json` holds scheduled sends.

## Hard rules
- NEVER send real email while testing. Run with `PECUT_DRY_RUN=1 ./run.sh` — sends are simulated, no Gmail/OAuth touched, results go to `sent_log_dry.csv`. If `sent_log.csv` or `token.json` appears during your testing, something is wrong.
- The user does real sending themselves. Test in a copy (e.g. `/tmp/...`) or with dry-run; restore `daftar.csv` after any test that mutates it.

## Running
- Always via `./run.sh` (it creates `.venv` + installs deps if missing, then runs `.venv/bin/python app.py`). Running `python app.py` with system Python gives `No module named 'flask'` — app.py prints a friendly hint instead of a traceback.
- If `./run.sh: Permission denied`, `chmod +x run.sh` (shebang is `/usr/bin/env bash` so it works in Termux and Ubuntu).
- Port 5000 (override with `PECUT_PORT`). A stale `app.py` process keeps the port and serves OLD code — `pkill -f "python app.py"` before restarting, and verify new routes respond. `./jalan-tunnel.sh` already clears stale own processes and falls back to 5001/5002/... if 5000 is taken by another program; `./stop.sh` stops app + tunnel.
- `./run.sh` = app only (no tracking); `./jalan-tunnel.sh` = app + public tunnel (tracking on); `./stop.sh` = stop both.

## OAuth (do NOT use run_local_server)
`flow.run_local_server(open_browser=True)` fails on Termux/proot with `could not locate runnable browser`, before the auth URL is shown. Use the in-app web flow instead:
- `/oauth/<kind>` (kind = `send` or `read`) builds the auth URL and 302-redirects the user's own browser to Google.
- Google returns to `/oauth/callback` (default `http://127.0.0.1:5000/oauth/callback`, override via `PECUT_REDIRECT_URI`).
- Separate tokens: `token.json` (scope gmail.send), `token_read.json` (gmail.readonly + gmail.modify). `_build_service` never opens a browser; missing scope raises a message pointing to the Izin Google card.
- Connecting the SECOND capability fails with `Scope has changed` unless `include_granted_scopes="false"` is passed in `authorization_url(...)` AND `os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")` is set at import — Google otherwise merges the already-granted send scope into the read response and oauthlib rejects the wider grant. Send keeps working, which makes it look like a UI bug.

### Google "Akses diblokir ... belum menyelesaikan verifikasi"
Not a code bug — OAuth client is `installed` type, app still in Testing, and the signed-in account is not a Test user. Fix in Google Cloud Console → APIs & Services → OAuth consent screen → **Test users** → add the exact Gmail account → Save, then retry. Expect the "Google hasn't verified this app" screen → Advanced → Go to (unsafe).

## CSV tolerance
Parser detects delimiter (`, ; tab |`), ignores case in header names, strips BOM/CRLF, decodes UTF-8 then Latin-1. Filename matching for `daftar.csv` is case-insensitive (`Daftar.csv` works). A row with more delimiters than the header yields a list value under key `None` — skip it, do not crash. If `daftar.csv` has content but is unparseable, `read_daftar()` returns `[]` and `daftar_problem()` surfaces a warning banner (HTTP 200, never 500).

## Browser/picker pitfalls on Android
- HTML pages set `Cache-Control: no-store` so the phone doesn't serve stale views.
- `accept=".csv"` on the file input can hide files from the Android picker — keep it unfiltered.
- Picker often can't reach the project dir inside proot. Prefer the in-page **Impor langsung dari folder HP** box (`/daftar/import-path`) reading `/sdcard/...` directly (allowed roots: `/sdcard`, `/storage/emulated/0`, `/storage/self/primary`, project dir).
- The textarea editor posts a hidden `daftar_sig` (mtime); save is rejected if the file changed since page load, so external edits aren't silently overwritten.

## Tracking "dibaca" (pixel) + public tunnel
There is no email read-receipt (unlike WhatsApp). The only real mechanism is a tracking pixel, and it is a SIGNAL, not proof:
- On send, each message gets `<img src="{PECUT_PUBLIC_URL}/track/<tid>.png">` (HTML alternative + plaintext fallback). `GET /track/<tid>.png` returns a 1x1 PNG and records `{at, ua}` under that id in `tracks.json`. Unknown ids still return the PNG (200) but record nothing.
- Without `PECUT_PUBLIC_URL` set, no pixel is embedded and the **Baca** column stays empty — the page shows a banner saying tracking is off. That is not an error.
- Run `./jalan-tunnel.sh` (NOT `./run.sh`) to enable it: starts `~/bin/cloudflared tunnel --protocol http2 --url http://127.0.0.1:5000`, scrapes the `*.trycloudflare.com` URL, exports `PECUT_PUBLIC_URL`, then launches the app.
- cloudflared quick tunnel: if it never logs `Registered tunnel connection` and the URL returns HTTP 530, QUIC is blocked on this network — force `--protocol http2`. Binary is the linux-arm64 release downloaded to `~/bin/cloudflared` (the script re-downloads it if missing).
- Be upfront with the user about limits (they explicitly want "nyata", not hype): image-blocking clients (Outlook) miss opens; Gmail/Apple auto-load can false-positive. Label it "kemungkinan dibuka", never "pasti dibaca". A pixel only works for mail sent AFTER the feature exists — earlier sends can never be tracked — and free trycloudflare URLs change on restart, killing pixels in old mail.

## Recipient validation + friendly errors
- `EMAIL_RE` rejects malformed addresses (trailing dot `gmail.co.`, TLD < 2 chars, `..`, spaces) so a typo is caught BEFORE sending; `validate_rows` reports every bad row at once and sends none.
- `friendly_error()` maps Gmail errors to plain language ("Invalid To header" -> "Alamat email tujuan tidak valid ..."), so `sent_log.csv` GAGAL lines are readable.

## Frontend (design system)
The UI was upgraded from bare templates to a token-driven system: `static/style.css` (CSS custom properties: warm-paper bg, single teal accent `--accent`, varied radius, tinted shadows, Outfit + JetBrains Mono with system fallbacks), an SVG icon sprite in `templates/_icons.html` used as `<svg class="ic"><use href="#i-..."/></svg>`, and `templates/index.html` + `templates/replies.html` as the two pages. Preserve this style on future edits — do not reintroduce emoji headings, inline styles, or a second accent colour. Class-level convention + verification probe: the `local-server-webapp-qa` skill.

## Prosa README (gaya bahasa)
README berbahasa Indonesia santai ("kamu", "kalau"), tanpa em dash. Em dash (U+2014) adalah pelanggaran Hard Gate di aturan antislop (R-02) dan sudah dibersihkan sekali dari README ini; jangan menuliskannya lagi. Pakai koma, titik, titik dua, atau kurung sesuai fungsi aslinya. Dilarang juga: buzzword (seamless, revolutionary, cutting-edge), signposting ("let's dive in"), dan chatbot closer ("semoga membantu").

Caps boleh dipakai hanya untuk label UI/kode nyata (`KIRIM SEKARANG`, `BELUM DIBACA`, `UNREAD`, `MODE SIMULASI`), bukan untuk memberi penekanan di tengah kalimat. Emoji di README adalah nama tombol asli dari aplikasi, bukan hiasan judul.

Audit prosa: cari `—`, `–`, `\s--\s`, dan buzzword dengan regex; verifikasi hasil edit TIDAK mengubah fakta teknis dengan membandingkan himpunan angka (`re.findall(r"\d+", ...)`) dan blok kode (```` ``` ````...```` ``` ````) antara `git show HEAD~1:README.md` dan file baru. Blok kode harus identik; hitungan angka harus sama.

## Banner README (assets/banner.svg)
Banner pixel-art di header README, digenerate oleh `assets/_gen_banner.py` (font pixel 5x7 = sumber kebenaran; ubah teks/ukuran di variabel, jangan edit SVG tangan). README memakai URL `raw.githubusercontent.com`, bukan path relatif — renderer markdown (mis. Telegram) tidak memuat gambar relatif dari repo.

Dua jebakan yang sudah memakan korban:
- **Animasi CSS di dalam `<style>` SVG harus dipasang ke elemen yang memegang `fill`, bukan ke grup induk.** `.l rect { fill: INK }` mengalahkan `fill` warisan dari `<g class="l1">`, jadi `animation` di grup tidak pernah terlihat (grup jadi teal, rect tetap tinta). Pakai `.l1 rect { animation: ... }`, dan override `prefers-reduced-motion` juga ke `.lN rect`.
- **Komentar CSS tidak boleh memuat `<` atau `&` mentah** di dalam `<style>` — itu XML, satu `<rect>` di komentar membuat seluruh dokumen gagal di-parse (`mismatched tag`). Tulis "elemen rect", bukan `<rect>`.

Verifikasi: `python3 -c "import xml.dom.minidom as m; m.parse('assets/banner.svg')"` untuk validitas XML, lalu di browser baca `el.getAnimations()[0]` — set `currentTime` ke pecahan durasi dan baca `getComputedStyle(el).fill` untuk membuktikan keyframes benar-benar berjalan. **Jangan mengandalkan sampling waktu dinding di sesi browser headless**: tab yang `document.hidden` membekukan timeline di 0 dan warnanya terlihat konstan padahal animasinya sehat. Cek `getAnimations()[0].playState` + `currentTime` sebelum menyimpulkan animasi mati.

## Verify changes
Flask test client for logic/renders; then a live `./run.sh` + curl pass (multipart for uploads). For UI changes, also load in `browser_exec` and check computed styles + no mobile overflow. Kill the test server and free port 5000 when done. Confirm `daftar.csv` still holds the user's real data.
