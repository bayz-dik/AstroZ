"""Project helpers: file tree, git status/diff, test discovery + execution."""
from __future__ import annotations

import os
import pathlib
import shlex
import shutil
import subprocess
import time
from typing import Any

import config
import hub

ROOT = pathlib.Path(__file__).resolve().parent
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build", ".mypy_cache"}


def project_dir() -> pathlib.Path:
    p = pathlib.Path(config.load()["project_dir"]).expanduser()
    # Pekerja CLI dijalankan dengan cwd yang sudah disiapkan orkestrator. Kalau
    # mereka juga memanggil ini (lewat project.ensure_repo atau alat bantu),
    # folder kerja baru ikut dibuat di mesin pekerja. Jangan: cukup pastikan
    # cwd-nya ada.
    if os.environ.get("ASTROZ_PEKERJA"):
        return pathlib.Path.cwd()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _git(args: list[str], cwd: pathlib.Path, timeout: int = 25) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "git not installed"
    except Exception as e:
        return 1, str(e)


def ensure_repo() -> pathlib.Path:
    d = project_dir()
    # Di dalam pekerja, jangan pernah git init: cwd adalah folder kerja yang
    # sudah disiapkan orkestrator. Menjalankan init di sini adalah cara folder
    # kerja baru muncul sendiri setiap kali pekerja menyentuh berkas.
    if os.environ.get("ASTROZ_PEKERJA"):
        return d
    if not (d / ".git").exists():
        _git(["init", "-q"], d)
        _git(["config", "user.email", "astroz@local"], d)
        _git(["config", "user.name", "AstroZ"], d)
        (d / "README.md").write_text("# AstroZ Workspace\n\nFolder kerja proyek yang dikerjakan tim AstroZ.\n")
        _git(["add", "-A"], d)
        _git(["commit", "-qm", "chore: init workspace"], d)
    return d


def tree(max_entries: int = 400, max_depth: int = 4) -> list[dict]:
    d = project_dir()
    out: list[dict] = []

    def walk(p: pathlib.Path, depth: int) -> None:
        if len(out) >= max_entries or depth > max_depth:
            return
        try:
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except Exception:
            return
        for e in entries:
            if e.name in SKIP_DIRS or e.name.startswith(".git"):
                continue
            rel = str(e.relative_to(d))
            if e.is_dir():
                out.append({"path": rel, "type": "dir"})
                walk(e, depth + 1)
            else:
                try:
                    size = e.stat().st_size
                except Exception:
                    size = 0
                out.append({"path": rel, "type": "file", "size": size})

    walk(d, 0)
    return out


def read_file(rel: str, limit: int = 200000) -> dict:
    d = project_dir()
    p = (d / rel).resolve()
    if not str(p).startswith(str(d.resolve())):
        return {"ok": False, "error": "path escapes project dir"}
    try:
        return {"ok": True, "path": rel, "content": p.read_text(errors="replace")[:limit]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def git_status() -> dict:
    d = ensure_repo()
    _, st = _git(["status", "--porcelain=v1", "-b"], d)
    _, log = _git(["log", "--oneline", "-n", "20"], d)
    _, diffstat = _git(["diff", "--stat", "HEAD"], d)
    return {"branch": st.splitlines()[0][3:] if st.startswith("##") else "", "status": st, "log": log, "diffstat": diffstat}


def change_summary(limit: int = 12000) -> str:
    """Everything the workers changed: tracked diff + untracked file contents.

    `git diff` alone is empty when a worker creates new files, which is the
    common case, so the reviewer would be shown nothing to review.
    """
    d = project_dir()
    parts: list[str] = []
    _, diff = _git(["diff", "--no-color", "HEAD"], d, timeout=40)
    if diff.strip():
        parts.append("--- tracked diff ---\n" + diff[: limit // 2])
    _, untracked = _git(["ls-files", "--others", "--exclude-standard"], d)
    files = [f for f in untracked.splitlines() if f.strip()][:20]
    for f in files:
        p = d / f
        try:
            body = p.read_text(errors="replace")[:3000]
        except Exception:
            continue
        parts.append(f"--- new file: {f} ---\n{body}")
    if not parts:
        return ""
    return "\n\n".join(parts)[:limit]


def git_diff(path: str = "", staged: bool = False) -> str:
    d = project_dir()
    args = ["diff", "--no-color"]
    if staged:
        args.append("--cached")
    if path:
        args += ["--", path]
    _, out = _git(args, d, timeout=40)
    if not out.strip():
        _, out = _git(["diff", "--no-color", "HEAD"], d, timeout=40)
    return out[:200000]


def git_commit_all(message: str) -> dict:
    d = ensure_repo()
    _git(["add", "-A"], d)
    rc, out = _git(["commit", "-qm", message], d, timeout=40)
    hub.emit("git", f"Commit: {message}", rc=rc, out=out[:500])
    return {"rc": rc, "out": out}


def detect_test_command() -> str:
    cfg = config.load()["workflow"].get("test_command") or ""
    if cfg:
        return cfg
    d = project_dir()
    if (d / "package.json").exists():
        try:
            import json

            pkg = json.loads((d / "package.json").read_text())
            if pkg.get("scripts", {}).get("test"):
                return "npm test --silent"
        except Exception:
            pass
    has_python_tests = (
        (d / "pytest.ini").exists()
        or (d / "pyproject.toml").exists()
        or list(d.glob("tests/test_*.py"))
        or list(d.glob("test_*.py"))
    )
    if has_python_tests:
        # Prefer a project-local venv: the system python is often PEP-668 managed
        # and may not have pytest, so a bare `python3 -m pytest` fails.
        return f"{_python()} -m pytest -q"
    if (d / "Makefile").exists():
        return "make test"
    return ""


def _venv_python(d: pathlib.Path) -> str:
    """Interpreter yang punya dependensi tes proyek, kalau ada venv-nya."""
    for venv in (d / ".venv", ROOT / ".venv", d / "venv", ROOT / "venv"):
        if (venv / "bin" / "python").exists():
            return str(venv / "bin" / "python")
    return ""


def _python() -> str:
    """Interpreter yang dipakai untuk menjalankan tes.

    Urutannya: $PY, lalu venv di folder proyek, lalu python3. Dulu ada path venv
    milik mesin pengembang di sini, jadi skrip ini gagal di mesin orang lain.
    """
    env = os.environ.get("PY")
    if env and pathlib.Path(env).exists():
        return env
    for kandidat in (ROOT / ".venv" / "bin" / "python", ROOT / "venv" / "bin" / "python"):
        if kandidat.exists():
            return str(kandidat)
    return shutil.which("python3") or "python3"


def run_tests(command: str | None = None, task_id: str = "", timeout: int = 600) -> dict:
    cmd = command or detect_test_command()
    d = project_dir()
    if not cmd:
        hub.emit("test", "Perintah tes tidak terdeteksi, tes dilewati", task=task_id)
        return {"ok": None, "skipped": True, "command": ""}
    # A planner (or the user) can hand us a bare `python -m pytest`, which hits
    # the PEP-668 system interpreter and fails before the tests ever run.
    venv_py = _venv_python(d)
    if venv_py:
        for bare in ("python3 ", "python "):
            if cmd.startswith(bare):
                cmd = venv_py + " " + cmd[len(bare):]
                break
    hub.emit("test", f"Menjalankan: {cmd}", task=task_id, command=cmd, phase="start")
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd,
            shell=True,
            cwd=str(d),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "CI": "1"},
        )
        out = ((p.stdout or "") + (p.stderr or ""))[-8000:]
        ok = p.returncode == 0
        dur = round(time.time() - t0, 2)
        hub.emit(
            "test",
            f"{'LULUS' if ok else 'TIDAK LULUS'} ({dur}s): {cmd}",
            task=task_id,
            command=cmd,
            rc=p.returncode,
            duration=dur,
            output=out[-4000:],
            phase="end",
            ok=ok,
        )
        return {"ok": ok, "command": cmd, "rc": p.returncode, "output": out, "duration": dur}
    except subprocess.TimeoutExpired:
        hub.emit("test", f"Melebihi batas waktu {timeout}s: {cmd}", task=task_id, ok=False)
        return {"ok": False, "command": cmd, "output": "timeout", "rc": 124}
