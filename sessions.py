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


def create(title: str = "") -> dict:
    now = time.time()
    s = {"id": uuid.uuid4().hex[:10], "title": title.strip() or "Percakapan baru",
         "created": now, "updated": now, "tasks": []}
    with _lock:
        _S[s["id"]] = s
    _persist()
    return s


def get(sid: str) -> dict | None:
    return _S.get(sid or "")


def ensure(sid: str | None, first_text: str = "") -> dict:
    """Return the session to use: the given one, or a fresh one."""
    s = get(sid) if sid else None
    if s:
        return s
    return create(_title_from(first_text))


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


def rename(sid: str, title: str) -> dict | None:
    s = get(sid)
    if not s:
        return None
    s["title"] = (title or "").strip()[:80] or s["title"]
    s["updated"] = time.time()
    _persist()
    return s


def delete(sid: str) -> bool:
    with _lock:
        gone = _S.pop(sid, None)
    if gone:
        _persist()
    return bool(gone)


def list_sessions() -> list[dict]:
    items = sorted(_S.values(), key=lambda s: s.get("updated", 0), reverse=True)
    return [
        {
            "id": s["id"],
            "title": s["title"],
            "created": s.get("created"),
            "updated": s.get("updated"),
            "task_count": len(s.get("tasks", [])),
            "tasks": list(s.get("tasks", []))[:40],
        }
        for s in items
    ]
