#!/usr/bin/env python3
"""Keep the AstroZ stack alive: 9Router, the SSE sanitiser, the UI.

Why a watchdog instead of "just leave them running": this stack lives in a
Termux/proot container that gets suspended, OOM-killed, or rebooted. Every
component dying looks the same from the outside, the UI is simply unreachable
and nothing says why. This checks each port and restarts only what is missing.

Ports are probed with a real TCP connect (not `ss`): in this environment `ss`
does not report listening sockets at all, so a port check based on it silently
reports everything as down and the watchdog restarts healthy services forever.

Usage:
  watchdog.py              one pass, restart what is down, print a report
  watchdog.py --loop       keep checking every --interval seconds (default 30)
  watchdog.py --status     report only, never restart
"""
from __future__ import annotations

import argparse
import json
import pathlib
import socket
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
PY = sys.executable
LOGS = ROOT / "logs"
RUNTIME = ROOT / "runtime"
STATE = RUNTIME / "watchdog.json"


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_ok(port: int, path: str, timeout: float = 5.0) -> bool:
    """Deeper check than a TCP connect: the port is open AND answers."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
            return 200 <= r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def spawn(args: list[str], log_name: str) -> int | None:
    """Start a detached process; returns its pid."""
    LOGS.mkdir(parents=True, exist_ok=True)
    fh = open(LOGS / log_name, "a", encoding="utf-8")
    try:
        p = subprocess.Popen(
            args,
            cwd=str(ROOT),
            stdout=fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        return p.pid
    except Exception as e:
        print(f"[watchdog] spawn failed for {log_name}: {e}", flush=True)
        return None
    finally:
        fh.close()


def wait_port(port: int, seconds: float = 25.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(0.5)
    return False


def ensure(name: str, port: int, check: tuple[str, ...], cmd: list[str],
           log: str, dry: bool) -> dict:
    """One service: is it answering? if not, start it and wait for the port."""
    alive = port_open(port) and all(http_ok(port, p) for p in check)
    out = {"name": name, "port": port, "alive": alive, "action": "none"}
    if alive:
        return out
    out["action"] = "would-restart" if dry else "restart"
    if dry:
        return out
    pid = spawn(cmd, log)
    out["pid"] = pid
    out["recovered"] = wait_port(port)
    print(f"[watchdog] {name} :{port} was down -> {'restarted' if out['recovered'] else 'RESTART FAILED'}"
          f"{f' (pid {pid})' if pid else ''}", flush=True)
    return out


def one_pass(dry: bool = False) -> dict:
    import config  # local import: watchdog may run before config is valid

    cfg = config.load()
    gw = cfg["gateway"]
    up_base = gw.get("upstream_base_url") or "http://127.0.0.1:20128"
    up_port = int(up_base.rsplit(":", 1)[-1].rstrip("/") or 20128)
    gw_port = int((gw.get("api_base") or "http://127.0.0.1:20129/v1").rsplit("/v1", 1)[0].rsplit(":", 1)[-1])
    ui_port = int(cfg["workflow"].get("ui_port") or 8799)

    report = {"ts": time.time(), "services": []}
    # Order matters: the sanitiser proxies the gateway, the UI reads both.
    report["services"].append(ensure(
        "9router", up_port, ("/api/health",),
        ["9router", "--no-browser", "--skip-update", "--port", str(up_port)],
        "9router.log", dry))
    report["services"].append(ensure(
        "sanitiser", gw_port, ("/api/health",),
        [PY, str(ROOT / "proxy.py"), "--listen", str(gw_port), "--upstream", f"127.0.0.1:{up_port}"],
        "proxy.log", dry))
    report["services"].append(ensure(
        "ui", ui_port, ("/api/state",),
        [PY, "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", str(ui_port)],
        "ui.log", dry))
    report["ok"] = all(s["alive"] or s.get("recovered") for s in report["services"])
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(report, indent=1))
    except Exception:
        pass
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--status", action="store_true", help="report only, never restart")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    while True:
        rep = one_pass(dry=args.status)
        if not args.quiet:
            line = " ".join(f"{s['name']}:{'up' if s['alive'] else ('fixed' if s.get('recovered') else 'DOWN')}"
                            for s in rep["services"])
            print(f"[watchdog] {time.strftime('%H:%M:%S')} {line}", flush=True)
        if not args.loop:
            return 0 if rep["ok"] else 1
        time.sleep(max(5.0, args.interval))


if __name__ == "__main__":
    sys.exit(main())
