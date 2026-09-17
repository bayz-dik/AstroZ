import sys
import time

sys.path.insert(0, "/root/AstroZ")
import orchestrator  # noqa: E402
import config  # noqa: E402
import project  # noqa: E402

cfg = config.load()
model = cfg["gateway"]["model"]
d = project.project_dir()
print("folder kerja:", d, flush=True)
print("model:", model, flush=True)

st = {
    "title": "Tambah fungsi sapa",
    "detail": ("Buat berkas sapa.py berisi fungsi sapa(nama) yang mengembalikan "
               "'Halo <nama>'. Tambahkan tes di tests/test_sapa.py."),
}
o = orchestrator.Orchestrator()
for w in ("omp", "codex"):
    t0 = time.time()
    klaim = o._klaim_untuk("verifikasi", st, "tambah fungsi sapa", w, str(d), model, cfg)
    print(f"[{w}] {round(time.time() - t0, 1)}s klaim={klaim}", flush=True)
