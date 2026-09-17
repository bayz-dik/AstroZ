"""Bukti pemisahan hak admin vs pengguna biasa, pada server yang sedang jalan.

Yang diperiksa hanya status HTTP dan nama kunci jawaban; token tidak dicetak.
Sebelum perbaikan, beberapa baris di sini menjawab 200 untuk pengguna biasa:

  POST /api/gateway/model      -> 200, dan benar-benar menulis ulang model
                                  mesin di config.yaml Hermes
  POST /api/gateway/probe      -> 200, memakai kunci API dan kuota pemilik
  GET  /api/jobs               -> 200, antrean pemasangan CLI milik mesin
  POST /api/capability/pratinjau -> 200, menjalankan git dan mengisi disk pemilik
  GET  /api/state              -> jalur konfigurasi CLI ikut terkirim
  GET  /api/workers            -> path + config_path ikut terkirim
  GET  /api/skills             -> path folder tiap paket ikut terkirim

Jalankan: .venv/bin/python dev/uji_batas_peran.py
"""
import json
import pathlib
import re
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8799"


def ambil(jalan, token=None, metode="GET", badan=None):
    data = json.dumps(badan).encode() if badan is not None else None
    req = urllib.request.Request(BASE + jalan, data=data, method=metode)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


adm = re.search(
    r"^Token  : ([A-Za-z0-9_-]{20,})$",
    pathlib.Path("/mnt/sdcard/Download/AstroZ/token_admin_astroz.txt").read_text(),
    re.M,
).group(1)
usr = pathlib.Path("/tmp/tok_tespisah").read_text().strip()

# 1. Endpoint bersama yang harus ditolak untuk pengguna biasa.
print("1. endpoint bersama sebagai pengguna biasa (harus 403)")
for metode, jalan, badan in (
    ("POST", "/api/gateway/model", {"model": "x/y", "apply_workers": False}),
    ("POST", "/api/gateway/probe", {"models": ["kenari-id/deepseek-v4-1-flash"], "limit": 1}),
    ("GET", "/api/jobs", None),
    ("POST", "/api/capability/pratinjau", {"url": "https://github.com/openai/skills"}),
):
    st, d = ambil(jalan, usr, metode, badan)
    tanda = "OK" if st == 403 else "BOCOR"
    print(f"   [{tanda}] {metode:4} {jalan:32} -> HTTP {st} {str(d.get('error') or '')[:52]}")

# 2. Endpoint yang boleh dibaca, tetapi tanpa jalur mesin.
print("\n2. bacaan yang tetap boleh, tanpa jalur mesin")
st, st_state = ambil("/api/state", usr)
w = (st_state.get("workers") or [{}])[0]
print(f"   GET  /api/state              -> HTTP {st}, kunci pekerja: {sorted(w)}")
st, d = ambil("/api/workers", usr)
print(f"   GET  /api/workers            -> HTTP {st}, kunci pekerja: {sorted((d.get('workers') or [{}])[0])}")
st, d = ambil("/api/skills", usr)
p = (d.get("paket") or [{}])[0]
print(f"   GET  /api/skills             -> HTTP {st}, {len(d.get('paket') or [])} paket, kunci paket: {sorted(p)[:6]}")
st, d = ambil("/api/mcp", usr)
print(f"   GET  /api/mcp                -> HTTP {st}, {len(d.get('servers') or [])} plugin, kunci: {sorted((d.get('servers') or [{}])[0])}")
st, d = ambil("/api/capability", usr)
print(f"   GET  /api/capability         -> HTTP {st}, {len(d.get('terpasang') or [])} paket, kunci: {sorted((d.get('terpasang') or [{}])[0])}")
st, d = ambil("/api/tools/status", usr)
print(f"   GET  /api/tools/status       -> HTTP {st}, pekerja={len(d.get('workers') or [])} mcp={len(d.get('mcp') or [])} job={len(d.get('jobs') or [])}")

# 3. Admin tetap menerima semuanya.
print("\n3. admin tetap menerima jalurnya")
st, d = ambil("/api/state", adm)
print(f"   GET  /api/state              -> HTTP {st}, kunci pekerja: {sorted((d.get('workers') or [{}])[0])}")
st, d = ambil("/api/skills", adm)
print(f"   GET  /api/skills             -> HTTP {st}, kunci paket: {sorted((d.get('paket') or [{}])[0])[:6]}")
st, d = ambil("/api/jobs", adm)
print(f"   GET  /api/jobs               -> HTTP {st}, {len(d.get('jobs') or [])} job")

# 4. Gerbang masuk tetap bekerja untuk keduanya (peran terbaca).
for nama, tok in (("admin", adm), ("pengguna", usr)):
    st, d = ambil("/api/saya", tok)
    print(f"\n4. /api/saya sebagai {nama:8} -> HTTP {st}, peran={d.get('pengguna', {}).get('peran')}")
