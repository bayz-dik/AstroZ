import sys
import time

sys.path.insert(0, "/root/AstroZ")
import orchestrator  # noqa: E402
import config  # noqa: E402
import project  # noqa: E402

cfg = config.load()
model = cfg["gateway"]["model"]
d = project.project_dir()
st = {
    "title": "Tambah fungsi sapa",
    "detail": ("Buat berkas sapa.py berisi fungsi sapa(nama) yang mengembalikan "
               "'Halo <nama>'. Tambahkan tes di tests/test_sapa.py."),
}
o = orchestrator.Orchestrator()
for w in ("codex", "opencode"):
    tanya = (
        "SEBELUM mengerjakan apa pun, jawab pertanyaan ini saja.\n"
        f"Tugas: {st['detail'][:1200]}\n\n"
        "Berkas mana saja yang akan kamu ubah atau buat untuk tugas itu? "
        "Tulis jalur relatif terhadap folder kerja, satu berkas per baris, "
        "tanpa penjelasan lain. Jangan menjalankan alat apa pun dan jangan "
        "mengubah berkas dulu."
    )
    t0 = time.time()
    res = o._worker_prompt(w, tanya, "uji-mentah", str(d), model, retries=1)
    print(f"===== {w} ok={res.get('ok')} {round(time.time() - t0, 1)}s", flush=True)
    print("--- teks mentah ---", flush=True)
    print((res.get("text") or "")[:2500], flush=True)
    print("--- setelah clean_output ---", flush=True)
    print(orchestrator.clean_output(res.get("text") or "")[:1500], flush=True)
