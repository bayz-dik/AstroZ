#!/usr/bin/env python3
"""Mulai ulang server UI AstroZ dengan aman.

Menghentikan uvicorn yang benar (dikenali dari cmdline + cwd, bukan dari kata
"hermes": server kadang jalan di venv Hermes, jadi filter itu justru membunuh
proses yang salah) lalu menyalakannya kembali lewat run.sh.

Jalankan: .venv/bin/python tools/mulai_ulang_ui.py
"""
from __future__ import annotations

import os
import pathlib
import signal
import subprocess
import time
import urllib.request

ROOT = pathlib.Path("/root/AstroZ")


def proses_ui() -> list[int]:
    keluar: list[int] = []
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            cmd = open(f"/proc/{p}/cmdline", "rb").read().decode("utf-8", "replace").replace("\x00", " ")
            cwd = os.readlink(f"/proc/{p}/cwd")
        except Exception:
            continue
        if "uvicorn" in cmd and "server:app" in cmd and cwd == str(ROOT):
            keluar.append(int(p))
    return keluar


def proses_watchdog() -> list[int]:
    keluar: list[int] = []
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            cmd = open(f"/proc/{p}/cmdline", "rb").read().decode("utf-8", "replace").replace("\x00", " ")
            cwd = os.readlink(f"/proc/{p}/cwd")
        except Exception:
            continue
        if "watchdog.py" in cmd and cwd == str(ROOT):
            keluar.append(int(p))
    return keluar


def hidup() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8799/api/tasks/running", timeout=10) as r:
            return b'"ok"' in r.read()
    except Exception:
        return False


wd = proses_watchdog()
for pid in wd:
    try:
        os.kill(pid, signal.SIGTERM)
        print("watchdog dihentikan:", pid)
    except Exception:
        pass

lama = proses_ui()
for pid in lama:
    try:
        os.kill(pid, signal.SIGTERM)
        print("server lama dihentikan:", pid)
    except Exception:
        pass
time.sleep(3)
for pid in lama:
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass

env = dict(os.environ)
env["PATH"] = "/usr/local/lib/hermes-agent/venv/bin:" + env.get("PATH", "")
subprocess.Popen(
    [str(ROOT / "run.sh")],
    cwd=str(ROOT),
    env=env,
    stdout=open(ROOT / "logs" / "run.out", "ab"),
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
for i in range(30):
    time.sleep(2)
    if hidup():
        print("server hidup lagi setelah", (i + 1) * 2, "detik")
        break
else:
    print("server TIDAK hidup setelah 60 detik")

if wd:
    subprocess.Popen(
        ["/usr/local/lib/hermes-agent/venv/bin/python", "watchdog.py", "--loop", "--interval", "30"],
        cwd=str(ROOT),
        stdout=open(ROOT / "logs" / "watchdog.out", "ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print("watchdog dinyalakan lagi")
