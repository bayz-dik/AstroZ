"""Bukti pemisahan folder kerja antar pengguna, dijalankan pada server hidup.

Alur: admin membuat kode undangan, pengguna baru mendaftar, pengguna itu
menjalankan tugas tulis berkas lewat /api/chat, lalu diperiksa di mana berkasnya
mendarat dan apa yang bisa dia lihat.

Token tidak pernah dicetak; hanya panjangnya.
"""
import json
import pathlib
import re
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8799"
NAMA = "tespisah"
BERKAS = "uji_pisah.txt"
ISI = "punya tespisah"
ADMIN_WS = pathlib.Path("/root/AstroZ/workspace")
USER_WS = pathlib.Path(f"/root/AstroZ/runtime/users/{NAMA}/workspace")


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
        return e.code, json.loads(e.read().decode() or "{}")


adm = re.search(
    r"^Token  : ([A-Za-z0-9_-]{20,})$",
    pathlib.Path("/mnt/sdcard/Download/AstroZ/token_admin_astroz.txt").read_text(),
    re.M,
).group(1)

# 1. admin membuat kode undangan
st, d = ambil("/api/undangan", adm, "POST", {"peran": "user", "maks": 1})
kode = d["undangan"]["kode"]
print(f"1. kode undangan dibuat: {kode} (maks {d['undangan']['maks']})")

# 2. pengguna baru mendaftar
st, d = ambil("/api/undangan/pakai", None, "POST", {"kode": kode, "nama": NAMA})
tok = d["akun"]["token"]
pathlib.Path("/tmp/tok_tespisah").write_text(tok)
pathlib.Path("/tmp/tok_tespisah").chmod(0o600)
print(f"2. akun {d['akun']['nama']} dibuat, peran {d['akun']['peran']}, token {len(tok)} karakter")

# 3. di mana folder kerjanya menurut server
st, d = ambil("/api/state", tok)
print(f"3. folder kerja pengguna menurut server: {d['project']['dir']}")
print(f"   folder kerja admin menurut server   : ", end="")
st2, d2 = ambil("/api/state", adm)
print(d2["project"]["dir"])

# 4. apa yang bisa dibaca pengguna
st, tree = ambil("/api/project/tree", tok)
nama_berkas = sorted(e.get("name") or e.get("nama") or "" for e in (tree.get("entries") or []))
print(f"4. panel Berkas pengguna: {tree.get('dir')} ({len(nama_berkas)} entri)")
st, tree_adm = ambil("/api/project/tree", adm)
adm_entri = sorted(e.get("name") or e.get("nama") or "" for e in (tree_adm.get("entries") or []))
print(f"   panel Berkas admin   : {tree_adm.get('dir')} ({len(adm_entri)} entri)")
print(f"   berkas admin terlihat oleh pengguna? {bool(set(nama_berkas) & set(adm_entri) - {'lampiran'})}")
for jalan in ("/api/akun", "/api/undangan", "/api/gateway/key", "/api/workers", "/api/config"):
    st, _ = ambil(jalan, tok)
    print(f"   {jalan} sebagai pengguna -> HTTP {st}")

# 5. pengguna menjalankan tugas tulis berkas
st, d = ambil("/api/chat", tok, "POST", {
    "text": f"Buat berkas {BERKAS} berisi satu baris: {ISI}",
    "workflow": "small",
    "baru": True,
})
tid = d["task_id"]
print(f"5. tugas dikirim: {tid} (sesi {d['session']})")

for _ in range(60):
    time.sleep(15)
    st, r = ambil("/api/tasks/running", tok)
    if not r.get("running"):
        break
st, d = ambil("/api/tasks", tok)
t = next((x for x in d["tasks"] if x["id"] == tid), None)
print(f"6. status tugas: {t.get('status')} | owner: {t.get('owner')} | workspace: {t.get('workspace')}")
print(f"   jawaban: {str(t.get('answer'))[:160]}")

# 7. di mana berkasnya mendarat
p_user = USER_WS / BERKAS
p_admin = ADMIN_WS / BERKAS
print(f"7. ada di folder pengguna ({p_user})? {p_user.exists()}")
if p_user.exists():
    print(f"   isinya: {p_user.read_text()!r}")
print(f"   ada di folder admin ({p_admin})? {p_admin.exists()}")
print(f"   berkas baru di folder admin: "
      f"{sorted(x.name for x in ADMIN_WS.glob('uji_pisah*'))}")

# 8. pengguna lain tidak bisa menyentuh tugas milik orang lain
st, r = ambil(f"/api/tasks/{tid}/hentikan", adm, "POST", {})
print(f"8. admin menghentikan tugas pengguna -> HTTP {st} {r.get('ok')}")
