"""Periksa hasil satu tugas chat lewat API + berkas di disk.

Bukti rantai hidup yang diminta skill: jawaban ada di task["answer"], DAN
berkasnya benar-benar ada di folder kerja.
"""
import json
import pathlib
import urllib.request

BASE = "http://127.0.0.1:8799"
TOKEN = pathlib.Path("/root/AstroZ/app_token.txt").read_text().strip()


def ambil(jalur):
    req = urllib.request.Request(BASE + jalur)
    req.add_header("Authorization", "Bearer " + TOKEN)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


jalan = ambil("/api/tasks/running")
print("masih berjalan:", len(jalan.get("running", [])))
for t in jalan.get("running", []):
    print("  ", t.get("id"), t.get("tahap"), t.get("prompt", "")[:60])

data = ambil("/api/tasks")
tugas = data.get("tasks", data if isinstance(data, list) else [])
print("jumlah tugas:", len(tugas))
if tugas:
    t = tugas[-1]
    print("id       :", t.get("id"))
    print("keadaan  :", t.get("state") or t.get("status"))
    ans = (t.get("answer") or "").strip()
    print("jawaban  :", (ans[:200] + "...") if len(ans) > 200 else ans)

# berkas yang diminta
kandidat = list(pathlib.Path("/root/AstroZ/runtime/users").glob("*/workspace/halo.txt"))
kandidat += list(pathlib.Path("/root/AstroZ/workspace").glob("halo.txt"))
print("berkas halo.txt ditemukan:", [str(p) for p in kandidat])
for p in kandidat:
    print("   isi:", repr(p.read_text()[:200]))
