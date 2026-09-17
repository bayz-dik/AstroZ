"""Chat sessions: one conversation thread, holding the tasks it produced.

A task is the unit of work; a session is the unit of reading. The user opens a
thread, sends messages, and each message becomes a task whose answer is appended
back to that same thread. Messages are not stored twice: a task already carries
its prompt (the user turn) and its answer (the AstroZ turn), so a session only
keeps the ordered list of task ids.
"""
from __future__ import annotations

import json
import pathlib
import threading
import time
import uuid

import config

SESSIONS_FILE = config.RUNTIME / "sessions.json"
MAX_SESSIONS = 40

# Pemilik sesi. Berkas lama tidak punya kolom ini, jadi dibaca sebagai milik
# admin: percakapan yang sudah ada sebelum pemisahan tidak boleh hilang dari
# pemiliknya sendiri.
PEMILIK_BAWAAN = "admin"

_lock = threading.Lock()
_S: dict[str, dict] = {}


def load() -> int:
    if not SESSIONS_FILE.exists():
        return 0
    try:
        items = json.loads(SESSIONS_FILE.read_text())
    except Exception:
        return 0
    for s in items:
        if isinstance(s, dict) and s.get("id"):
            s.setdefault("owner", PEMILIK_BAWAAN)
            _S[s["id"]] = s
    return len(_S)


def _persist() -> None:
    try:
        items = sorted(_S.values(), key=lambda s: s.get("updated", 0), reverse=True)[:MAX_SESSIONS]
        SESSIONS_FILE.write_text(json.dumps(items, ensure_ascii=False, default=str))
    except Exception:
        pass


def _title_from(text: str) -> str:
    t = " ".join((text or "").split())
    return (t[:48] + "…") if len(t) > 48 else (t or "Percakapan baru")


def create(title: str = "", owner: str = PEMILIK_BAWAAN) -> dict:
    now = time.time()
    s = {"id": uuid.uuid4().hex[:10], "title": title.strip() or "Percakapan baru",
         "created": now, "updated": now, "tasks": [], "pinned": False,
         "owner": (owner or PEMILIK_BAWAAN).strip().lower()}
    with _lock:
        _S[s["id"]] = s
    _persist()
    return s


def get(sid: str) -> dict | None:
    return _S.get(sid or "")


def get_milik(sid: str, owner: str) -> dict | None:
    """Ambil sesi HANYA kalau pemiliknya cocok.

    Dipakai semua endpoint yang menyebut satu sesi. Tanpa ini, menebak id sesi
    sudah cukup untuk membaca percakapan orang lain.
    """
    s = _S.get(sid or "")
    if not s:
        return None
    if (s.get("owner") or PEMILIK_BAWAAN) != (owner or "").strip().lower():
        return None
    return s


def ensure(sid: str | None, first_text: str = "", owner: str = PEMILIK_BAWAAN) -> dict:
    """Return the session to use: the given one, or a fresh one.

    Sesi yang diberikan tetapi bukan milik `owner` diperlakukan sebagai tidak
    ada: pengguna mendapat percakapan baru, bukan percakapan orang lain.
    """
    s = get_milik(sid, owner) if sid else None
    if s:
        return s
    return create(_title_from(first_text), owner)


def attach(sid: str, tid: str, prompt: str = "") -> dict | None:
    s = get(sid)
    if not s:
        return None
    with _lock:
        if tid not in s["tasks"]:
            s["tasks"].append(tid)
        if s["title"] in ("", "Percakapan baru") and prompt:
            s["title"] = _title_from(prompt)
        s["updated"] = time.time()
    _persist()
    return s


def rename(sid: str, title: str, owner: str | None = None) -> dict | None:
    s = get_milik(sid, owner) if owner is not None else get(sid)
    if not s:
        return None
    s["title"] = (title or "").strip()[:80] or s["title"]
    s["updated"] = time.time()
    _persist()
    return s


def delete(sid: str, owner: str | None = None) -> bool:
    if owner is not None and not get_milik(sid, owner):
        return False
    with _lock:
        gone = _S.pop(sid, None)
    if gone:
        _persist()
    return bool(gone)


def toggle_pin(sid: str, pinned: bool | None = None, owner: str | None = None) -> dict | None:
    """Sematkan atau lepas sematan percakapan.

    Tanpa nilai yang dikirim, keadaannya dibalik. Sematan tidak mengubah
    `updated`, kalau ikut berubah urutannya bergeser sendiri setiap kali
    disematkan.
    """
    s = get_milik(sid, owner) if owner is not None else get(sid)
    if not s:
        return None
    s["pinned"] = (not s.get("pinned")) if pinned is None else bool(pinned)
    _persist()
    return s


def list_sessions(owner: str | None = None) -> list[dict]:
    """Daftar percakapan. `owner` menyaring; None berarti semua (dipakai admin).

    Yang disematkan selalu di atas, sisanya urut dari yang terakhir dipakai.
    """
    if owner is None:
        items = list(_S.values())
    else:
        owner = (owner or "").strip().lower()
        items = [s for s in _S.values() if (s.get("owner") or PEMILIK_BAWAAN) == owner]
    items.sort(key=lambda s: (bool(s.get("pinned")), s.get("updated", 0)), reverse=True)
    return [
        {
            "id": s["id"],
            "title": s["title"],
            "created": s.get("created"),
            "updated": s.get("updated"),
            "pinned": bool(s.get("pinned")),
            "task_count": len(s.get("tasks", [])),
            "tasks": list(s.get("tasks", []))[:40],
            "owner": s.get("owner") or PEMILIK_BAWAAN,
        }
        for s in items
    ]
