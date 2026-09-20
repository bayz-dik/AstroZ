"""Pantau satu tugas sampai selesai, lewat API.

Dipakai untuk membuktikan rantai chat masih hidup sesudah perubahan tampilan.
Perubahan CSS tidak bisa menyentuh backend, jadi uji ini memisahkan
"tampilan berubah" dari "ada yang rusak di alur tugas".
"""
import json
import pathlib
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8799"
TOKEN = pathlib.Path("/root/AstroZ/app_token.txt").read_text().strip()


def ambil(jalur):
    r = urllib.request.Request(BASE + jalur)
    r.add_header("Authorization", "Bearer " + TOKEN)
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode())


jalan = ambil("/api/tasks/running").get("running", [])
if not jalan:
    print("tidak ada tugas berjalan")
    sys.exit(0)

t = jalan[0]
tid = t["id"]
print(f"memantau tugas {tid}: {t.get('prompt','')[:60]}")
print(f"  tahap: {t.get('tahap')} | pekerja: {[p.get('nama') for p in t.get('pekerja',[])]}")

for i in range(80):
    time.sleep(6)
    d = ambil(f"/api/tasks/{tid}")
    st = d.get("state") or d.get("status")
    ans = (d.get("answer") or "").strip()
    if i % 3 == 0:
        print(f"  [{i*6:4d}s] status={st} tahap={d.get('tahap')} jawaban={ans[:60]!r}")
    if st in ("done", "error", "cancelled"):
        print(f"\nSELESAI: status={st}")
        print("JAWABAN:", ans[:500])
        sys.exit(0 if st == "done" else 2)

print("\nbelum selesai setelah 8 menit")
sys.exit(1)
