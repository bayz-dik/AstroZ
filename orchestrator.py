"""Hermes orchestrator: plan -> workers (parallel) -> discussion -> test -> review.

Every stage emits hub events so the web UI shows live what Hermes and each
worker are doing. Worker output is streamed line by line, not buffered.
"""
from __future__ import annotations

import json
import os
import pathlib
import queue
import re
import signal
import subprocess
import threading
import time
import uuid
from typing import Any

import adapters
import config
import hub
import project
from gateway import Gateway

TASKS: dict[str, dict] = {}
TASKS_FILE = config.RUNTIME / "tasks.json"
# Proses pekerja yang sedang hidup, per id tugas. Dipakai untuk menghentikan
# tugas dari UI: tanpa daftar ini, tugas yang berjalan hanya bisa ditunggu.
PROSES: dict[str, list] = {}
_DIHENTIKAN: set[str] = set()
_TASK_FIELDS = (
    "id", "prompt", "status", "size", "workers", "model", "plan", "results",
    "test", "review", "summary", "commit", "created", "finished", "answer",
    "session", "kind", "sources", "procs",
)

# Sumber yang dipakai jawaban. Model menuliskannya di baris terakhir sebagai
# `SUMBER: nama | url`. Baris itu diangkat keluar dari teks jawaban dan
# disimpan terpisah supaya UI bisa menampilkannya sebagai chip seperti di
# aplikasi pesan, bukan sebagai teks mentah di tengah jawaban.
_SUMBER_RX = re.compile(r"^\s*sumber\s*:\s*(.+?)\s*\|\s*(https?://\S+)\s*$", re.I)
_URL_RX = re.compile(r"https?://[^\s)>\]]+")


def _nama_sumber(url: str) -> str:
    """Nama pendek dari sebuah tautan: domain tanpa www."""
    host = url.split("//", 1)[-1].split("/", 1)[0].split("?", 1)[0]
    return host[4:] if host.startswith("www.") else host


def pisah_sumber(text: str) -> tuple[str, list[dict]]:
    """Pisahkan baris SUMBER dari teks jawaban.

    Mengembalikan (teks tanpa baris sumber, daftar sumber). Satu sumber
    berbentuk {"nama": ..., "url": ...}; duplikat dibuang, urutan dipertahankan.
    """
    if not text:
        return "", []
    sisa: list[str] = []
    sumber: list[dict] = []
    dilihat: set[str] = set()
    for baris in text.splitlines():
        m = _SUMBER_RX.match(baris)
        if not m:
            sisa.append(baris)
            continue
        nama = m.group(1).strip(" -·|")[:60] or _nama_sumber(m.group(2))
        url = m.group(2).rstrip(".,;")
        if url in dilihat:
            continue
        dilihat.add(url)
        sumber.append({"nama": nama, "url": url})
    bersih = re.sub(r"\n{3,}", "\n\n", "\n".join(sisa)).strip()
    return bersih, sumber[:6]


def sumber_dari_catatan(text: str, jawaban: str, maks: int = 3) -> list[dict]:
    """Cadangan kalau model lupa menulis baris SUMBER.

    Hanya tautan yang domainnya benar-benar disebut di jawaban yang dipakai,
    jadi tidak ada sumber yang ditempel asal-asalan.
    """
    out: list[dict] = []
    if not text or not jawaban:
        return out
    for url in _URL_RX.findall(text):
        nama = _nama_sumber(url)
        if nama and nama in jawaban and url not in {s["url"] for s in out}:
            out.append({"nama": nama, "url": url.rstrip(".,;")})
        if len(out) >= maks:
            break
    return out

# Terminal control sequences and progress noise that worker CLIs emit around
# their real output. Stripped before anything reaches a human.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
_NOISE = (
    re.compile(r"^\s*[>»]\s*(build|plan|edit|run|review|write|think)\b", re.I),
    re.compile(r"^\s*still starting after", re.I),
    re.compile(r"^\s*logs:\s*/root/", re.I),
    re.compile(r"^\s*re-run with pi_debug_startup", re.I),
    re.compile(r"^\s*wrote file successfully", re.I),
    re.compile(r"^\s*working\.{0,3}\s*$", re.I),
    re.compile(r"^\s*(thinking|processing|starting)\.{0,3}\s*$", re.I),
    re.compile(r"^\s*(files?|tokens?|cost|duration|model)\s*[:=]\s*[\d.$]+", re.I),
    re.compile(r"^[\s│┃|┌┐└┘├┤─━=_*·•·]+$"),
    re.compile(r"^\s*(done|ok|success)\.?\s*$", re.I),
)


def clean_output(text: str) -> str:
    """Worker stdout turned into prose: ANSI off, progress noise out."""
    if not text:
        return ""
    plain = _ANSI.sub("", text).replace("\r", "\n")
    lines: list[str] = []
    for raw in plain.splitlines():
        line = raw.rstrip()
        if not line.strip():
            lines.append("")
            continue
        if any(rx.search(line) for rx in _NOISE):
            continue
        # a bare filesystem path is a tool echo, not an answer
        if line.strip().startswith(("/root/", "/tmp/", "/home/")) and " " not in line.strip():
            continue
        lines.append(line.strip())
    out = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def best_answer_text(results: list[dict]) -> str:
    """The most human line a worker produced, used when no LLM is available."""
    for r in reversed(results or []):
        if not r.get("ok"):
            continue
        clean = clean_output(r.get("text") or "")
        if not clean:
            continue
        lines = [ln for ln in clean.splitlines() if len(ln) >= 12 and any(c.isalpha() for c in ln)]
        if lines:
            return " ".join(lines[-3:])[:600]
        return clean[-600:]
    return ""


def _persist_tasks() -> None:
    """Keep task history across restarts (the UI and plugin both read it)."""
    try:
        items = sorted(TASKS.values(), key=lambda t: t.get("created", 0), reverse=True)[:60]
        slim = [{k: t.get(k) for k in _TASK_FIELDS if k in t} for t in items]
        TASKS_FILE.write_text(json.dumps(slim, ensure_ascii=False, default=str))
    except Exception:
        pass


def load_tasks() -> int:
    if not TASKS_FILE.exists():
        return 0
    try:
        items = json.loads(TASKS_FILE.read_text())
    except Exception:
        return 0
    for t in items:
        if isinstance(t, dict) and t.get("id"):
            # A task that was mid-flight when the server stopped is not running
            # any more: report it as interrupted instead of a permanent "running".
            if t.get("status") == "running":
                t["status"] = "interrupted"
                _bersihkan_proses(t)
            TASKS[t["id"]] = t
    return len(TASKS)


def _bersihkan_proses(t: dict) -> None:
    """Matikan proses pekerja yang tertinggal dari tugas yang sudah tidak jalan.

    Server yang mati mendadak (atau dihentikan paksa) meninggalkan CLI pekerja
    yang masih hidup: prosesnya bukan anak siapa-siapa lagi, dan tugasnya tidak
    akan pernah selesai. Tiap pekerja dijalankan dengan sesi proses sendiri
    (start_new_session), jadi pgid-nya bisa dimatikan langsung.
    """
    for pid in list(t.get("procs") or []):
        try:
            os.killpg(os.getpgid(int(pid)), signal.SIGKILL)
            hub.emit("system", f"Proses pekerja tertinggal dimatikan (pid {pid})", task=t.get("id"), ok=True)
        except Exception:
            pass
    t["procs"] = []
_TASK_LOCK = threading.Lock()


def get_task(tid: str) -> dict | None:
    return TASKS.get(tid)


def list_tasks(limit: int = 50) -> list[dict]:
    items = sorted(TASKS.values(), key=lambda t: t["created"], reverse=True)
    return [
        {
            "id": t["id"],
            "prompt": t["prompt"],
            "status": t["status"],
            "size": t.get("size"),
            "workflow": t.get("workflow"),
            "created": t["created"],
            "finished": t.get("finished"),
            "model": t.get("model"),
            "workers": t.get("workers", []),
            "summary": (t.get("summary") or "")[:2000],
            "answer": (t.get("answer") or "")[:4000],
            "session": t.get("session") or "",
        }
        for t in items[:limit]
    ]


def _is_retryable(text: str) -> bool:
    """True for transient upstream conditions that a retry can actually fix."""
    if not text:
        return True
    low = text.lower()
    for token in ("429", "503", "502", "all providers busy", "rate limit", "overloaded",
                  "timeout", "timed out", "connection reset", "temporarily unavailable"):
        if token in low:
            return True
    return False


def _dari_pekerja() -> bool:
    """True kalau proses ini jalan sebagai pekerja CLI, bukan sebagai server UI.

    Dipakai untuk mencegah pekerja ikut membuat folder kerja baru: mereka
    dijalankan dengan cwd yang sudah disiapkan, jadi tidak perlu menyiapkan apa pun.
    """
    return bool(os.environ.get("ASTROZ_PEKERJA"))


def _daftar_proses(tid: str, p) -> None:
    with _TASK_LOCK:
        PROSES.setdefault(tid, []).append(p)
        # pgid-nya ikut dicatat di tugas supaya proses yang tertinggal dari
        # server yang mati mendadak bisa dimatikan saat server hidup lagi.
        t = TASKS.get(tid)
        if t is not None:
            t.setdefault("procs", [])
            if p.pid not in t["procs"]:
                t["procs"].append(p.pid)


def _lepas_proses(tid: str, p) -> None:
    with _TASK_LOCK:
        sisa = [x for x in PROSES.get(tid, []) if x is not p]
        if sisa:
            PROSES[tid] = sisa
        else:
            PROSES.pop(tid, None)


def dihentikan(tid: str) -> bool:
    """True kalau tugas ini sudah diminta berhenti.

    Pekerja CLI bisa memanggil sub-proses sendiri, jadi mematikan proses yang
    tercatat saja tidak cukup. Tahap berikutnya pada tugas yang sama harus tahu
    bahwa tugasnya sudah batal, supaya tidak lanjut ke tes dan penilaian.
    """
    with _TASK_LOCK:
        return tid in _DIHENTIKAN


def hentikan(tid: str) -> dict:
    """Hentikan satu tugas: tandai batal, matikan proses pekerja yang hidup.

    Kill per proses, bukan lewat pola nama: pola `pkill -f` juga cocok dengan
    shell yang menjalankannya, dan di sini pola itu akan mematikan server UI.
    """
    t = TASKS.get(tid)
    if not t:
        return {"ok": False, "error": "tugas tidak ditemukan"}
    with _TASK_LOCK:
        _DIHENTIKAN.add(tid)
        hidup = list(PROSES.get(tid, []))
    dimatikan = 0
    for p in hidup:
        try:
            if p.poll() is None:
                # Prosesnya dijalankan dengan start_new_session, jadi pgid-nya
                # sendiri: mematikan grupnya ikut membunuh anak proses CLI
                # (ripgrep, shell bantu) yang kalau tidak akan tertinggal hidup.
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception:
                    p.kill()
                dimatikan += 1
        except Exception:
            pass
    if t.get("status") == "running":
        t["status"] = "cancelled"
        t["finished"] = time.time()
        t["answer"] = t.get("answer") or "Tugas dihentikan dari UI sebelum selesai."
        t["summary"] = (t.get("summary") or "") + " · dihentikan pengguna"
    hub.emit("task", f"Tugas dihentikan dari UI ({dimatikan} proses pekerja dimatikan)",
             task=tid, phase="cancel", ok=False)
    _persist_tasks()
    return {"ok": True, "id": tid, "proses_dimati": dimatikan}


def cepatkah(prompt: str) -> bool:
    """True kalau pesan ini cukup dijawab langsung oleh model, tanpa tim.

    Terukur: pertanyaan seperti "malam" atau "halo" dulu dijalankan sebagai tugas
    penuh. Akibatnya dua hal buruk: jawabannya lama karena menunggu pekerja CLI
    hidup, dan folder kerja baru dibuat padahal tidak ada yang dikerjakan.
    Aturannya: kalau tidak ada tanda pekerjaan berkas atau kode, dan pesannya
    pendek, jawab langsung.
    """
    p = (prompt or "").strip().lower()
    if not p:
        return False
    # tanda pekerjaan berkas, kode, atau perintah yang harus dijalankan
    tanda_kerja = (
        ".py", ".js", ".ts", ".tsx", ".html", ".css", ".json", ".md", ".txt", ".sh", ".yml", ".yaml",
        "buat berkas", "buat file", "tulis berkas", "tulis file", "simpan ke", "hapus berkas", "hapus file",
        "clone", "commit", "push", "pull", "git ", "npm ", "pip ", "install", "jalankan", "run ",
        "perbaiki", "refactor", "debug", "error", "galat", "fungsi", "function", "class", "script",
        "folder", "direktori", "proyek", "project", "repo", "test", "tes", "server", "api", "database",
        "web", "html", "halaman", "website", "aplikasi", "app", "kode", "program", "syntax",
    )
    if any(t in p for t in tanda_kerja):
        return False
    # perintah beruntun (banyak baris) selalu dianggap pekerjaan
    if len(p.splitlines()) > 2:
        return False
    if len(p) <= 220:
        return True
    return False


def _model_ditolak(teks: str) -> bool:
    """True kalau kegagalan ini soal modelnya tidak dikenal, bukan soal tugasnya.

    Terukur: gateway menjawab "unrecognized_model" untuk beberapa model yang
    masih ada di daftar cadangan lama. Mencoba model berikutnya hanya membuang
    waktu kalau yang berikutnya juga tidak dikenal, jadi rantai cadangan
    dipotong begitu jenis galat ini terlihat.
    """
    low = (teks or "").lower()
    return any(t in low for t in ("unrecognized_model", "model_not_found", "unknown model",
                                 "no such model", "invalid model", "model is not supported"))


def model_chain(cfg: dict, primary: str) -> list[str]:
    """Ordered models to try for a task: the selected one, then the fallbacks.

    A single free upstream provider saturates easily, so a task that dies on a
    429 is a routing problem, not a work problem. Fallbacks come from
    ``gateway.fallback_models`` and, when empty, from the models that answered
    the last health probe. Cadangan yang pernah ditolak gateway dibuang, supaya
    satu tugas tidak menunggu tiga model mati berturut-turut.
    """
    gw = cfg["gateway"]
    mati = {m for m in (gw.get("model_rejected") or []) if m}
    chain = [primary] if primary else []
    for m in gw.get("fallback_models") or []:
        if m and m not in chain and m not in mati:
            chain.append(m)
    if gw.get("auto_fallback", True):
        for m in gw.get("healthy") or []:
            if m and m not in chain and m not in mati:
                chain.append(m)
    return chain[:5]


def tandai_model_ditolak(model: str) -> None:
    """Catat model yang ditolak gateway supaya tidak dicoba lagi di tugas lain."""
    if not model:
        return
    try:
        cfg = config.load()
        daftar = list(cfg["gateway"].get("model_rejected") or [])
        if model not in daftar:
            daftar.append(model)
            cfg["gateway"]["model_rejected"] = daftar[-40:]
            config.save(cfg)
            hub.emit("gateway", f"Model {model} ditolak gateway, dikeluarkan dari daftar cadangan", model=model)
    except Exception:
        pass


def _pick_workers(cfg: dict, want: int) -> list[str]:
    enabled = [k for k, v in cfg["workers"].items() if v.get("enabled")]
    installed = [k for k in enabled if adapters.ADAPTERS[k].path or adapters.ADAPTERS[k].probe().get("installed")]
    order = [k for k in (cfg["workflow"].get("worker_order") or []) if k in adapters.ADAPTERS]
    if not order:
        order = list(adapters.ADAPTERS)
    installed = [k for k in order if k in installed]
    return installed[:want] if installed else enabled[:want]


def _worker_cost(cfg: dict, worker: str) -> float:
    """Typical cost of one run, in the config's own unit (USD per request)."""
    try:
        return float((cfg["workflow"].get("worker_cost") or {}).get(worker, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _pick_cheapest(cfg: dict, want: int = 1, exclude: set[str] | None = None) -> list[str]:
    """Installed workers, cheapest first, the escalation order for retries."""
    installed = [w for w in _pick_workers(cfg, 99) if w not in (exclude or set())]
    return sorted(installed, key=lambda w: (_worker_cost(cfg, w), _pick_workers(cfg, 99).index(w)))[:want]


def _worker_env(worker: str, model: str) -> dict:
    cfg = config.load()
    gw = {**cfg["gateway"], "model": model}
    return adapters.ADAPTERS[worker].env(gw, model)


def _bin_dir() -> str:
    """Folder tempat uvx dan uv dipasang di mesin ini.

    Plugin MCP yang dipasang dari UI bisa memakai `uvx` (server berbasis Python).
    Terukur: omp gagal memuat plugin itu dengan "Executable not found in $PATH:
    uvx", karena /root/.hermes/bin tidak ada di PATH pekerja. Tambahkan folder
    yang benar-benar memuat binernya, jangan tebak-tebak.
    """
    for kandidat in (pathlib.Path.home() / ".hermes" / "bin", pathlib.Path("/usr/local/bin")):
        if (kandidat / "uvx").exists() or (kandidat / "uv").exists():
            return str(kandidat)
    return ""


def _worker_brief(cwd: str, model: str) -> str:
    """Konteks singkat untuk setiap pekerja: folder kerja dan alat yang tersedia.

    Pekerja CLI tidak tahu apa pun soal AstroZ. Tanpa keterangan ini, alat cari,
    buka, dan lihat ada di PATH tapi tidak pernah dipakai, dan pekerja mengarang
    jawaban ketika tugasnya butuh informasi dari luar.
    """
    meta = (config.load()["gateway"].get("model_meta", {}) or {}).get(model) or {}
    caps = meta.get("caps") or {}
    bisa_lihat = bool(caps.get("vision"))
    baris = [
        "Konteks kerja:",
        f"- Folder kerja: {cwd}. Simpan semua berkas di dalam folder ini.",
        "- Alat tambahan, jalankan lewat shell:",
        '    cari "kata kunci"   cari di web, hasilnya judul, tautan, ringkasan',
        "    buka <url>           ambil isi satu halaman web sebagai teks",
        "    lihat <berkas>       baca isi berkas gambar (PNG, JPEG, WebP, GIF) jadi teks",
        "- Pakai cari dan buka kalau tugas butuh informasi dari luar. Jangan mengarang fakta:",
        "  kalau tidak ketemu, katakan tidak ketemu.",
        "- Kalau jawabanmu memakai informasi dari halaman web, tutup jawaban dengan satu baris",
        "  per sumber, persis format ini: SUMBER: nama sumber | https://tautan-persis",
    ]
    if bisa_lihat:
        baris.append(f"- Model yang kamu pakai ({model}) bisa melihat gambar langsung.")
    else:
        baris.append(f"- Model yang kamu pakai ({model}) tidak bisa melihat gambar langsung, pakai `lihat`.")
    # Skill yang dipasang dari UI sudah ditautkan ke folder yang kamu baca sendiri
    # (~/.claude/skills, ~/.agents/skills, $CODEX_HOME/skills, ~/.omp/agent/skills).
    # Sebutkan supaya kamu benar-benar memakainya, bukan mengarang caranya sendiri.
    try:
        import plugins as _plugins

        skills = _plugins.skill_ringkas_untuk_pekerja(24)
    except Exception:
        skills = []
    if skills:
        baris.append("- Skill siap pakai (sudah ada di folder skill kamu, pakai kalau tugasnya cocok):")
        baris.append("    " + ", ".join(skills))
    baris.append("- Jawab dalam bahasa Indonesia. Jangan pakai tanda pisah panjang.")
    # Gaya bahasa: pekerja menulis ringkasan, komentar kode, dan teks berkas.
    # Tanpa aturan ini, keluarannya penuh pembukaan basa-basi dan kata pemasaran
    # yang langsung terbaca sebagai tulisan mesin.
    baris.append(
        "- Tulis seperti orang yang menjelaskan pekerjaannya, bukan seperti asisten: "
        "langsung ke isinya, tanpa pembukaan pujian, tanpa kata seperti 'tentu', "
        "'sebagai AI', 'solusi menyeluruh', atau 'mudah dan cepat'. "
        "Kalau ada skill antislop atau no-ai-slop di daftar skill, pakai untuk semua teks yang kamu tulis."
    )
    return "\n".join(baris) + "\n\n"


def _menunggu_jaringan(pid: int) -> bool:
    """True kalau proses punya satu koneksi TCP yang sedang terbuka.

    Dipakai pembatas kemacetan: pekerja CLI diam saat model berpikir lama, dan
    koneksi ke gateway yang masih terbuka membedakan "menunggu jawaban" dari
    "benar-benar macet".
    """
    try:
        inode: set[str] = set()
        for f in pathlib.Path(f"/proc/{pid}/fd").iterdir():
            try:
                taut = os.readlink(f)
            except Exception:
                continue
            if taut.startswith("socket:["):
                inode.add(taut[8:-1])
        if not inode:
            return False
        for jalur in ("/proc/net/tcp", "/proc/net/tcp6"):
            try:
                baris = pathlib.Path(jalur).read_text().splitlines()[1:]
            except Exception:
                continue
            for b in baris:
                kolom = b.split()
                if len(kolom) >= 10 and kolom[9] in inode and kolom[3] == "01":
                    return True
    except Exception:
        pass
    return False


def run_worker(worker: str, prompt: str, task_id: str, cwd: str, model: str, timeout: int = 900,
               retries: int = 3) -> dict:
    """Run one worker CLI, streaming its stdout/stderr into the hub.

    A worker that fails for a transient reason (gateway 429/503, provider busy,
    timeout) is retried, with a different worker if one is available, because
    the alternative is a task that dies for a reason the team can route around.
    """
    a = adapters.ADAPTERS[worker]
    if not a.path:
        a.probe()
    if not a.path:
        hub.emit("worker", f"[{worker}] tidak terpasang", task=task_id, worker=worker, ok=False)
        return {"worker": worker, "ok": False, "error": "not installed", "text": ""}
    env = {**os.environ, **_worker_env(worker, model)}
    # PWD must follow cwd. opencode resolves its working directory as
    # `path.resolve(process.env.PWD ?? process.cwd())`, PWD wins, so an
    # inherited PWD from the UI server made it edit one directory above the
    # project: files landed in the repo root, its later test/git steps saw
    # nothing, and the task still reported success. Children that trust PWD
    # over getcwd() (opencode, some shells/scripts) need this to agree.
    env["PWD"] = cwd
    # Tandai proses ini sebagai pekerja. project.project_dir() dan
    # ensure_repo() memakainya untuk menolak membuat folder kerja baru: pekerja
    # sudah dijalankan di dalam folder yang benar.
    env["ASTROZ_PEKERJA"] = "1"
    # Alat bantu (cari, buka, lihat) ada di folder tools; taruh di depan PATH
    # supaya pekerja bisa memanggilnya tanpa path panjang. Folder uvx ikut
    # dimasukkan karena plugin MCP yang dipasang dari UI bisa memakainya.
    jalur = [str(config.ROOT / "tools")]
    biner = _bin_dir()
    if biner:
        jalur.append(biner)
    jalur.append(env.get("PATH", ""))
    env["PATH"] = os.pathsep.join(jalur)
    prompt = _worker_brief(cwd, model) + prompt
    last: dict = {}
    for attempt in range(1, max(1, retries) + 1):
        cmd = a.command(prompt, model, cwd)
        hub.emit(
            "worker",
            f"[{worker}] mulai: {prompt[:160]}" + (f" (percobaan {attempt}/{retries})" if attempt > 1 else ""),
            task=task_id,
            worker=worker,
            phase="start",
            cmd=" ".join(cmd)[:400],
            model=model,
            attempt=attempt,
        )
        t0 = time.time()
        out_lines: list[str] = []
        try:
            p = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                stdin=subprocess.DEVNULL,
                # Sesi proses sendiri: supaya "hentikan" bisa mematikan seluruh
                # pohon proses CLI (beserta anak prosesnya) sekaligus, dan supaya
                # Ctrl-C di server tidak ikut menimpa pekerja.
                start_new_session=True,
            )
        except Exception as e:
            hub.emit("worker", f"[{worker}] gagal dijalankan: {e}", task=task_id, worker=worker, ok=False)
            return {"worker": worker, "ok": False, "error": str(e), "text": ""}

        q: queue.Queue = queue.Queue()
        # Daftarkan prosesnya supaya bisa dimatikan dari UI. Tanpa ini tugas yang
        # berjalan hanya bisa ditunggu sampai selesai atau macet.
        _daftar_proses(task_id, p)

        def reader() -> None:
            try:
                for line in p.stdout:  # type: ignore[union-attr]
                    q.put(line)
            except Exception:
                pass
            q.put(None)

        threading.Thread(target=reader, daemon=True).start()
        deadline = t0 + timeout
        buf: list[str] = []
        timed_out = False
        # A worker CLI can wedge while still printing progress chatter (observed:
        # omp emits "Working..." forever, opencode sits in state D printing
        # nothing). The guard therefore measures the last MEANINGFUL line, not
        # the last byte: noise-only output does not count as progress, and a
        # worker that streams real output is never cut off.
        stall = int(config.load()["workflow"].get("stall_seconds") or 240)
        last_useful = t0
        stalled = False
        while True:
            try:
                item = q.get(timeout=1.0)
            except queue.Empty:
                if time.time() > deadline:
                    p.kill()
                    timed_out = True
                    hub.emit("worker", f"[{worker}] melebihi batas waktu {timeout}s", task=task_id, worker=worker, ok=False)
                    break
                if stall and time.time() - last_useful > stall:
                    if _menunggu_jaringan(p.pid):
                        # Ada koneksi TCP aktif: pekerja sedang menunggu jawaban
                        # model, bukan macet. Ini yang dulu salah dinilai macet:
                        # opencode dan claude diam saat model berpikir lama.
                        last_useful = time.time()
                        continue
                    p.kill()
                    timed_out = True
                    stalled = True
                    hub.emit("worker", f"[{worker}] macet tanpa kemajuan selama {stall}s, dihentikan", task=task_id, worker=worker, ok=False)
                    break
                continue
            if item is None:
                break
            line = item.rstrip("\n")
            buf.append(line)
            clean_line = clean_output(line)
            if clean_line:
                last_useful = time.time()
                hub.emit("worker", f"[{worker}] {clean_line[:500]}", task=task_id, worker=worker, phase="out")
            if time.time() > deadline:
                p.kill()
                timed_out = True
                break
        try:
            p.wait(timeout=10)
        except Exception:
            p.kill()
        _lepas_proses(task_id, p)
        raw = "\n".join(buf)
        parsed = a.parse(raw)
        dur = round(time.time() - t0, 2)
        ok = p.returncode == 0 and not timed_out
        dibatalkan = dihentikan(task_id)
        if dibatalkan:
            ok = False
        last = {"worker": worker, "ok": ok, "rc": p.returncode, "duration": dur,
                "text": parsed.get("text") or raw[-6000:], "attempt": attempt,
                "stalled": stalled, "cancelled": dibatalkan,
                **{k: v for k, v in parsed.items() if k not in ("text",)}}
        hub.emit(
            "worker",
            f"[{worker}] {'selesai' if ok else 'gagal'} dalam {dur}s",
            task=task_id,
            worker=worker,
            phase="end",
            ok=ok,
            duration=dur,
            rc=p.returncode,
            result=(parsed.get("text") or "")[-4000:],
            attempt=attempt,
        )
        if ok:
            return last
        if stalled:
            # The CLI itself is wedged, not the route: repeating the same worker
            # on another model just burns another stall window. Let the caller
            # escalate to a different worker instead.
            hub.emit("worker", f"[{worker}] macet, tidak diulang di worker yang sama", task=task_id, worker=worker, phase="stall")
            break
        if attempt >= retries or not _is_retryable(f"{parsed.get('text','')}\n{raw[-3000:]}"):
            break
        wait = 5 * attempt
        hub.emit("worker", f"[{worker}] gagal sementara, dicoba lagi dalam {wait}s", task=task_id, worker=worker, phase="retry")
        time.sleep(wait)
    return last


class Orchestrator:
    def __init__(self) -> None:
        self.cfg = config.load()
        self.gw = Gateway(self.cfg)

    # ------------------------------------------------------------- planning
    def plan(self, prompt: str, size_hint: str = "auto") -> dict:
        cfg = config.load()
        model = cfg["gateway"].get("model")
        workers = _pick_workers(cfg, 4)
        fallback = {
            "size": "medium",
            "goal": prompt,
            "subtasks": [{"title": "Implement request", "detail": prompt, "worker": workers[0] if workers else "claude"}],
            "test_command": project.detect_test_command(),
        }
        if not model or not cfg["gateway"].get("online"):
            return fallback
        sys = (
            "You are Hermes, the orchestrator of a coding team. Classify the task and decompose it.\n"
            "Return ONLY minified JSON with keys: size (small|medium|large), goal (1 sentence), "
            "subtasks (array of {title, detail, worker} where worker is one of "
            f"{workers}), test_command (shell command or empty string).\n"
            "small = single focused edit, 1 subtask. medium = a few files, 2 subtasks. "
            "large = multi-part feature, 3-4 subtasks that can run in parallel.\n"
            "Never invent files. Keep subtask details self-contained and actionable."
        )
        r = self.gw.chat(model, [{"role": "system", "content": sys}, {"role": "user", "content": prompt}], timeout=180, max_tokens=1500)
        if not r.get("ok"):
            hub.emit("plan", f"Perencana tidak bisa dihubungi, dipakai rencana sederhana ({r.get('error','')[:120]})", ok=False)
            return fallback
        text = r["text"].strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
        try:
            start, end = text.find("{"), text.rfind("}")
            plan = json.loads(text[start : end + 1])
        except Exception:
            hub.emit("plan", "Perencana tidak menjawab dalam bentuk yang benar, dipakai rencana sederhana", ok=False, raw=text[:500])
            return fallback
        plan.setdefault("size", "medium")
        plan.setdefault("goal", prompt)
        plan.setdefault("subtasks", fallback["subtasks"])
        plan.setdefault("test_command", project.detect_test_command())
        # The planner tends to guess `python -m pytest`; the detected command is
        # the one that actually runs in this environment.
        detected = project.detect_test_command()
        if detected and (not plan.get("test_command") or "pytest" in str(plan.get("test_command", ""))):
            plan["test_command"] = detected
        if size_hint in ("small", "medium", "large"):
            plan["size"] = size_hint
        return plan

    # -------------------------------------------------------------- workflow
    def submit(self, prompt: str, workflow: str = "auto", workers: list[str] | None = None,
               model: str | None = None, session_id: str | None = None) -> str:
        cfg = config.load()
        tid = uuid.uuid4().hex[:12]
        # Pertanyaan ringan dijawab langsung, jadi tidak perlu folder kerja baru.
        # Tanpa ini setiap "halo" meninggalkan satu folder yang menumpuk.
        ringan = workflow == "auto" and cepatkah(prompt)
        t = {
            "id": tid,
            "prompt": prompt,
            "status": "running",
            "created": time.time(),
            "workflow": workflow,
            "model": model or cfg["gateway"].get("model"),
            "workers": [],
            "results": [],
            "session": session_id or "",
            "size": "chat" if ringan else "",
            "workspace": "" if ringan else str(project.project_dir()),
        }
        with _TASK_LOCK:
            TASKS[tid] = t
        _persist_tasks()
        hub.emit("task", f"Pesan diterima: {prompt[:120]}", task=tid, workflow=workflow,
                 model=t["model"], phase="created", session=session_id or "")
        threading.Thread(target=self._run, args=(tid, prompt, workflow, workers), daemon=True).start()
        return tid

    def _run(self, tid: str, prompt: str, workflow: str, workers: list[str] | None) -> None:
        t = TASKS[tid]
        try:
            cfg = config.load()
            model = t["model"] or cfg["gateway"].get("model")
            if not model:
                raise RuntimeError("no model configured, pick one in the Gateway tab")
            t["model"] = model

            # --- jawab langsung -------------------------------------------
            # Pertanyaan seperti "halo" atau "malam" tidak butuh pekerja CLI,
            # tidak butuh folder kerja, dan tidak boleh menunggu satu menit.
            if workflow == "auto" and cepatkah(prompt):
                t["size"] = "chat"
                t["workers"] = []
                hub.emit("plan", "Dijawab langsung, tanpa pekerja", task=tid, size="chat", phase="end")
                gw = Gateway(cfg)
                sys_pesan = (
                    "Kamu AstroZ, asisten kerja. Jawab singkat dan ramah dalam bahasa Indonesia, "
                    "satu sampai tiga kalimat. Jangan menyebut alat, berkas, atau pekerja."
                )
                jawab = gw.chat(model, [
                    {"role": "system", "content": sys_pesan},
                    {"role": "user", "content": prompt},
                ])
                teks = (jawab.get("text") or "").strip()
                if not teks:
                    raise RuntimeError(jawab.get("error") or "model tidak menjawab")
                t["answer"] = teks
                t["status"] = "done"
                t["finished"] = time.time()
                t["results"] = []
                hub.emit("task", "Jawaban dikirim", task=tid, phase="done", ok=True, size="chat")
                _persist_tasks()
                return

            d = project.ensure_repo()
            before = project.git_status()

            # Tugas yang dihentikan sebelum sempat mulai tidak boleh lanjut.
            if dihentikan(tid):
                hub.emit("task", "Tugas dihentikan sebelum mulai", task=tid, phase="cancel", ok=False)
                return

            # --- plan -----------------------------------------------------
            if workflow in ("auto", "medium", "large"):
                hub.emit("plan", "Menyusun rencana kerja", task=tid, phase="start")
                plan = self.plan(prompt, "auto" if workflow == "auto" else workflow)
            else:
                plan = {"size": "small", "goal": prompt, "subtasks": [{"title": prompt[:80], "detail": prompt, "worker": (workers or _pick_workers(cfg, 1))[0]}], "test_command": project.detect_test_command()}
            t["size"] = plan["size"]
            t["plan"] = plan
            hub.emit(
                "plan",
                f"ukuran={plan['size']} · {len(plan.get('subtasks', []))} langkah",
                task=tid,
                plan=plan,
                phase="end",
            )

            chosen = workers or _pick_workers(cfg, 4)
            subtasks = plan.get("subtasks") or []
            size = plan["size"]
            max_par = int(cfg["workflow"].get("max_parallel", 3))
            if size == "small":
                max_par = 1

            # --- execute --------------------------------------------------
            results: list[dict] = []
            if size == "small" or len(subtasks) <= 1:
                st = subtasks[0] if subtasks else {"title": prompt[:80], "detail": prompt, "worker": chosen[0]}
                w = st.get("worker") if st.get("worker") in adapters.ADAPTERS else chosen[0]
                t["workers"] = [w]
                hub.emit("worker", f"Diberikan ke {w}", task=tid, worker=w, phase="assign")
                results.append(self._worker_prompt(w, st.get("detail") or st.get("title") or prompt, tid, str(d), model))
            else:
                # Large tasks run subtasks in parallel and then discuss them.
                # If the planner put every subtask on the same (cheapest) worker,
                # spread them round-robin: the discussion stage is only worth
                # anything when different CLIs actually did the work.
                if size == "large" and len({(s.get("worker") or chosen[0]) for s in subtasks}) == 1:
                    for i, s in enumerate(subtasks):
                        s["worker"] = chosen[i % len(chosen)]
                groups: list[list[dict]] = [subtasks[i : i + max_par] for i in range(0, len(subtasks), max_par)]
                for gi, group in enumerate(groups):
                    threads = []
                    box: list[dict] = []
                    hub.emit("worker", f"Dikerjakan paralel: " + ", ".join(s.get("worker", "?") for s in group), task=tid, phase="assign")
                    for st in group:
                        w = st.get("worker") if st.get("worker") in adapters.ADAPTERS else chosen[0]
                        if w not in t["workers"]:
                            t["workers"].append(w)
                        thr = threading.Thread(
                            target=lambda s=st, ww=w: box.append(self._worker_prompt(ww, s.get("detail") or s.get("title"), tid, str(d), model))
                        )
                        thr.start()
                        threads.append(thr)
                    for thr in threads:
                        thr.join()
                    results.extend(box)
            t["results"] = results

            # Berhenti di sini kalau pengguna sudah menekan hentikan: tes dan
            # penilaian setelahnya cuma membakar waktu untuk tugas yang batal.
            if dihentikan(tid):
                t["status"] = "cancelled"
                t["answer"] = t.get("answer") or "Tugas dihentikan dari UI sebelum selesai."
                t["summary"] = "dihentikan pengguna"
                hub.emit("task", "Tugas dihentikan, sisa tahap dilewati", task=tid, phase="cancel", ok=False)
                return

            # --- escalation -------------------------------------------------
            # Every worker failed? Try other workers before giving up: the
            # gateway routes models per provider, so a second worker often
            # succeeds when the first one's route is busy. More than one
            # alternative is worth trying, because a wedged CLI (observed with
            # omp and opencode in this container) fails regardless of model,
            # while the next worker in the order can finish the job.
            if results and not any(r.get("ok") for r in results):
                tried = {r["worker"] for r in results}
                tries = int(cfg["workflow"].get("escalate_tries", 2))
                alts = [w for w in chosen if w not in tried][:max(0, tries)]
                for alt_w in alts:
                    hub.emit("worker", f"Semua pekerja gagal, dicoba ke {alt_w}", task=tid, phase="escalate")
                    st = subtasks[0] if subtasks else {"detail": prompt}
                    if alt_w not in t["workers"]:
                        t["workers"].append(alt_w)
                    res = self._worker_prompt(alt_w, st.get("detail") or prompt, tid, str(d), model)
                    results.append(res)
                    t["results"] = results
                    if res.get("ok"):
                        break

            # --- discussion ----------------------------------------------
            if cfg["workflow"].get("discussion", True) and len(results) > 1:
                self._discuss(tid, prompt, results, model)

            # --- tests ----------------------------------------------------
            test_res = None
            if cfg["workflow"].get("auto_test", True):
                test_res = project.run_tests(plan.get("test_command") or None, task_id=tid)
                t["test"] = test_res
                # A red test is a work item, not an end state: hand the failure
                # back to a worker once before asking Hermes to review.
                if test_res.get("ok") is False and size != "small":
                    test_res = self._fix_failure(tid, prompt, test_res, d, model, results)
                    t["test"] = test_res

            # --- review ---------------------------------------------------
            review = None
            if cfg["workflow"].get("review", True):
                review = self._review(tid, prompt, results, test_res, model)
                t["review"] = review
                # A review that finds real issues is a work item, not an end
                # state either, hand the reviewer's own issue list back once
                # and re-review. (Green tests do not mean the task is met: a
                # worker can pass its own test while ignoring the requirement.)
                if size != "small" and (review.get("verdict") or "").upper().startswith("FAIL"):
                    fixed = self._fix_review(tid, prompt, review, d, model, results)
                    if fixed:
                        review = self._review(tid, prompt, results, t.get("test"), model)
                        t["review"] = review

            after = project.git_status()
            changed = project.change_summary(2000)
            hub.emit("git", "Perubahan berkas setelah tugas:\n" + (changed[:2000] or "tidak ada perubahan"), task=tid, diffstat=after.get("diffstat"))
            t["summary"] = self._summarize(prompt, results, test_res, review, changed)
            jawaban = self._answer(prompt, results, review, model)
            # Baris `SUMBER: nama | url` keluar dari teks jawaban dan disimpan
            # terpisah: chip sumber di UI tidak boleh tercampur jadi kalimat.
            t["answer"], t["sources"] = pisah_sumber(jawaban)
            if not t["sources"]:
                # Model lupa menuliskan sumbernya. Kalau dia menyebut sebuah
                # domain dan catatan kerja memuat tautannya, itu dipakai.
                t["sources"] = sumber_dari_catatan(
                    "\n".join((r.get("text") or "") for r in (results or [])), t["answer"]
                )
            if t["sources"]:
                hub.emit("task", "Sumber jawaban: " + ", ".join(s["nama"] for s in t["sources"]),
                         task=tid, phase="sources", sources=t["sources"])
            hub.emit("task", "Jawaban siap", task=tid, phase="answer", answer=t["answer"][:4000])
            # Commit only work the task's own verification passed, see
            # _task_is_green. Default off; enable with workflow.auto_commit.
            if cfg["workflow"].get("auto_commit", False) and self._task_is_green(test_res, review):
                t["commit"] = self._auto_commit(tid, prompt, after.get("status") or "")
            t["status"] = "done"
            hub.emit("task", f"Selesai: {t['summary'][:200]}", task=tid, phase="done", summary=t["summary"], test_ok=(test_res or {}).get("ok"))
        except Exception as e:
            t["status"] = "error"
            t["summary"] = f"error: {e}"
            t["answer"] = f"Gagal menyelesaikan tugas: {e}"
            hub.emit("task", f"Gagal: {e}", task=tid, phase="error", ok=False, answer=t["answer"])
        finally:
            t["finished"] = time.time()
            _persist_tasks()

    def _task_is_green(self, test_res: dict | None, review: dict | None) -> bool:
        """True only when the task's own verification actually passed.

        Committing on a FAIL review bakes known-bad work into history behind a
        tidy-looking log, and committing when nothing ran commits unverified
        work. Either way the commit stops meaning "this was checked".
        """
        if test_res is None and review is None:
            return False
        if test_res is not None and test_res.get("ok") is not True:
            return False
        if review is not None and not (review.get("verdict") or "").upper().startswith("PASS"):
            return False
        return True

    def _auto_commit(self, tid: str, prompt: str, porcelain: str) -> dict:
        """Commit a green task's changes, with the task text as the subject."""
        if not (porcelain or "").strip():
            return {"ok": True, "skipped": "no changes"}
        subject = " ".join(prompt.strip().split())
        if len(subject) > 68:
            subject = subject[:65].rstrip() + "..."
        message = f"{subject}\n\ntask: {tid}"
        res = project.git_commit_all(message)
        out = res.get("out") or ""
        ok = res.get("rc") == 0 or "nothing to commit" in out
        hub.emit("git", f"Commit otomatis {'tersimpan' if ok else 'GAGAL'}: {subject[:80]}",
                 task=tid, ok=ok, out=out[:300])
        return {"ok": ok, "message": message, **res}

    def _worker_prompt(self, worker: str, prompt: str, tid: str, cwd: str, model: str) -> dict:
        """Run one subtask on one worker, walking the model fallback chain.

        The chain matters more than the retry: the same prompt on the same
        worker succeeds immediately when routed to a model whose upstream is not
        saturated, so a failure here is usually routing, not capability.
        """
        cfg = config.load()
        wmodel = cfg["workers"].get(worker, {}).get("model") or model
        chain = model_chain(cfg, wmodel)
        res: dict = {}
        for i, m in enumerate(chain):
            if i:
                hub.emit("worker", f"[{worker}] coba ulang dengan model cadangan {m}", task=tid, worker=worker, phase="fallback", model=m)
            res = run_worker(worker, prompt, tid, cwd, m)
            if res.get("ok"):
                return res
            if res.get("cancelled"):
                # Pengguna menekan hentikan: mencoba model cadangan berikutnya
                # berarti tugas yang sudah dibatalkan tetap makan waktu.
                break
            if res.get("stalled"):
                # The worker wedged, not the model: another model will wedge the
                # same way, so stop and let the caller try a different worker.
                break
            # Model yang tidak dikenal gateway akan ditolak lagi di tugas lain,
            # dan mencoba cadangan berikutnya setelah ini cuma menambah waktu
            # tunggu tanpa hasil. Catat lalu berhenti.
            if _model_ditolak((res.get("text") or "") + " " + str(res.get("error") or "")):
                tandai_model_ditolak(m)
                break
        return res

    # ------------------------------------------------------------ fix pass
    def _fix_failure(self, tid: str, prompt: str, test_res: dict, cwd, model: str, results: list[dict]) -> dict:
        """One repair round: show a worker the failing tests and let it fix them."""
        cfg = config.load()
        if not cfg["workflow"].get("fix_on_fail", True):
            return test_res
        rounds = int(cfg["workflow"].get("fix_rounds", 1))
        for rnd in range(1, rounds + 1):
            hub.emit("test", f"Tes belum lulus, perbaikan ronde {rnd}/{rounds}", task=tid, phase="fix")
            detail = (
                f"The test suite for this task is failing.\n\nTask: {prompt}\n\n"
                f"Command: {test_res.get('command')}\nrc={test_res.get('rc')}\n"
                f"Output:\n{(test_res.get('output') or '')[-3000:]}\n\n"
                "Fix the code and/or the tests so the suite passes. Do not delete or weaken tests "
                "to make them pass. Run the tests yourself before finishing."
            )
            used = {r["worker"] for r in results if r.get("ok")}
            # Cheapest first: a repair round is a small fix, not a place to
            # spend a $0.45 Claude request when omp does it for cents.
            order = _pick_cheapest(cfg, 1, exclude=used) or _pick_workers(cfg, 1)
            res = self._worker_prompt(order[0], detail, tid, str(cwd), model)
            results.append(res)
            test_res = project.run_tests(test_res.get("command") or None, task_id=tid)
            if test_res.get("ok"):
                hub.emit("test", f"Tes lulus setelah perbaikan ronde {rnd}", task=tid, ok=True)
                return test_res
        return test_res

    # ------------------------------------------------------------ review fix
    def _fix_review(self, tid: str, prompt: str, review: dict, cwd, model: str,
                    results: list[dict]) -> bool:
        """Hand the reviewer's own issue list back to a worker, once.

        Returns True when the worker actually changed something, so the caller
        only re-reviews when there is something new to look at.
        """
        cfg = config.load()
        rounds = int(cfg["workflow"].get("fix_review_rounds", 1))
        if rounds <= 0:
            return False
        before = project.change_summary(200000)
        used = {r["worker"] for r in results if r.get("ok")}
        order = _pick_cheapest(cfg, 1, exclude=used) or _pick_workers(cfg, 1)
        if not order:
            return False
        hub.emit("review", "Penilaian menemukan masalah, catatan dikirim ke pekerja lain", task=tid, phase="fix")
        detail = (
            f"Task: {prompt}\n\nAn independent review of the work found these issues:\n"
            f"{review.get('text', '')[:2500]}\n\n"
            "Fix exactly these issues in the project files. Change only what the issues "
            "require, keep the tests green, and run the tests yourself before finishing."
        )
        res = self._worker_prompt(order[0], detail, tid, str(cwd), model)
        results.append(res)
        after = project.change_summary(200000)
        return after.strip() != before.strip()

    # ------------------------------------------------------------ discussion
    def _discuss(self, tid: str, prompt: str, results: list[dict], model: str) -> None:
        hub.emit("discuss", "Pekerja saling menilai hasil", task=tid, phase="start")
        digest = "\n\n".join(f"### {r['worker']} ({'ok' if r.get('ok') else 'failed'})\n{(r.get('text') or '')[-1500:]}" for r in results)
        for r in results:
            w = r["worker"]
            wmodel = config.load()["workers"].get(w, {}).get("model") or model
            others = "\n\n".join(f"### {x['worker']}\n{(x.get('text') or '')[-900:]}" for x in results if x["worker"] != w)
            msg = (
                f"Task: {prompt}\n\nYour own result:\n{(r.get('text') or '')[-1200:]}\n\n"
                f"Teammates' results:\n{others}\n\n"
                "In <=120 words: state agreement/disagreement, concrete bugs or gaps in the other work, "
                "and the single most important next fix. Be specific about files."
            )
            out = self.gw.chat(wmodel, [{"role": "user", "content": msg}], timeout=150, max_tokens=600)
            text = out.get("text") if out.get("ok") else f"(no comment: {out.get('error','')[:120]})"
            hub.emit("discuss", f"[{w}] {text[:1200]}", task=tid, worker=w, phase="msg", text=text)
        hub.emit("discuss", "Saling menilai selesai", task=tid, phase="end")

    # ---------------------------------------------------------------- review
    def _review(self, tid: str, prompt: str, results: list[dict], test_res: dict | None, model: str) -> dict:
        hub.emit("review", "Penilaian akhir berjalan", task=tid, phase="start")
        diff = project.change_summary(12000)
        digest = "\n\n".join(f"### {r['worker']}\n{(r.get('text') or '')[-1200:]}" for r in results)
        tinfo = "not run"
        if test_res:
            tinfo = f"{test_res.get('command')} -> rc={test_res.get('rc')} ok={test_res.get('ok')}\n{(test_res.get('output') or '')[-1500:]}"
        msg = (
            f"Original task: {prompt}\n\nWorker reports:\n{digest}\n\nTest result:\n{tinfo}\n\n"
            f"Git diff:\n{diff}\n\n"
            "You are the orchestrator reviewing the work. Answer in this exact shape:\n"
            "VERDICT: PASS|FAIL\nISSUES: bullet list (or 'none')\nNEXT: the single next action"
        )
        out = self.gw.chat(model, [{"role": "user", "content": msg}], timeout=200, max_tokens=900)
        text = (out.get("text") or "") if out.get("ok") else f"(penilaian tidak tersedia: {out.get('error','')[:200]})"
        if not str(text).strip():
            text = "(penilaian tidak tersedia: balasan kosong dari model)"
        text = str(text)
        verdict = "UNKNOWN"
        for line in text.splitlines():
            if line.strip().upper().startswith("VERDICT"):
                verdict = line.split(":", 1)[-1].strip().upper()[:20]
                break
        # Some models echo the template back ("PASS|FAIL") instead of choosing,
        # and others add a word after the verdict. Neither is a real decision, so
        # normalise to PASS / FAIL / UNKNOWN and let the UI say so.
        if "PASS" in verdict and "FAIL" in verdict:
            verdict = "UNKNOWN"
        elif verdict.startswith("PASS"):
            verdict = "PASS"
        elif verdict.startswith("FAIL"):
            verdict = "FAIL"
        elif verdict not in ("UNKNOWN",):
            verdict = "UNKNOWN"
        hub.emit("review", f"penilaian: {verdict}", task=tid, phase="end", verdict=verdict, text=text[:4000])
        return {"verdict": verdict, "text": text}

    # --------------------------------------------------------------- summary
    def _answer(self, prompt: str, results: list[dict], review: dict | None, model: str) -> str:
        """The one paragraph a person actually reads.

        Worker output is a work log, not an answer: it carries progress lines,
        file echoes and tool chatter. This asks the gateway model to read that
        log and answer the user in plain language, and falls back to the most
        human line the workers produced when the gateway cannot answer.
        """
        digest = "\n\n".join(
            f"### {r.get('worker')} ({'ok' if r.get('ok') else 'gagal'})\n{clean_output(r.get('text') or '')[-4000:]}"
            for r in (results or [])
        )
        if not digest.strip():
            return "Tidak ada keluaran dari worker untuk tugas ini."
        msg = (
            f"Permintaan pengguna: {prompt}\n\n"
            f"Catatan kerja tim (mentah):\n{digest}\n\n"
            + (f"Hasil penilaian: {review.get('verdict')}\n" if review else "")
            + "Jawab pengguna langsung, dalam bahasa Indonesia, 1 sampai 4 kalimat pendek. "
            "Kalau pengguna bertanya, jawab pertanyaannya. Kalau pengguna meminta pekerjaan, "
            "sebutkan apa yang sudah dikerjakan dan di file mana. "
            "Jangan menyebut nama tool, nama worker, path panjang, atau langkah internal. "
            "Jangan pakai tanda pisah panjang. Jangan mengarang. "
            "Tulis seperti orang, bukan seperti asisten: tanpa pembukaan basa-basi, "
            "tanpa pujian ke pertanyaannya, dan tanpa kata pemasaran seperti "
            "'tentu', 'hebat', 'solusi lengkap', atau 'mudah dan cepat'. "
            "Kalau jawaban ini memakai informasi dari halaman web, tutup dengan satu baris "
            "per sumber, persis format ini: SUMBER: nama sumber | https://tautan-persis. "
            "Kalau tidak ada, jangan menulis baris SUMBER sama sekali."
        )
        out = self.gw.chat(model, [{"role": "user", "content": msg}], timeout=180, max_tokens=700)
        text = clean_output(out.get("text") or "") if out.get("ok") else ""
        if not any(r.get("ok") for r in (results or [])):
            # Nothing succeeded: an answer would be a guess built on failed runs.
            reason = ""
            for r in reversed(results or []):
                cleaned = clean_output(r.get("text") or "") or (r.get("error") or "")
                if cleaned:
                    reason = " ".join(cleaned.split())[:300]
                    break
            base = "Belum ada pekerja yang berhasil menyelesaikan tugas ini."
            return (base + (" Percobaan terakhir: " + reason if reason else ""))[:4000]
        if not text:
            text = best_answer_text(results)
        if not text:
            text = "Tugas selesai, tetapi tidak ada ringkasan yang bisa dibaca."
        return text[:4000]

    def _summarize(self, prompt: str, results: list[dict], test_res: dict | None, review: dict | None, changed: str) -> str:
        parts = [f"task: {prompt[:160]}"]
        parts.append("workers: " + ", ".join(f"{r['worker']}({'ok' if r.get('ok') else 'fail'})" for r in results))
        if test_res:
            parts.append(f"tests: {'skipped' if test_res.get('skipped') else ('PASS' if test_res.get('ok') else 'FAIL')}")
        if review:
            parts.append(f"review: {review.get('verdict')}")
        files = [ln.split("---")[1].strip() for ln in (changed or "").splitlines() if ln.startswith("--- new file:")]
        if files:
            parts.append(f"new files: {', '.join(files[:6])}")
        return " · ".join(parts)
