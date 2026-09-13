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
    """Rehydrate the in-memory ring from the JSONL feed (survives restarts)."""
    global _seq
    p = config.EVENTS_FILE
    if not p.exists():
        return 0
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
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
