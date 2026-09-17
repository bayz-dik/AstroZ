"""Event hub: one append-only JSONL feed + in-process fanout to SSE clients.

Everything that happens (hermes activity, worker output, discussion, tests,
gateway sync, git) is one event dict. The web UI and the Hermes plugin both
speak this format, so a single tail serves the whole dashboard.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import threading
import time
from collections import deque
from typing import Any, Iterable

import config

_lock = threading.Lock()
_subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None
_recent: deque[dict] = deque(maxlen=4000)
_seq = 0

KINDS = {
    "task",
    "plan",
    "worker",
    "discuss",
    "review",
    "test",
    "git",
    "gateway",
    "hermes",
    "system",
    "log",
}


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def _write_line(ev: dict) -> None:
    try:
        with open(config.EVENTS_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        pass


def emit(kind: str, msg: str = "", **fields: Any) -> dict:
    """Emit one event. Thread-safe; safe to call from worker threads.

    The message parameter is named ``msg`` so callers can still pass a ``text``
    field without colliding with the positional argument.
    """
    global _seq
    with _lock:
        _seq += 1
        ev = {
            "id": _seq,
            "ts": time.time(),
            "kind": kind if kind in KINDS else "log",
            "text": str(msg)[:4000],
        }
        for k, v in fields.items():
            ev[k] = v
        _recent.append(ev)
        _write_line(ev)
        subs = list(_subscribers)
    if subs and _loop and not _loop.is_closed():
        for q in subs:
            try:
                _loop.call_soon_threadsafe(q.put_nowait, ev)
            except Exception:
                pass
    return ev


def recent(limit: int = 300, kind: str | None = None) -> list[dict]:
    with _lock:
        items = list(_recent)
    if kind:
        kinds = {k.strip() for k in kind.split(",") if k.strip()}
        items = [e for e in items if e["kind"] in kinds]
    return items[-limit:]


def load_from_disk(limit: int = 2000) -> int:
    """Rehydrate the in-memory ring from the JSONL feed (survives restarts).

    Only the tail is read. The feed grows without bound (worker stdout is long),
    so reading the whole file makes the UI slower every day it runs; the file
    itself is never truncated because it is the durable log.
    """
    global _seq
    p = config.EVENTS_FILE
    if not p.exists():
        return 0
    tail = _baca_ekor(p, 3_000_000)
    lines = tail.splitlines()[-limit:]
    n = 0
    with _lock:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            _recent.append(ev)
            _seq = max(_seq, int(ev.get("id", 0)))
            n += 1
    return n


def _baca_ekor(p: pathlib.Path, byte_anggaran: int) -> str:
    """Baca byte terakhir sebuah berkas teks tanpa memuat seluruh isinya."""
    try:
        ukuran = p.stat().st_size
        with open(p, "rb") as fh:
            if ukuran > byte_anggaran:
                fh.seek(ukuran - byte_anggaran)
                fh.readline()  # buang baris pertama yang mungkin terpotong
            return fh.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


# Hasil pembacaan kejadian satu tugas dari berkas, disimpan supaya panel proses
# tidak membaca ulang berkas besar tiap 3 detik. Kuncinya id tugas + ukuran
# berkas: tugas yang sudah selesai tidak berubah, jadi cache-nya kekal.
_berkas_tugas: dict[str, tuple[int, list[dict]]] = {}
_BERKAS_TUGAS_BYTE = 4_000_000


def untuk_tugas(tid: str, limit: int = 300) -> list[dict]:
    """Kejadian satu tugas, dibaca dari feed di disk kalau perlu.

    Ring di memori hanya menyimpan 4000 kejadian terakhir, dan aktivitas plugin
    Hermes bisa memenuhinya dalam beberapa menit. Tanpa membaca berkasnya,
    panel proses untuk tugas yang agak lama tampil kosong walau catatannya ada.
    """
    if not tid:
        return []
    with _lock:
        dari_ring = [e for e in _recent if e.get("task") == tid]
    if dari_ring:
        return dari_ring[-limit:]
    p = config.EVENTS_FILE
    try:
        ukuran = p.stat().st_size
    except Exception:
        return []
    simpan = _berkas_tugas.get(tid)
    if simpan and simpan[0] == ukuran:
        return simpan[1]
    out: list[dict] = []
    for line in _baca_ekor(p, _BERKAS_TUGAS_BYTE).splitlines():
        line = line.strip()
        if not line or tid not in line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("task") == tid:
            out.append(ev)
    out = out[-limit:]
    if len(_berkas_tugas) > 60:
        _berkas_tugas.clear()
    _berkas_tugas[tid] = (ukuran, out)
    return out


# ---------------------------------------------------------------- kunci berkas
# Tabel kecil {jalur berkas: pekerja yang memegang}. Ini Lapis 3 orkestrator:
# dipakai hanya kalau Lapis 1 dan 2 terbukti belum cukup (tabrakan berkas masih
# sering terjadi). Belum ada pemanggilnya: sengaja disediakan sebagai alat yang
# sudah teruji, bukan dinyalakan diam-diam.
_pegang_lock = threading.Lock()
_pegang: dict[str, str] = {}
_pegang_sejak: dict[str, float] = {}
# Batas pegang: pekerja yang mati tanpa melepas kuncinya tidak boleh membuat
# pekerja lain menunggu selamanya.
PEGANG_KEDALUWARSA = 1800.0


def _bersihkan_kedaluwarsa() -> list[str]:
    sekarang = time.time()
    lepas = [f for f, t in _pegang_sejak.items() if sekarang - t > PEGANG_KEDALUWARSA]
    for f in lepas:
        _pegang.pop(f, None)
        _pegang_sejak.pop(f, None)
    return lepas


def pegang_berkas(berkas: Iterable[str], pekerja: str) -> dict:
    """Coba pegang beberapa berkas sekaligus untuk satu pekerja.

    Semua atau tidak sama sekali: kalau satu berkas sedang dipegang pekerja
    lain, tidak ada satu pun yang dipegang oleh pemanggil. Memegang sebagian
    lalu gagal membuat dua pekerja sama-sama merasa berhak atas berkas berbeda
    di satu kelompok yang sama, dan tabrakan tetap terjadi.
    """
    minta = [b for b in dict.fromkeys(berkas) if b]
    with _pegang_lock:
        _bersihkan_kedaluwarsa()
        bentrok = {f: _pegang[f] for f in minta if f in _pegang and _pegang[f] != pekerja}
        if bentrok:
            return {"ok": False, "bentrok": bentrok, "dipegang": []}
        for f in minta:
            _pegang[f] = pekerja
            _pegang_sejak[f] = time.time()
        return {"ok": True, "bentrok": {}, "dipegang": minta}


def lepas_berkas(berkas: Iterable[str], pekerja: str) -> list[str]:
    """Lepas berkas yang dipegang pekerja ini; milik pekerja lain tidak disentuh."""
    dilepas: list[str] = []
    with _pegang_lock:
        for f in berkas:
            if _pegang.get(f) == pekerja:
                _pegang.pop(f, None)
                _pegang_sejak.pop(f, None)
                dilepas.append(f)
    return dilepas


def pegang_siapa() -> dict[str, str]:
    """Salinan tabel pegang, untuk panel dan pengujian."""
    with _pegang_lock:
        _bersihkan_kedaluwarsa()
        return dict(_pegang)


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def subscribers() -> int:
    return len(_subscribers)


def follow_file(path: str | os.PathLike, kind: str = "hermes", tag: str = "plugin") -> None:
    """Tail a JSONL file written by another process and re-emit as hub events.

    Used for the Hermes plugin feed (live_activity style) so the dashboard shows
    real Hermes agent-loop activity even though it happens in a separate process.
    """
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pos = path.stat().st_size if path.exists() else 0
    while True:
        try:
            if not path.exists():
                time.sleep(1.0)
                continue
            size = path.stat().st_size
            if size < pos:  # truncated/rotated
                pos = 0
            if size == pos:
                time.sleep(0.4)
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(pos)
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    ev.pop("id", None)
                    emit(kind, ev.get("text") or ev.get("message") or "", **{k: v for k, v in ev.items() if k not in ("text", "message")}, source=tag)
                pos = fh.tell()
        except Exception:
            time.sleep(1.0)
