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
from typing import Any, Iterable

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
    # Pemilik dan folder kerja tugas. Tanpa keduanya di sini, tugas yang sudah
    # selesai kehilangan pemiliknya saat server menyimpan ulang daftar tugas,
    # dan pemisahan antar pengguna hilang begitu server dimulai ulang.
    "owner", "workspace",
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


def _teks_dari_stream_json(baris: str) -> str | None:
    """Satu baris stream-json Claude Code jadi satu baris yang bisa dibaca.

    Mengembalikan None kalau barisnya bukan stream-json, atau kalau isinya tidak
    ada gunanya untuk manusia (hasil alat yang panjang, penanda sesi). String
    kosong berarti "ini stream-json, tapi tidak ada yang perlu ditampilkan".

    Alasan: adaptor claude memakai --output-format stream-json supaya keluarannya
    mengalir (lihat ClaudeAdapter.command). Tanpa penerjemah ini, log pekerja dan
    panel aktivitas penuh JSON mentah satu baris panjang, dan jawaban akhir ikut
    membawa JSON itu ke dalam chat.
    """
    if not baris.lstrip().startswith("{"):
        return None
    try:
        d = json.loads(baris)
    except Exception:
        return None
    if not isinstance(d, dict) or "type" not in d:
        return None
    tipe = str(d.get("type"))
    if tipe == "assistant":
        potong: list[str] = []
        for b in (d.get("message") or {}).get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text"):
                potong.append(str(b["text"]).strip())
            elif b.get("type") == "tool_use":
                potong.append(f"jalankan alat {b.get('name', '')}".strip())
        return " ".join(potong)
    if tipe == "result":
        return str(d.get("result") or "").strip()
    if tipe == "tool_progress":
        return f"sedang berjalan: {d.get('tool_name', '')}".strip()
    if tipe in ("system", "user"):
        # Penanda sesi dan hasil alat: panjang, tidak informatif untuk dibaca.
        return ""
    return ""


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
        terjemah = _teks_dari_stream_json(line)
        if terjemah is not None:
            if not terjemah.strip():
                continue
            line = terjemah
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


# =============================================================== klaim berkas
# Dua lapis penjaga untuk pekerja yang dilepas paralel.
#
# Lapis 1, sebelum dispatch: tiap tugas menyebut berkas yang akan disentuhnya,
# lalu klaim semua tugas dibandingkan. Yang klaimnya beririsan tidak dilepas
# bareng, tetapi dikerjakan gantian di atas folder kerja yang bersih.
#
# Lapis 2, sesudah eksekusi: berkas yang BENAR-BENAR berubah (dari sidik jari
# sebelum dan sesudah) dibandingkan dengan klaim tadi. Kalau dua pekerja
# menulis berkas yang sama padahal klaimnya berbeda, hasil paralel itu tidak
# dipercaya: berkasnya dikembalikan ke isi sebelum tugas dan tugas yang bentrok
# dijalankan ulang gantian. Ini jaring pengaman untuk klaim yang salah tebak,
# dan letaknya SEBELUM commit, jadi repo tidak pernah menyimpan hasil campur.
#
# Yang tidak dijanjikan di sini: CLI pekerja tetap bisa timeout dan pintu
# gateway tetap bisa mati. Keduanya di luar kendali orkestrator, dan keduanya
# sudah punya penanganannya sendiri.

# Dua rupa daftar berkas yang ditulis model:
#   BERKAS: src/a.py, src/b.py
#   - src/a.py
# Keduanya dibaca, karena perencana yang berbeda memilih bentuk yang berbeda.
_BERKAS_RX_BARIS = re.compile(r"^\s*(?:[-*]\s*)?(?:berkas|file)\s*[:=]\s*(.+)$", re.I)
_ITEM_RX = re.compile(r"^\s*[-*]\s+`?([^\s`]+)`?\s*$")
# Penanda jawaban klaim. Pekerja CLI menggemakan brief orkestrator ke stdout,
# jadi jawaban harus bisa dipisahkan dari teks prompt yang ikut tercetak.
_PENANDA_BUKA = "MULAI_BERKAS"
_PENANDA_TUTUP = "AKHIR_BERKAS"
# Jalur yang bentuknya tidak masuk akal (kalimat, bukan berkas) dibuang di sini,
# bukan setelah dipakai membandingkan klaim.
_JALUR_RX = re.compile(r"^[A-Za-z0-9_.@+-]+(?:/[A-Za-z0-9_.@+-]+)*$")
_JALUR_ABAI = {"", ".", "..", "/", "-", "none", "tidak", "n/a"}
# Berkas sah yang memang tidak punya ekstensi. Dipakai oleh pembacaan TEBAKAN
# saja: pada teks bebas, kata tanpa titik hampir selalu kata biasa ("buat",
# "berkas", "fungsi"), dan klaim palsu seperti itu membuat setiap tugas
# beririsan dengan tugas lain.
_NAMA_TANPA_EKSTENSI = {
    "dockerfile", "makefile", "license", "licence", "readme", "procfile",
    "gemfile", "rakefile", "vagrantfile", "justfile", "brewfile", "changelog",
    "notice", "authors", "contributing", "codeowners", "owners", "todo",
}
# Penanda bahwa sebuah nama memang berkas: ada titik di segmen terakhirnya,
# atau disebut sebagai jalur (mengandung garis miring).
_BERKAS_RX = re.compile(r"(\.[A-Za-z0-9_-]{1,10}$)|/")


def _normalisasi_jalur(teks: str) -> str:
    """Bersihkan satu sebutan berkas jadi jalur relatif yang bisa dibandingkan.

    Pekerja menulis jalur dengan gaya berbeda: absolut (`/root/AstroZ/workspace/x.py`),
    berawalan `./`, atau berspasi seperti di kalimat. Semuanya harus jadi satu
    bentuk yang sama, kalau tidak dua klaim atas berkas yang sama terlihat
    berbeda dan Lapis 1 meloloskannya.
    """
    s = (teks or "").strip().strip("`'\"").rstrip(".,;:")
    if not s:
        return ""
    s = s.replace("\\", "/")
    if "://" in s:
        return ""
    if s.startswith("/"):
        # Jalur absolut: yang dipakai adalah bagian sesudah nama folder kerja.
        bagian = [x for x in s.split("/") if x]
        for jangkar in ("workspace", "project", "repo"):
            if jangkar in bagian:
                bagian = bagian[bagian.index(jangkar) + 1 :]
                break
        s = "/".join(bagian)
    # Hanya awalan "./" yang utuh yang dibuang. `lstrip("./")` juga membuang
    # titik dan garis miring di depan, jadi "../lain.py" berubah jadi "lain.py"
    # dan terlihat seperti berkas di dalam folder kerja.
    while s.startswith("./"):
        s = s[2:]
    if s.startswith("../") or s.startswith("/") or s in _JALUR_ABAI or s.startswith(".git/"):
        return ""
    if not _JALUR_RX.match(s):
        return ""
    if len(s) > 160 or s.count("/") > 8:
        return ""
    return s


def _jalur_di_teks(teks: str, maks: int, hanya_berkas: bool = True) -> list[str]:
    """Semua jalur yang bisa dikenali di satu potong teks, urut kemunculannya.

    `hanya_berkas` menyalakan penyaring bentuk berkas (lihat `_BERKAS_RX`).
    Dipakai saat membaca teks bebas seperti deskripsi tugas, di mana kata biasa
    jauh lebih banyak daripada nama berkas. Tanpa penyaring itu, deskripsi
    "Buat berkas sapa.py berisi fungsi sapa" menghasilkan klaim ['Buat',
    'berkas', 'sapa.py', 'berisi', 'fungsi', 'sapa']: enam klaim palsu yang
    membuat tugas itu beririsan dengan hampir semua tugas lain, dan seluruh
    tugas dikerjakan gantian tanpa perlu. Terukur di mesin ini.
    """
    out: list[str] = []
    for kandidat in re.findall(r"[A-Za-z0-9_./@+-]*[A-Za-z0-9_][A-Za-z0-9_./@+-]*", teks or ""):
        if hanya_berkas and not _BERKAS_RX.search(kandidat):
            continue
        jalur = _normalisasi_jalur(kandidat)
        if jalur and hanya_berkas and "/" not in jalur and not _BERKAS_RX.search(jalur) \
                and jalur.lower() not in _NAMA_TANPA_EKSTENSI:
            continue
        if jalur and jalur not in out:
            out.append(jalur)
        if len(out) >= maks:
            break
    return out


def berkas_diklaim(teks: str, maks: int = 12, maks_tebak: int | None = None) -> list[str]:
    """Baca daftar berkas dari jawaban pekerja atau perencana.

    Tiga cara baca, dipakai berurutan:

    * blok di antara penanda `MULAI_BERKAS` dan `AKHIR_BERKAS` adalah daftar
      yang disengaja, dan hanya isinya yang dibaca. Ini yang paling aman:
      pekerja CLI menggemakan seluruh brief ke stdout-nya, dan tanpa penanda ini
      nama berkas yang disebut brief (mis. daftar berkas setelan) terbaca
      sebagai klaim pekerja. Terukur di mesin ini: codex mengklaim tiga berkas
      setelan untuk tugas yang tidak ada hubungannya, dan seluruh tugas jadi
      dianggap beririsan;
    * baris `BERKAS:` dan butir daftar dipakai kalau penandanya tidak ada;
    * kalau tidak ada keduanya, jalur apa pun yang bentuknya memang nama berkas
      dipakai sebagai perkiraan. Cara ini lebih longgar, dan justru itu gunanya:
      klaim yang terlalu luas membuat tugas dikerjakan gantian (aman, cuma lebih
      lambat), sedangkan klaim yang terlalu sempit melepas dua pekerja ke berkas
      yang sama.

    Yang dikembalikan selalu jalur relatif yang sudah dinormalkan, tanpa
    duplikat, urut kemunculan.
    """
    out: list[str] = []
    if not teks:
        return out
    teks = _buang_brief(str(teks))
    blok = _blok_penanda(teks)
    if blok is not None:
        # Di dalam blok penanda, tiap baris yang berisi adalah jalur: pekerja
        # diminta menulis satu jalur per baris, tanpa tanda daftar. Jadi tidak
        # ada teka-teki bentuk di sini.
        for baris in blok.splitlines():
            jalur = _normalisasi_jalur(baris)
            if jalur and jalur not in out:
                out.append(jalur)
            if len(out) >= maks:
                break
        return out
    sumber = teks
    butir: list[str] = []
    for baris in sumber.splitlines():
        m = _BERKAS_RX_BARIS.match(baris)
        if m:
            for potong in re.split(r"[,\n]", m.group(1)):
                butir.append(potong)
            continue
        m2 = _ITEM_RX.match(baris)
        if m2 and _BERKAS_RX.search(m2.group(1)):
            butir.append(m2.group(1))
    for b in butir:
        jalur = _normalisasi_jalur(b)
        if jalur and jalur not in out:
            out.append(jalur)
        if len(out) >= maks:
            break
    if out:
        return out
    # Tidak ada daftar yang disengaja: jalur apa pun yang bentuknya nama berkas
    # dipakai sebagai perkiraan, dan jumlahnya dibatasi lebih ketat. Satu jawaban
    # pekerja yang menyebut belasan jalur sekaligus membuat klaimnya beririsan
    # dengan semua tugas lain, dan seluruh tugas jadi dikerjakan gantian.
    return _jalur_di_teks(sumber, maks if maks_tebak is None else maks_tebak)


def _buang_brief(teks: str) -> str:
    """Potong brief orkestrator yang ikut tergemakan di keluaran pekerja.

    Pekerja CLI mencetak prompt yang diberikan kepadanya, termasuk brief dari
    `_worker_brief`. Brief itu memuat nama berkas dan contoh perintah, dan kalau
    ikut dibaca sebagai jawaban, klaim pekerja berisi berkas yang tidak ada
    hubungannya dengan tugasnya. Yang dipotong hanya bagian brief yang dikenali
    dari penandanya, bukan seluruh teks.
    """
    if "Konteks kerja:" not in teks:
        return teks
    potong: list[str] = []
    dalam_brief = False
    for baris in teks.splitlines():
        if baris.strip().startswith("Konteks kerja:"):
            dalam_brief = True
            continue
        if dalam_brief:
            # Brief berakhir di baris aturan terakhirnya; sesudah itu pertanyaan
            # klaim atau jawaban pekerja sendiri.
            if baris.strip().startswith(("SEBELUM mengerjakan", "Berkas mana saja")):
                dalam_brief = False
                potong.append(baris)
            continue
        potong.append(baris)
    return "\n".join(potong)


def _blok_penanda(teks: str) -> str | None:
    """Isi blok penanda yang TERAKHIR, atau None kalau tidak ada.

    Yang diambil blok terakhir, bukan yang pertama: pekerja CLI mencetak
    pertanyaannya sendiri lebih dulu (termasuk contoh blok `<jalur berkas>` di
    dalam pertanyaan), dan jawaban sebenarnya menyusul di bawahnya. Mengambil
    blok pertama berarti membaca contoh dari pertanyaan, bukan jawabannya.
    """
    atas = teks.rfind(_PENANDA_BUKA)
    if atas < 0:
        return None
    bawah = teks.find(_PENANDA_TUTUP, atas + len(_PENANDA_BUKA))
    if bawah < 0:
        return teks[atas + len(_PENANDA_BUKA):]
    return teks[atas + len(_PENANDA_BUKA):bawah]


def klaim_aman(cfg: dict) -> list[str]:
    """Berkas setelan yang selalu ikut diklaim.

    Bukan karena tugas sering menyentuhnya, tetapi karena dua pekerja yang
    menulis berkas setelan yang sama di saat yang sama merusak seluruh tugas
    berikutnya, bukan cuma satu langkah. Terukur di repo ini: team.yaml berisi
    kunci gateway, dan satu penulisan setengah jalan membuat semua tugas gagal
    dengan pesan yang tidak ada hubungannya dengan pekerjaannya.
    """
    out: list[str] = []
    for b in cfg["workflow"].get("berkas_aman") or []:
        jalur = _normalisasi_jalur(b)
        if jalur:
            out.append(jalur)
    return out


def _norm_klaim(daftar: Iterable[str] | None, maks: int, hanya_berkas: bool = False) -> list[str]:
    """Bersihkan daftar klaim: dinormalkan, dibatasi jumlahnya, tanpa duplikat.

    `hanya_berkas` membuang isi yang bentuknya bukan nama berkas. Dipakai untuk
    daftar yang datang dari perencana: satu isian berbentuk kalimat di daftar itu
    membuat tugas beririsan dengan semua tugas lain.
    """
    out: list[str] = []
    for b in daftar or []:
        if hanya_berkas and not _BERKAS_RX.search(str(b)):
            continue
        jalur = _normalisasi_jalur(b)
        if hanya_berkas and "/" not in jalur and not _BERKAS_RX.search(jalur) \
                and jalur.lower() not in _NAMA_TANPA_EKSTENSI:
            continue
        if jalur and jalur not in out:
            out.append(jalur)
        if len(out) >= maks:
            break
    return out


def _pembagian_klaim(items: list[dict], max_par: int) -> list[list[dict]]:
    """Susun tugas jadi beberapa batch, tiap batch aman dilepas paralel.

    Satu tugas masuk batch pertama yang masih punya ruang dan TIDAK beririsan
    dengan tugas mana pun di batch itu. Kalau tidak ada yang menerimanya, tugas
    itu membuka batch baru. Batch dijalankan satu per satu, jadi tugas yang
    beririsan dengan tugas lain otomatis dikerjakan gantian, sementara tugas
    yang tidak beririsan tetap berbagi batch dan tetap paralel.

    Dua hal yang dijaga di sini: tidak ada dua tugas beririsan di satu batch
    (itu inti Lapis 1), dan jumlah batch tidak dibatasi supaya tugas yang
    saling bertabrakan tetap punya tempat, bukan hilang dari antrean.
    """
    batch: list[list[dict]] = []
    for st in items:
        klaim = set(st.get("klaim") or [])
        masuk = False
        for b in batch:
            if len(b) >= max(1, max_par):
                continue
            if any(klaim & set(x.get("klaim") or []) for x in b):
                continue
            b.append(st)
            masuk = True
            break
        if not masuk:
            batch.append([st])
    return batch


def _label_pekerja(r: dict, i: int = 0) -> str:
    """Nama unik satu laporan pekerja di dalam satu batch.

    Kunci internal `_pekerja` bisa hilang (mis. laporan yang dipulihkan dari
    tasks.json), dan tanpa cadangan itu seluruh batch bisa dianggap satu pekerja
    yang sama sehingga tidak ada tabrakan yang terdeteksi. Posisi dalam batch
    dipakai sebagai cadangan: ia selalu ada dan tetap unik.
    """
    return str(r.get("_pekerja") or r.get("worker") or f"pekerja-{i}")


def _berkas_balik(hasil: list[dict]) -> set[str]:
    """Berkas yang pernah dipulihkan karena tabrakan, di seluruh tugas ini.

    Dipakai dua hal: ringkasan sesudah eksekusi, dan garis dasar laporan
    perubahan berkas. Berkas yang sudah dikembalikan ke kondisi sebelum tugas
    bukan hasil tugas ini, jadi ia tidak boleh ikut dilaporkan atau dinilai
    seolah-olah baru dikerjakan.
    """
    out: set[str] = set()
    for r in hasil or []:
        if isinstance(r, dict):
            out.update(r.get("bentrok") or [])
    return out


def _bersihkan_hasil(t: dict) -> None:
    """Buang kunci internal sebelum tugas disimpan.

    `_prompt` dan `_pekerja` dipakai Lapis 2 untuk menjalankan ulang tugas yang
    bentrok. Keduanya bukan bagian dari laporan yang dibaca UI, dan menyimpannya
    berarti prompt penuh ikut tertulis ke tasks.json untuk setiap tugas.
    """
    for r in t.get("results") or []:
        if isinstance(r, dict):
            r.pop("_prompt", None)
            r.pop("_pekerja", None)
    for st in (t.get("plan") or {}).get("subtasks") or []:
        if isinstance(st, dict):
            st.pop("_pekerja", None)


def _persist_tasks() -> None:
    """Keep task history across restarts (the UI and plugin both read it)."""
    try:
        for t in TASKS.values():
            _bersihkan_hasil(t)
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
            # Tugas dari berkas lama tidak punya pemilik: dibaca sebagai milik
            # admin, sama seperti sesi. Tanpa ini, seluruh riwayat tugas yang
            # sudah ada hilang dari pemiliknya setelah pemisahan ini.
            t.setdefault("owner", "admin")
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


def list_tasks(limit: int = 50, owner: str | None = None) -> list[dict]:
    """Daftar tugas. `owner` menyaring pemiliknya; None berarti semua (admin).

    Tugas tanpa pemilik (berkas lama) dibaca sebagai milik admin, sama seperti
    sesi: pekerjaan yang sudah ada tidak boleh hilang dari pemiliknya.
    """
    items = list(TASKS.values())
    if owner is not None:
        owner = (owner or "").strip().lower()
        items = [t for t in items if (t.get("owner") or "admin") == owner]
    items.sort(key=lambda t: t["created"], reverse=True)
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
            "owner": t.get("owner") or "admin",
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


def pintu_gateway_hidup(cfg: dict | None = None) -> dict:
    """Periksa pintu yang dipakai pekerja, bukan hanya gateway di belakangnya.

    Pekerja menembak :20129 (penyaring SSE), sementara UI dan Hermes memakai
    :20128 langsung. Dua port itu bisa berbeda nasib, dan itulah insiden yang
    memakan waktu: penyaring di :20129 mati, :20128 tetap sehat, UI melaporkan
    gateway "online", lalu setiap pekerja menggantung menunggu port yang tidak
    ada yang mendengarkan. Ketiga pekerja dilaporkan "macet" padahal ketiganya
    hanya menunggu jawaban yang tidak akan datang.

    Jadi periksa kedua-duanya, dan sebut port mana yang mati supaya pesannya
    bisa langsung ditindaklanjuti.
    """
    cfg = cfg or config.load()
    gw = cfg["gateway"]
    hasil: dict = {"ok": True, "mati": [], "pesan": ""}
    tujuan = [
        ("upstream", (gw.get("upstream_base_url") or gw.get("base_url") or "").rstrip("/"), "/api/health"),
        ("pekerja", (gw.get("api_base") or "").rstrip("/"), "/models"),
    ]
    for nama, dasar, jalur in tujuan:
        if not dasar:
            continue
        host_port = dasar.split("://", 1)[-1].split("/")[0]
        host, _, port = host_port.partition(":")
        try:
            import socket as _socket

            with _socket.create_connection((host or "127.0.0.1", int(port or 80)), timeout=3):
                pass
        except OSError as e:
            hasil["ok"] = False
            hasil["mati"].append(f"{nama} {dasar} ({e.__class__.__name__})")
    if not hasil["ok"]:
        hasil["pesan"] = (
            "Pintu gateway tidak menerima sambungan: "
            + "; ".join(hasil["mati"])
            + ". Pekerja akan menunggu tanpa jawaban, jadi tugas tidak dijalankan."
        )
    return hasil


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
    # Aturan pembagian berkas. Tanpa ini, dua pekerja yang dilepas bersamaan
    # sama-sama merasa berhak menyentuh berkas bersama, dan hasil kerjanya saling
    # menimpa. Orkestrator sudah memisahkan tugas yang klaimnya beririsan, jadi
    # aturan ini melengkapinya, bukan menggantikannya.
    #
    # Sengaja TIDAK menyebut nama berkas setelan satu per satu. Pekerja CLI
    # menggemakan seluruh brief ini ke stdout-nya, dan teks itu dibaca lagi oleh
    # pembaca klaim berkas. Terukur: daftar "team.yaml, .env, requirements.txt"
    # di brief membuat codex mengklaim ketiga berkas itu untuk tugas yang tidak
    # ada hubungannya, sehingga semua tugas dianggap beririsan dan seluruh
    # pekerjaan jadi berjalan gantian. Kalimatnya sekarang umum, tanpa jalur.
    baris.append(
        "- Kerjakan hanya berkas yang menjadi bagian tugasmu. Jangan mengubah berkas "
        "setelan atau berkas milik tugas lain, dan jangan merapikan berkas yang tidak "
        "kamu ubah."
    )
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


def _pohon_proses(pid: int) -> list[int]:
    """pid ini dan semua keturunannya.

    Pekerja CLI bukan satu proses: claude dan omp menjalankan mesin Bun/Node
    sebagai anak, codex menjalankan biner di dalam node_modules, dan perintah
    shell yang dijalankan pekerja menambah satu proses lagi.

    Pohon dibangun dengan memindai /proc/*/stat dan mencocokkan PPid, BUKAN
    dengan membaca /proc/<pid>/task/<pid>/children: berkas children itu tidak
    ada di container proot ini (diukur: FileNotFoundError pada semua proses),
    sehingga penelusuran lewat children selalu berhenti di proses induk dan
    anak yang benar-benar bekerja tidak pernah terlihat.
    """
    peta: dict[int, int] = {}
    for x in pathlib.Path("/proc").iterdir():
        if not x.name.isdigit():
            continue
        try:
            st = (x / "stat").read_text()
        except Exception:
            continue
        try:
            tutup = st.rindex(")")
            peta[int(st[: st.index(" ")])] = int(st[tutup + 2 :].split()[1])
        except Exception:
            continue
    keluar: list[int] = []
    tumpuk = [pid]
    while tumpuk:
        p = tumpuk.pop()
        if p in keluar:
            continue
        keluar.append(p)
        tumpuk += [k for k, v in peta.items() if v == p]
    return keluar


def _menunggu_jaringan(pid: int) -> bool:
    """True kalau proses (atau anaknya) memegang satu socket terbuka.

    Dipakai pembatas kemacetan. Versi lama membaca /proc/net/tcp untuk
    mencocokkan inode socket, dan di container proot ini berkas itu SELALU
    PermissionError (diukur: root pun ditolak, begitu juga lewat
    /proc/self/net/tcp dan /proc/<pid>/net/tcp). Akibatnya fungsi ini selalu
    menjawab False, penjaga macet tidak pernah mengenali pekerja yang sedang
    menunggu jawaban model, dan setiap tugas yang lebih lambat dari
    stall_seconds dibunuh sebagai "macet" walau sehat.

    Yang dibaca sekarang: tautan socket: di /proc/<pid>/fd, pada pohon proses.

    Jujur soal batasnya: hitungan socket TIDAK membedakan "menunggu jawaban"
    dari "menunggu koneksi yang tidak akan pernah datang". Diukur pada dua
    kasus, pekerja ke gateway hidup dan ke port mati, keduanya memegang 4-6
    socket dan sama-sama diam. Jadi fungsi ini hanya dipakai sebagai izin
    menunggu SESUATU yang dibatasi waktunya oleh pemanggil (lihat
    _menunggu_jaringan_batas), bukan sebagai bukti pekerja itu sehat.
    """
    for p in _pohon_proses(pid):
        try:
            for f in pathlib.Path(f"/proc/{p}/fd").iterdir():
                try:
                    if os.readlink(f).startswith("socket:["):
                        return True
                except Exception:
                    continue
        except Exception:
            continue
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
        # Berapa lama "ada socket terbuka" boleh dipakai sebagai alasan untuk
        # tetap menunggu. Socket yang terbuka hanya membuktikan pekerja menunggu
        # SESUATU, bukan bahwa sesuatu itu akan menjawab: diukur, pekerja ke
        # gateway mati memegang 4-6 socket yang sama persis dengan pekerja ke
        # gateway hidup, dan sama-sama diam. Tanpa batas ini, satu port gateway
        # yang mati membuat setiap pekerja menunggu sampai timeout penuh
        # (900s x 3 pekerja), dan itulah yang terjadi sebelum perbaikan ini.
        # 600s = dua kali batas menunggu bawaan, cukup untuk model lambat.
        tunggu_maks = int(config.load()["workflow"].get("wait_ceiling_seconds") or 600)
        last_useful = t0
        menunggu_sejak = 0.0
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
                    if _menunggu_jaringan(p.pid) and time.time() - (menunggu_sejak or time.time()) < tunggu_maks:
                        # Ada socket terbuka: pekerja sedang menunggu jawaban
                        # model, bukan macet. Ini yang dulu salah dinilai macet:
                        # opencode dan claude diam saat model berpikir lama.
                        menunggu_sejak = menunggu_sejak or time.time()
                        last_useful = time.time()
                        continue
                    p.kill()
                    timed_out = True
                    stalled = True
                    sebab = (
                        f"macet tanpa kemajuan selama {stall}s"
                        if not menunggu_sejak
                        else f"menunggu tanpa jawaban lebih dari {tunggu_maks}s, pintu gateway diduga mati"
                    )
                    hub.emit("worker", f"[{worker}] {sebab}, dihentikan", task=task_id, worker=worker, ok=False)
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
            "subtasks": [{"title": "Implement request", "detail": prompt, "worker": workers[0] if workers else "claude",
                          "berkas": berkas_diklaim(prompt, 6)}],
            "test_command": project.detect_test_command(),
        }
        if not model or not cfg["gateway"].get("online"):
            return fallback
        sys = (
            "You are Hermes, the orchestrator of a coding team. Classify the task and decompose it.\n"
            "Return ONLY minified JSON with keys: size (small|medium|large), goal (1 sentence), "
            "subtasks (array of {title, detail, worker, berkas} where worker is one of "
            f"{workers} and berkas is the array of file paths that subtask will change), "
            "test_command (shell command or empty string).\n"
            "small = single focused edit, 1 subtask. medium = a few files, 2 subtasks. "
            "large = multi-part feature, 3-4 subtasks that can run in parallel.\n"
            "Two subtasks that run together must never touch the same file: if they would, "
            "either split the work by file or merge them into one subtask. Subtasks that "
            "share a file are executed one after another, which wastes the parallel run.\n"
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

    # -------------------------------------------------------- klaim berkas
    def _klaim_untuk(self, tid: str, st: dict, prompt: str, worker: str, cwd: str, model: str,
                     cfg: dict) -> list[str]:
        """Berkas yang akan disentuh satu tugas, sebelum pekerja dilepas.

        Sumbernya berurutan: berkas yang sudah disebut perencana (di `berkas`),
        lalu tanya langsung ke pekerja tanpa eksekusi nyata. Yang dikembalikan
        HANYA klaim pekerja itu sendiri, karena klaim inilah yang dipakai
        memutuskan tugas mana yang boleh jalan bareng: berkas yang selalu
        diklaim semua orang (lihat `klaim_aman`) sengaja TIDAK dimasukkan di
        sini, kalau tidak setiap pasang tugas beririsan dan tidak ada satu pun
        yang benar-benar paralel.

        Pekerja yang gagal menjawab tidak menghambat tugasnya: klaimnya kosong
        dan Lapis 2 yang menjaga, bukan penjadwalannya.
        """
        maks = int(cfg["workflow"].get("batas_klaim") or 12)
        # Berkas yang disebut di deskripsi tugas dipakai HANYA kalau perencana
        # sudah menuliskannya sebagai daftar `berkas`. Kalau tidak, yang
        # diandalkan adalah jawaban pekerja: deskripsi tugas adalah kalimat biasa,
        # dan membaca nama berkas dari kalimat menghasilkan klaim palsu (lihat
        # _jalur_di_teks). Kalau pekerja tidak bisa ditanya, klaimnya kosong dan
        # Lapis 2 yang menjaga.
        from_plan = _norm_klaim(st.get("berkas"), maks, hanya_berkas=True)
        if from_plan:
            hub.emit("plan", f"Klaim berkas dari rencana ({worker}): " + ", ".join(from_plan[:8]),
                     task=tid, worker=worker, phase="klaim", berkas=from_plan)
            return from_plan
        if not cfg["workflow"].get("klaim_berkas", True):
            return []
        tanya = (
            "Jawab pertanyaan ini saja, jangan mengerjakan tugasnya dulu dan jangan "
            "mengubah berkas apa pun.\n"
            f"Tugas: {(st.get('detail') or st.get('title') or prompt)[:1200]}\n\n"
            "Berkas mana saja yang akan kamu ubah atau buat untuk tugas itu? "
            "Tulis jawabannya HANYA di antara dua baris penanda berikut, satu jalur "
            "relatif per baris, tanpa penjelasan lain:\n"
            f"{_PENANDA_BUKA}\n"
            "<jalur berkas>\n"
            f"{_PENANDA_TUTUP}\n"
            "Kalau tidak ada berkas yang perlu diubah, tulis 'tidak ada' di antara "
            "penanda itu."
        )
        try:
            res = self._worker_prompt(worker, tanya, tid, cwd, model, retries=1)
        except Exception as e:
            res = {"ok": False, "error": str(e), "text": ""}
        if not res.get("ok"):
            hub.emit("worker", f"[{worker}] tidak bisa menjawab pertanyaan berkas, "
                              "klaim dikosongkan (dijaga Lapis 2)", task=tid, worker=worker,
                     phase="klaim", ok=False)
            return []
        klaim = berkas_diklaim(clean_output(res.get("text") or ""), maks, maks_tebak=max(1, maks // 2))
        if klaim:
            hub.emit("worker", f"[{worker}] mengklaim berkas: " + ", ".join(klaim[:8]),
                     task=tid, worker=worker, phase="klaim", berkas=klaim)
        else:
            hub.emit("worker", f"[{worker}] tidak menyebut berkas apa pun, klaim dikosongkan "
                              "(dijaga Lapis 2)", task=tid, worker=worker, phase="klaim", ok=False)
        return klaim

    def _susun_klaim(self, tid: str, items: list[dict], prompt: str, chosen: list[str], d,
                     model: str, cfg: dict) -> list[list[dict]]:
        """Lapis 1: tanyakan berkas tiap tugas, lalu susun batch yang aman.

        Tanyaannya dijalankan PARALEL dan hanya sekali per tugas, jadi tidak ada
        tanya berantai yang menambah waktu tunggu. Hasilnya ditempelkan ke tiap
        tugas sebagai `klaim`, dan tugas yang klaimnya beririsan diletakkan di
        batch yang berbeda supaya dikerjakan gantian, bukan bersamaan.
        """
        for st in items:
            w = st.get("worker") if st.get("worker") in adapters.ADAPTERS else chosen[0]
            st["_pekerja"] = w
            st["klaim"] = []
        if not items:
            return []
        threads: list[threading.Thread] = []
        for st in items:
            w = st["_pekerja"]
            thr = threading.Thread(
                target=lambda s=st, ww=w: s.__setitem__(
                    "klaim", self._klaim_untuk(tid, s, prompt, ww, str(d), model, cfg)
                )
            )
            thr.start()
            threads.append(thr)
        for thr in threads:
            thr.join()
        max_par = int(cfg["workflow"].get("max_parallel", 3) or 3)
        batch = _pembagian_klaim(items, max_par)
        # Klaimnya ditempelkan ke tugas yang benar-benar dikirim ke pekerja.
        # Tanpa ini klaim hanya dipakai orkestrator, dan pekerja tetap merasa
        # bebas menyentuh berkas milik tugas lain.
        for st in items:
            klaim = st.get("klaim") or []
            if klaim:
                st["detail"] = (st.get("detail") or st.get("title") or "") + (
                    "\n\nBerkas yang menjadi bagian tugas ini: " + ", ".join(klaim)
                    + ". Jangan mengubah berkas lain."
                )
        if len(batch) > 1:
            hub.emit("plan", f"Klaim berkas bentrok, {len(batch)} batch dikerjakan berurutan: "
                             + " | ".join(", ".join(x["_pekerja"] for x in b) for b in batch),
                     task=tid, phase="klaim", batch=[[x["_pekerja"] for x in b] for b in batch])
        else:
            hub.emit("plan", "Tidak ada klaim berkas yang bentrok, semua tugas jalan paralel",
                     task=tid, phase="klaim", batch=[[x["_pekerja"] for x in batch[0]]] if batch else [])
        return batch

    def _siapkan_cadangan(self, tid: str, batch: list[dict], d) -> pathlib.Path | None:
        """Salin berkas yang diklaim SEBELUM batch dilepas.

        Urutannya penting: kalau salinan diambil sesudah pekerja selesai, yang
        tersalin adalah isi yang sudah bentrok, dan pemulihan hanya akan
        mengembalikan kerusakannya. Jadi salinan diambil di sini, tepat sebelum
        batch berjalan.

        Yang disalin hanya berkas yang diklaim. Berkas yang sudah ada tapi tidak
        diklaim tidak disalin: isinya bisa dikembalikan lewat git, dan berkas
        yang memang baru (belum ada isi lama) cukup dihapus. Jadi folder
        cadangan tetap dikembalikan walau tidak ada satu pun berkas yang perlu
        disalin, supaya pemulihan lewat git tetap punya tempat berpijak.
        """
        klaim: list[str] = []
        for st in batch:
            klaim += list(st.get("klaim") or [])
        if not klaim:
            tempat = config.RUNTIME / "cadangan" / (tid or "tugas")
            try:
                tempat.mkdir(parents=True, exist_ok=True)
            except Exception:
                return None
            return tempat
        return project.snap_sementara(sorted(set(klaim)), tag=tid)

    def _cek_bentrok(self, tid: str, hasil: list[dict], snap_awal: dict,
                     dasar: set[str], d, cfg: dict, dipakai: set[str], kedalaman: int = 0,
                     model: str = "", berkas_aman: list[str] | None = None,
                     cadangan: pathlib.Path | None = None) -> list[dict]:
        """Lapis 2: bandingkan berkas yang BENAR-BENAR berubah dengan klaimnya.

        Dipanggil tepat sesudah satu batch paralel selesai, jadi kerusakannya
        ketahuan sebelum tes, sebelum penilaian, dan sebelum commit.

        Ada dua macam tabrakan, dan keduanya harus tertangkap:

        * dua pekerja mengubah berkas yang sama padahal keduanya tidak
          mengklaimnya (klaimnya kosong atau salah tebak). Ini yang paling
          berbahaya: tidak ada satu pun yang merasa bertanggung jawab, dan
          hasilnya campuran dua pekerja.
        * sebuah berkas yang diklaim DUA tugas tapi tetap berubah, walau
          penjadwalan seharusnya sudah memisahkan mereka.

        Berkas yang diklaim oleh satu pekerja saja tidak pernah dianggap
        tabrakan, seberapa pun berubahnya: itu memang hasil kerjanya. Aturan ini
        yang membuat Lapis 2 tidak menuduh pekerja yang tidak bersalah.

        Tindakannya: hasil batch itu dibuang (laporan tiap pekerja ditandai
        `bentrok` supaya tes, penilaian, dan jawaban tidak membacanya sebagai
        hasil sah), berkasnya dikembalikan ke isi sebelum batch, lalu tugas yang
        terlibat dijalankan ulang GANTIAN dari kondisi bersih.

        `dipakai` mencegah berkas yang sama ditangani dua kali: setelah
        dipulihkan sekali, hasil kerja gantian berikutnya dianggap sah untuk
        berkas itu. Ini yang membuat pengulangan terbatas, bukan berputar
        selamanya.

        `kedalaman` membatasi pengulangan bersarang: hasil gantian yang masih
        bentrok dipulihkan sekali lagi tanpa penjadwalan baru. Lebih dari itu
        tabrakan dianggap pola yang tidak bisa ditolong Lapis 2, dan itu sinyal
        untuk menyalakan Lapis 3 (kunci berkas di hub.py), bukan untuk mengulang
        terus.

        `cadangan` adalah salinan berkas sebelum batch dilepas (lihat
        `_siapkan_cadangan`). Ini WAJIB ada kalau pemulihan diharapkan berhasil:
        berkas baru belum ada di git mana pun, jadi tanpa salinan itu tidak ada
        isi lama yang bisa dikembalikan.
        """
        if not hasil:
            return hasil
        aman = set(berkas_aman or [])
        sekarang = project.snap_berkas()
        beda = project.beda_snap(snap_awal, sekarang)
        if beda.get("terpotong"):
            hub.emit("system", "Pemindaian folder kerja terpotong batas berkas, "
                               "deteksi tabrakan hanya mencakup berkas yang terpindai",
                     task=tid, phase="klaim", ok=False)
        # Berkas yang berubah di luar garis dasar tugas ini, beserta siapa saja
        # di batch ini yang mengklaimnya.
        berubah: dict[str, list[int]] = {}
        for rel in [*beda.get("diubah", []), *beda.get("dibuat", []), *beda.get("dihapus", [])]:
            if rel in dasar:
                # Berkas yang sudah ada sebelum tugas mulai bukan hasil tugas ini.
                continue
            berubah[rel] = [i for i, r in enumerate(hasil) if rel in set(r.get("klaim") or [])]
        # Pekerja yang klaimnya kosong (tidak bisa menjawab, atau menjawab tanpa
        # satu pun jalur) dianggap bisa menyentuh berkas apa saja. Tanpa asumsi
        # ini, pekerja tanpa klaim yang menulis ke berkas milik pekerja lain
        # justru lolos: berkas itu terlihat diklaim satu orang, padahal ada dua
        # yang menulis.
        kosong = [i for i, r in enumerate(hasil) if not (r.get("klaim") or [])]
        # Aturan penuduhan, sengaja sempit supaya tidak ada pekerja yang diulang
        # tanpa sebab. Sebuah berkas dianggap bentrok hanya kalau lebih dari satu
        # pekerja di batch ini mungkin menulisnya:
        #   - dua klaim atau lebih atas berkas yang berubah: penjadwalan Lapis 1
        #     tidak jalan, atau klaimnya berubah di tengah jalan;
        #   - satu klaim ditambah satu pekerja tanpa klaim: tidak ada cara tahu
        #     siapa yang menulis, jadi keduanya dijalankan ulang;
        #   - nol klaim tapi ada lebih dari satu pekerja: sama saja, tidak bisa
        #     dipastikan siapa penulisnya.
        # Berkas yang jelas milik satu pekerja tidak pernah dianggap tabrakan,
        # seberapa pun berubahnya: itu memang hasil kerjanya.
        bentrok: set[str] = set()
        for rel, pengklaim in berubah.items():
            if rel in dipakai:
                continue
            if rel in aman:
                # Berkas setelan (team.yaml, .env, requirements.txt): semua
                # pekerja dilarang menjadikannya hasil kerja, dan berkas ini
                # sering ditulis proses lain yang bukan pekerja. Jadi ia tidak
                # pernah dipakai untuk menuduh, tetapi perubahannya tetap
                # dilaporkan supaya tidak hilang begitu saja.
                hub.emit("system", f"Berkas setelan berubah saat pekerja paralel berjalan: {rel}. "
                                   "Bukan hasil pekerja, jadi tidak ada yang dijalankan ulang. "
                                   "Periksa kalau perubahannya tidak kamu duga.",
                         task=tid, phase="klaim", ok=False, berkas=[rel])
                continue
            mungkin = sorted(set(pengklaim) | set(kosong))
            if len(pengklaim) >= 2 or (len(pengklaim) >= 1 and len(kosong) >= 1) \
                    or (not pengklaim and len(hasil) > 1):
                bentrok.add(rel)
                hub.emit("system", f"Berkas {rel} berubah dan lebih dari satu pekerja mungkin "
                                   f"menulisnya ({len(mungkin)} pekerja di batch ini tanpa "
                                   "pembagian yang jelas)", task=tid, phase="klaim", ok=False,
                         berkas=[rel])
        if not bentrok:
            return hasil
        pekerja_bentrok: list[str] = []
        for rel in sorted(bentrok):
            kandidat = list(berubah.get(rel) or [])
            # Pekerja tanpa klaim ikut diulang: berkasnya berubah dan tidak ada
            # cara memastikan bukan dia penulisnya. Ini harga dari klaim yang
            # kosong, dan justru alasan klaim di Lapis 1 penting.
            kandidat += [i for i in kosong if i not in kandidat]
            for i in kandidat:
                label = _label_pekerja(hasil[i], i)
                if label not in pekerja_bentrok:
                    pekerja_bentrok.append(label)
        pekerja_bentrok = sorted(pekerja_bentrok)
        hub.emit("system", "Tabrakan berkas terdeteksi sesudah paralel: " + ", ".join(sorted(bentrok)[:8]),
                 task=tid, phase="klaim", ok=False, berkas=sorted(bentrok), pekerja=pekerja_bentrok)
        dipakai.update(bentrok)
        # Salinannya sudah diambil SEBELUM batch dilepas (_siapkan_cadangan).
        # Mengambilnya di sini akan menyalin isi yang sudah rusak, dan pemulihan
        # hanya akan mengembalikan kerusakannya.
        if cadangan is None:
            hub.emit("system", "Tidak ada salinan sebelum batch, berkas bentrok tidak bisa "
                               "dikembalikan. Ini kegagalan penjagaan, bukan kegagalan pekerja.",
                     task=tid, phase="klaim", ok=False)
        pulih = project.pulihkan_berkas(sorted(bentrok), cadangan, snap_awal) if cadangan else \
            {"kembali": [], "dihapus": [], "gagal": sorted(bentrok)}
        hub.emit("system", f"Hasil paralel dibuang dan berkas bentrok dikembalikan ke kondisi "
                           f"sebelum batch ({len(pulih['kembali'])} dipulihkan, "
                           f"{len(pulih['dihapus'])} dihapus, {len(pulih['gagal'])} gagal)",
                 task=tid, phase="klaim", ok=not pulih["gagal"], rincian=pulih)
        # Hasil batch yang bentrok dibuang: laporan pekerja bisa berisi kerja
        # yang sudah dipulihkan, dan penilai yang membacanya akan menilai berkas
        # yang tidak ada lagi.
        for i, r in enumerate(hasil):
            if _label_pekerja(r, i) in pekerja_bentrok:
                r["bentrok"] = sorted(bentrok)
                r["ok"] = False
                r["text"] = (f"Hasil dibuang: berkas {', '.join(sorted(bentrok)[:6])} disentuh "
                             "lebih dari satu pekerja paralel, berkas dikembalikan dan tugas "
                             "dijalankan ulang gantian.")
        # Hasil batch berikutnya dijalankan di atas folder yang sudah bersih,
        # jadi sidik jarinya disegarkan. Tanpa ini, berkas yang baru saja
        # dipulihkan masih terlihat berubah bagi batch berikutnya, dan pekerja
        # yang tidak bersalah ikut dituduh bentrok.
        sesudah_pulih = project.snap_berkas()
        if kedalaman >= 1:
            # Pengulangan bersarang sudah dipakai sekali. Kalau hasil gantian pun
            # masih bentrok, mengulang lagi hanya menambah waktu tanpa bukti
            # bahwa kali ini akan berbeda. Yang dilakukan sekarang: berkasnya
            # tetap dikembalikan (sudah di atas, jadi folder kerja bersih), dan
            # hasil yang gagal dibiarkan gagal dengan catatan yang jelas.
            # Tabrakan yang tetap terjadi sesudah dikerjakan gantian adalah
            # sinyal untuk menyalakan Lapis 3 (kunci berkas di hub.py), bukan
            # untuk menambah putaran.
            hub.emit("system", "Hasil gantian masih bentrok, pengulangan dihentikan. "
                               "Folder kerja sudah dikembalikan; pola seperti ini yang perlu "
                               "Lapis 3 (kunci berkas di hub.py).",
                     task=tid, phase="klaim", ok=False)
            return hasil
        ulang: list[dict] = []
        for i, r in enumerate(hasil):
            if _label_pekerja(r, i) not in pekerja_bentrok:
                continue
            label = _label_pekerja(r, i)
            prompt_ulang = r.get("_prompt") or ""
            if not prompt_ulang:
                # Tanpa prompt aslinya, menjalankan ulang berarti menebak tugas,
                # dan tebakan yang salah lebih buruk daripada laporan yang jujur
                # bahwa hasilnya dibuang.
                hub.emit("worker", f"[{label}] tidak dijalankan ulang: prompt tugasnya tidak "
                                   "tercatat, hasilnya dibuang dan berkasnya sudah bersih",
                         task=tid, worker=label, phase="ulang", ok=False)
                continue
            hub.emit("worker", f"[{label}] dijalankan ulang gantian dari kondisi bersih",
                     task=tid, worker=label, phase="ulang")
            baru = self._worker_prompt(label, prompt_ulang, tid, str(d), model)
            baru["klaim"] = list(r.get("klaim") or [])
            baru["_pekerja"] = label
            baru["_prompt"] = prompt_ulang
            ulang.append(baru)
        ulang = self._cek_bentrok(tid, ulang, sesudah_pulih, dasar, d, cfg, dipakai,
                                  kedalaman + 1, model, berkas_aman, cadangan)
        return [r for i, r in enumerate(hasil) if _label_pekerja(r, i) not in pekerja_bentrok] + ulang

    # -------------------------------------------------------------- workflow
    def submit(self, prompt: str, workflow: str = "auto", workers: list[str] | None = None,
               model: str | None = None, session_id: str | None = None,
               owner: str = "admin") -> str:
        cfg = config.load()
        tid = uuid.uuid4().hex[:12]
        # Pertanyaan ringan dijawab langsung, jadi tidak perlu folder kerja baru.
        # Tanpa ini setiap "halo" meninggalkan satu folder yang menumpuk.
        ringan = workflow == "auto" and cepatkah(prompt)
        # Folder kerja milik pemilik tugas, bukan folder global. Dihitung di sini
        # (thread pemanggil) dan disimpan di tugas, supaya thread pekerja tidak
        # perlu tahu apa pun tentang akun.
        import users as _users
        ruang = "" if ringan else str(_users.ruang_kerja(owner))
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
            "owner": (owner or "admin").strip().lower(),
            "size": "chat" if ringan else "",
            "workspace": ruang,
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
            # Seluruh tugas ini bekerja di folder pemiliknya. Dikunci di awal
            # thread, jadi setiap pemanggilan project.* di bawah ikut memakai
            # folder itu, termasuk pekerja paralel dan pemeriksaan berkas.
            if t.get("workspace"):
                project.set_workspace(t["workspace"])

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
            # Garis dasar berkas yang sudah ada sebelum tugas ini mulai. Dipakai
            # supaya sisa berkas dari tugas lama tidak ikut dilaporkan sebagai
            # hasil tugas ini (lihat project.change_summary).
            dasar = project.berkas_baru()
            # Sidik jari folder kerja SEBELUM pekerja mana pun menyentuhnya.
            # Dipakai dua hal: garis dasar laporan perubahan berkas, dan
            # pembanding Lapis 2 (berkas mana yang benar-benar berubah sesudah
            # pekerja paralel selesai). Diambil di sini, bukan di tengah tahap
            # eksekusi, supaya mencakup apa pun yang terjadi selama tugas.
            snap_awal = project.snap_berkas()
            if snap_awal.get("terpotong"):
                hub.emit("system", f"Folder kerja lebih dari {project.BATAS_BERKAS} berkas, "
                                   "sidik jari hanya mencakup sebagian (deteksi tabrakan "
                                   "tetap jalan untuk berkas yang terpindai)",
                         task=tid, phase="start", ok=False)

            # Pintu gateway diperiksa SEBELUM pekerja dijalankan. Tanpa ini,
            # port pekerja yang mati (penyaring SSE di :20129) tidak terlihat
            # oleh pemeriksaan health mana pun, dan setiap pekerja menunggu
            # jawaban yang tidak akan datang sampai batas waktunya habis:
            # 900s dikali tiga pekerja untuk satu tugas yang sebenarnya tidak
            # bisa dikerjakan sejak detik pertama.
            pintu = pintu_gateway_hidup(cfg)
            if not pintu["ok"]:
                t["status"] = "error"
                t["answer"] = pintu["pesan"]
                t["summary"] = "pintu gateway mati: " + "; ".join(pintu["mati"])
                hub.emit("gateway", pintu["pesan"], task=tid, phase="error", ok=False)
                hub.emit("task", "Tugas tidak dijalankan: " + pintu["pesan"], task=tid, phase="error", ok=False)
                return

            # Tugas yang dihentikan sebelum sempat mulai tidak boleh lanjut.
            if dihentikan(tid):
                hub.emit("task", "Tugas dihentikan sebelum mulai", task=tid, phase="cancel", ok=False)
                return

            # --- tanpa pekerja: jawab langsung lewat model -----------------
            # Terjadi kalau tidak ada satu pun pekerja CLI terpasang, misalnya di
            # aplikasi Android yang memang tidak menyertakannya. Menjalankan
            # tahap berikutnya tanpa pekerja hanya menghasilkan tugas yang gagal
            # setelah menunggu batas waktu, jadi jawab langsung dengan model.
            if not _pick_workers(cfg, 1):
                t["size"] = t.get("size") or "chat"
                t["workers"] = []
                hub.emit("plan", "Tidak ada pekerja CLI, dijawab langsung oleh model",
                         task=tid, size="chat", phase="end")
                gw = Gateway(cfg)
                pesan = (
                    "Kamu AstroZ, asisten kerja yang berjalan di dalam aplikasi Android. "
                    "Di perangkat ini tidak ada pekerja CLI (claude, codex, opencode, omp), "
                    "jadi kamu menjawab sendiri: tidak ada yang menjalankan perintah atau "
                    "menulis berkas. Jawab dalam bahasa Indonesia, ringkas, langsung ke "
                    "intinya. Kalau permintaannya butuh menjalankan perintah atau mengubah "
                    "berkas di perangkat, katakan dengan jelas bahwa hal itu belum "
                    "didukung di versi Android ini, lalu berikan jawaban atau langkah yang "
                    "masih bisa kamu berikan sekarang."
                )
                jawab = gw.chat(model, [
                    {"role": "system", "content": pesan},
                    {"role": "user", "content": prompt},
                ])
                teks = (jawab.get("text") or "").strip()
                if not teks:
                    t["status"] = "error"
                    t["answer"] = jawab.get("error") or "model tidak menjawab"
                    hub.emit("task", "Model tidak menjawab", task=tid, phase="error", ok=False)
                    return
                t["answer"] = teks
                t["status"] = "done"
                t["finished"] = time.time()
                t["results"] = []
                hub.emit("task", "Jawaban dikirim", task=tid, phase="done", ok=True, size="chat")
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
            # Mode "Besar" dulu cuma dikatakan paralel. Sekarang paralelnya
            # dijaga: tiap tugas mengklaim berkasnya lebih dulu (Lapis 1), dan
            # yang klaimnya beririsan dikerjakan gantian. Mode lain tidak
            # disentuh.
            klaim_on = bool(cfg["workflow"].get("klaim_berkas", True)) and size == "large" \
                and len(subtasks) > 1 and not dihentikan(tid)
            max_par = int(cfg["workflow"].get("max_parallel", 3))
            if size == "small":
                max_par = 1

            # --- execute --------------------------------------------------
            results: list[dict] = []
            dipakai_bentrok: set[str] = set()
            if size == "small" or len(subtasks) <= 1:
                st = subtasks[0] if subtasks else {"title": prompt[:80], "detail": prompt, "worker": chosen[0]}
                w = st.get("worker") if st.get("worker") in adapters.ADAPTERS else chosen[0]
                t["workers"] = [w]
                hub.emit("worker", f"Diberikan ke {w}", task=tid, worker=w, phase="assign")
                results.append(self._worker_prompt(w, st.get("detail") or st.get("title") or prompt, tid, str(d), model))
            else:
                # Tugas besar dikerjakan paralel lalu dibahas bersama. Kalau
                # perencana menaruh semua subtugas di pekerja yang sama (biasanya
                # yang termurah), sebar bergiliran: tahap pembahasan hanya
                # berguna kalau yang mengerjakan memang CLI yang berbeda.
                if size == "large" and len({(s.get("worker") or chosen[0]) for s in subtasks}) == 1:
                    for i, s in enumerate(subtasks):
                        s["worker"] = chosen[i % len(chosen)]
                if klaim_on:
                    # Lapis 1: tiap tugas mengklaim berkasnya lebih dulu, dan
                    # hasilnya disusun jadi batch. Satu batch = tugas yang
                    # klaimnya tidak beririsan, jadi aman dilepas bareng. Batch
                    # dijalankan berurutan, jadi tugas yang beririsan otomatis
                    # dikerjakan gantian.
                    groups = self._susun_klaim(tid, subtasks, prompt, chosen, d, model, cfg)
                else:
                    hub.emit("plan", f"ukuran={size} · {len(subtasks)} langkah · "
                                     f"paralel maksimal {max_par}", task=tid, phase="end", size=size)
                    groups = [subtasks[i : i + max_par] for i in range(0, len(subtasks), max_par)]
                for gi, group in enumerate(groups):
                    if dihentikan(tid):
                        break
                    threads = []
                    box: list[dict] = []
                    hub.emit("worker", f"Batch {gi + 1}/{len(groups)} dikerjakan: "
                                       + ", ".join(_label_pekerja(s, i) for i, s in enumerate(group)),
                             task=tid, phase="assign")
                    # Salinan berkas yang diklaim diambil SEBELUM pekerja
                    # dilepas, supaya isi lama benar-benar tersimpan.
                    cadangan = self._siapkan_cadangan(tid, group, d) if klaim_on else None
                    for st in group:
                        w = st.get("_pekerja") or (st.get("worker") if st.get("worker") in adapters.ADAPTERS else chosen[0])
                        if w not in t["workers"]:
                            t["workers"].append(w)
                        thr = threading.Thread(
                            target=lambda s=st, ww=w: box.append(self._worker_prompt(ww, s.get("detail") or s.get("title"), tid, str(d), model))
                        )
                        thr.start()
                        threads.append(thr)
                    for thr in threads:
                        thr.join()
                    # Lapis 2: sebelum hasil paralel dipakai untuk tes dan
                    # penilaian, berkas yang benar-benar berubah dibandingkan
                    # dengan klaim. Yang bentrok dikembalikan dan dikerjakan
                    # ulang gantian di sini juga, bukan sesudah commit.
                    if klaim_on and len(group) > 1:
                        box = self._cek_bentrok(tid, box, snap_awal, dasar, d, cfg,
                                                dipakai_bentrok, 0, model, klaim_aman(cfg), cadangan)
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

            # --- hasil paralel, diringkas untuk panel proses ----------------
            # Terlihat juga saat tidak ada tabrakan: tanpa ini, klaim berkas
            # hanya terlihat ketika ada masalah, dan pengguna tidak bisa tahu
            # apakah penjagaannya bekerja atau tidak pernah jalan.
            if klaim_on:
                balik = sorted(_berkas_balik(results))
                hub.emit("plan", f"Paralel selesai, {len(balik)} berkas dikembalikan ke kondisi bersih "
                                 f"sesudah tabrakan", task=tid, phase="klaim", berkas=balik[:20],
                         ulang=len(balik))
            else:
                hub.emit("plan", "Tidak ada klaim berkas yang bentrok, hasil paralel dipakai apa adanya",
                         task=tid, phase="klaim", berkas=[], ulang=0)

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
                review = self._review(tid, prompt, results, test_res, model, abaikan=dasar)
                t["review"] = review
                # A review that finds real issues is a work item, not an end
                # state either, hand the reviewer's own issue list back once
                # and re-review. (Green tests do not mean the task is met: a
                # worker can pass its own test while ignoring the requirement.)
                if size != "small" and (review.get("verdict") or "").upper().startswith("FAIL"):
                    fixed = self._fix_review(tid, prompt, review, d, model, results)
                    if fixed:
                        review = self._review(tid, prompt, results, t.get("test"), model, abaikan=dasar)
                        t["review"] = review

            after = project.git_status()
            # Garis dasar diambil SEBELUM pekerja mulai (lihat `dasar` di atas):
            # hanya berkas yang benar-benar dibuat tugas ini yang dilaporkan.
            changed = project.change_summary(2000, abaikan=dasar)
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
                t["commit"] = self._auto_commit(tid, prompt, after.get("status") or "", abaikan=dasar)
            t["status"] = "done"
            hub.emit("task", f"Selesai: {t['summary'][:200]}", task=tid, phase="done", summary=t["summary"], test_ok=(test_res or {}).get("ok"))
        except Exception as e:
            t["status"] = "error"
            t["summary"] = f"error: {e}"
            t["answer"] = f"Gagal menyelesaikan tugas: {e}"
            hub.emit("task", f"Gagal: {e}", task=tid, phase="error", ok=False, answer=t["answer"])
        finally:
            t["finished"] = time.time()
            # Thread pekerja dipakai ulang oleh tugas berikutnya. Folder kerja
            # yang tertinggal di sini akan membuat tugas pengguna lain bekerja di
            # folder yang salah, jadi selalu dikembalikan.
            project.set_workspace(None)
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

    def _auto_commit(self, tid: str, prompt: str, porcelain: str, abaikan: set[str] | None = None) -> dict:
        """Commit a green task's changes, with the task text as the subject.

        `abaikan` adalah berkas yang sudah ada sebelum tugas mulai. Commit
        memakai `git add -A`, jadi tanpa penyaringan ini berkas asing dari tugas
        lama ikut masuk ke dalam commit tugas yang lolos verifikasi: riwayatnya
        bersih terlihat padahal isinya kerja yang tidak pernah diperiksa.
        """
        if not (porcelain or "").strip():
            return {"ok": True, "skipped": "no changes"}
        subject = " ".join(prompt.strip().split())
        if len(subject) > 68:
            subject = subject[:65].rstrip() + "..."
        message = f"{subject}\n\ntask: {tid}"
        res = project.git_commit_all(message, abaikan=abaikan)
        out = res.get("out") or ""
        ok = res.get("rc") == 0 or "nothing to commit" in out
        hub.emit("git", f"Commit otomatis {'tersimpan' if ok else 'GAGAL'}: {subject[:80]}",
                 task=tid, ok=ok, out=out[:300])
        return {"ok": ok, "message": message, **res}

    def _worker_prompt(self, worker: str, prompt: str, tid: str, cwd: str, model: str,
                       retries: int = 3) -> dict:
        """Run one subtask on one worker, walking the model fallback chain.

        The chain matters more than the retry: the same prompt on the same
        worker succeeds immediately when routed to a model whose upstream is not
        saturated, so a failure here is usually routing, not capability.

        `retries` diteruskan ke run_worker. Pertanyaan klaim berkas (Lapis 1)
        memakainya untuk memotong percobaan ulang: pertanyaan itu hanya
        melengkapi penjagaan, bukan pekerjaannya sendiri, dan menunggu tiga kali
        batas waktu hanya menunda tugas yang sebenarnya bisa segera dimulai.
        """
        cfg = config.load()
        wmodel = cfg["workers"].get(worker, {}).get("model") or model
        chain = model_chain(cfg, wmodel)
        res: dict = {}
        for i, m in enumerate(chain):
            if i:
                hub.emit("worker", f"[{worker}] coba ulang dengan model cadangan {m}", task=tid, worker=worker, phase="fallback", model=m)
            res = run_worker(worker, prompt, tid, cwd, m, retries=retries)
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
        # Jejak asal-usul laporan ini. Dipakai Lapis 2: hasil yang bentrok harus
        # bisa dibuang per pekerja, dan tugas yang perlu diulang butuh prompt
        # aslinya, bukan potongan laporan pekerja yang sudah gagal.
        if isinstance(res, dict):
            res["_pekerja"] = worker
            res["_prompt"] = prompt
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
    def _review(self, tid: str, prompt: str, results: list[dict], test_res: dict | None, model: str,
                abaikan: set[str] | None = None) -> dict:
        hub.emit("review", "Penilaian akhir berjalan", task=tid, phase="start")
        diff = project.change_summary(12000, abaikan=abaikan)
        digest = "\n\n".join(f"### {r['worker']}\n{(r.get('text') or '')[-1200:]}" for r in results)
        tinfo = "not run"
        if test_res:
            tinfo = f"{test_res.get('command')} -> rc={test_res.get('rc')} ok={test_res.get('ok')}\n{(test_res.get('output') or '')[-1500:]}"
        msg = (
            f"Original task: {prompt}\n\nWorker reports:\n{digest}\n\nTest result:\n{tinfo}\n\n"
            f"Changes made by this task:\n{diff or '(no file changed by this task)'}\n\n"
            "You are the orchestrator reviewing the work. Answer in this exact shape:\n"
            "VERDICT: PASS|FAIL\nISSUES: bullet list (or 'none')\nNEXT: the single next action\n\n"
            "How to judge:\n"
            "- A new file shows up as 'new file: <name>' with its contents, NOT as a git diff. "
            "A task whose deliverable is a new file is therefore normal and complete when that "
            "file is listed with the right contents. Do not fail it for having no diff.\n"
            "- Judge only the changes listed above. Anything else in the working folder is "
            "leftover from earlier work and is not part of this task.\n"
            "- A passing test run counts as evidence, but it does not replace the requirement: "
            "check the deliverable actually matches what was asked.\n"
            "- If the requirement IS met, answer PASS. Do not invent work to justify a FAIL."
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
