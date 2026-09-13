#!/usr/bin/env python3
"""Direct worker smoke: run every installed worker CLI through the gateway.

One source of truth: the command line and environment come from adapters.py,
the same code the orchestrator uses. Hardcoding the CLI flags in the shell test
is how this test drifted from the adapters (claude without IS_SANDBOX, omp
without the 9router/ provider prefix) and reported FAILs that were test bugs.

Usage: worker_smoke.py [--model MODEL] [--timeout 240] [worker ...]
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import adapters  # noqa: E402
import config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("workers", nargs="*", default=None)
    ap.add_argument("--model", default="")
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    cfg = config.load()
    gw = cfg["gateway"]
    model = args.model or gw["model"]
    cwd = str(cfg["project_dir"])
    keys = args.workers or ["claude", "codex", "opencode", "omp"]

    print(f"[worker-smoke] model={model} cwd={cwd}")
    rc_all = 0
    for key in keys:
        a = adapters.ADAPTERS.get(key)
        if a is None:
            print(f"[worker-smoke] {key}: SKIP (unknown worker)")
            continue
        if not a.path:
            a.probe()
        if not a.path:
            print(f"[worker-smoke] {key}: SKIP (not installed)")
            continue
        prompt = f"Reply with exactly: SMOKE_OK_{key}"
        cmd = a.command(prompt, model, cwd)
        env = {**os.environ, **a.env({**gw, "model": model}, model)}
        t0 = time.time()
        try:
            p = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                env=env,
                stdin=subprocess.DEVNULL,
            )
            out = (p.stdout or "") + (p.stderr or "")
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or "") + (e.stderr or "") if isinstance(e.stdout, str) else ""
            out += f"\n[timeout after {args.timeout}s]"
        dur = round(time.time() - t0, 1)
        ok = f"SMOKE_OK_{key}" in out
        if not ok:
            rc_all = 1
        tail = " ".join(out.strip().splitlines()[-3:])[-220:]
        print(f"[worker-smoke] {key}: {'PASS' if ok else 'FAIL'} ({dur}s) {'' if ok else '-> ' + tail}")
    return rc_all


if __name__ == "__main__":
    raise SystemExit(main())
