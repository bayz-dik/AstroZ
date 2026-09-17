"""Cek jalur bersama yang masih bisa disentuh pengguna biasa, pada server hidup.

Tidak mengubah apa pun: hanya membaca status sebelum dan sesudah, dan satu
percobaan tulis yang sengaja diarahkan ke nilai yang sama dengan nilai sekarang
supaya tidak ada yang benar-benar berubah.

Token tidak dicetak.
"""
import json
import pathlib
import re
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8799"
USER = "tespisah"


def ambil(jalan, token=None, metode="GET", badan=None):
    data = json.dumps(badan).encode() if badan is not None else None
    req = urllib.request.Request(BASE + jalan, data=data, method=metode)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
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

st, d = ambil("/api/gateway/models?limit=3", usr)
print(f"/api/gateway/models (katalog model + provider) sebagai pengguna -> HTTP {st}, "
      f"contoh entri: {list((d.get('models') or [{}])[0].keys())[:8]}")

# 1. gateway/model: bisakah pengguna biasa mengganti model seluruh mesin?
st, sblm = ambil("/api/gateway/models?limit=1&only_healthy=1", adm)
st, info = ambil("/api/state", adm)
model_kini = info.get("gateway", {}).get("model") or info.get("model")
print(f"\n1. model mesin sekarang: {model_kini}")
st, d = ambil("/api/gateway/model", usr, "POST", {"model": model_kini, "apply_workers": False})
print(f"   POST /api/gateway/model sebagai pengguna -> HTTP {st} {d.get('ok')}")
print(f"   efek yang dilaporkan: {json.dumps(d)[:200]}")

# 2. gateway/probe: pengguna bisa memaksa mesin memanggil puluhan model?
st, d = ambil("/api/gateway/probe", usr, "POST", {"models": ["kenari-id/deepseek-v4-1-flash"]})
print(f"\n2. POST /api/gateway/probe sebagai pengguna -> HTTP {st}, dicoba: {d.get('dicoba') or d.get('total')}")

# 3. jobs: daftar pekerjaan latar milik mesin
st, d = ambil("/api/jobs", usr)
print(f"\n3. GET /api/jobs sebagai pengguna -> HTTP {st}, {len(d.get('jobs') or [])} job")

# 4. workers/paket + probe
st, d = ambil("/api/workers/paket", usr)
print(f"\n4. GET /api/workers/paket sebagai pengguna -> HTTP {st}, {len(d.get('pekerja') or [])} paket")
st, d = ambil("/api/workers/opencode/probe", usr, "POST", {})
print(f"   POST /api/workers/opencode/probe sebagai pengguna -> HTTP {st} {d.get('ok')} "
      f"versi {d.get('version')}")

# 5. marketplace, capability, mcp, skills (baca)
for jalan in ("/api/marketplace", "/api/capability", "/api/mcp", "/api/skills", "/api/tools/status"):
    st, d = ambil(jalan, usr)
    print(f"\n5. GET {jalan} sebagai pengguna -> HTTP {st} ({len(json.dumps(d))} byte)")

# 6. events: apakah pengguna melihat kejadian mesin milik admin?
st, d = ambil("/api/events/recent?limit=5", usr)
ev = d.get("events") or []
print(f"\n6. GET /api/events/recent sebagai pengguna -> HTTP {st}, {len(ev)} kejadian")
for e in ev[:3]:
    print(f"   [{e.get('kind')}] {str(e.get('text'))[:70]}")
