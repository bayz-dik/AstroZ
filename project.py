"""Project helpers: file tree, git status/diff, test discovery + execution."""
from __future__ import annotations

import hashlib
import os
import pathlib
import shlex
import shutil
import subprocess
import time
from typing import Any, Iterable

import config
import hub

ROOT = pathlib.Path(__file__).resolve().parent
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build", ".mypy_cache"}
# Berkas yang isinya bukan hasil kerja siapa pun dan selalu ada di repo: ikut
# dihitung, panel berkas penuh sampah setiap tugas selesai.
SKIP_FILES = {".DS_Store", "Thumbs.db", ".gitkeep"}
# Batas jumlah berkas saat menelusuri folder kerja. Foldernya milik pengguna,
# bisa berisi ribuan berkas (node_modules yang tidak terdeteksi, hasil build):
# penelusuran tanpa batas membuat satu permintaan UI berjalan detik-detikan.
BATAS_BERKAS = 20000


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


def berkas_baru() -> set[str]:
    """Berkas yang belum dilacak git, untuk dijadikan garis dasar satu tugas.

    Dipakai supaya ringkasan perubahan hanya berisi berkas yang dibuat TUGAS
    INI. Tanpa garis dasar, sisa berkas dari tugas lama ikut terhitung: diukur
    pada mesin ini, .riset/ads.md dari tugas riset lama muncul sebagai
    "new file" di setiap tugas berikutnya, ikut masuk ringkasan, dan penilai
    membacanya sebagai hasil pekerjaan yang tidak diminta.
    """
    d = project_dir()
    _, untracked = _git(["ls-files", "--others", "--exclude-standard"], d)
    return {f.strip() for f in untracked.splitlines() if f.strip()}


def change_summary(limit: int = 12000, abaikan: set[str] | None = None) -> str:
    """Everything the workers changed: tracked diff + untracked file contents.

    `git diff` alone is empty when a worker creates new files, which is the
    common case, so the reviewer would be shown nothing to review.

    `abaikan` adalah berkas yang sudah ada sebelum tugas mulai (lihat
    berkas_baru). Berkas di daftar itu tidak dilaporkan lagi sebagai buatan
    tugas ini.
    """
    d = project_dir()
    lewat = abaikan or set()
    parts: list[str] = []
    _, diff = _git(["diff", "--no-color", "HEAD"], d, timeout=40)
    if diff.strip():
        parts.append("--- tracked diff ---\n" + diff[: limit // 2])
    _, untracked = _git(["ls-files", "--others", "--exclude-standard"], d)
    files = [f for f in untracked.splitlines() if f.strip() and f.strip() not in lewat][:20]
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


def git_commit_all(message: str, abaikan: set[str] | None = None) -> dict:
    """Simpan semua perubahan di folder kerja.

    `abaikan` adalah berkas yang sudah ada sebelum tugas mulai: berkas itu tidak
    ikut ditambahkan. `git add -A` tanpa penyaringan akan menelan berkas asing
    (sisa tugas lama, catatan kerja) ke dalam commit tugas yang lolos verifikasi,
    sehingga commit tidak lagi berarti "isi ini sudah diperiksa".
    """
    d = ensure_repo()
    lewat = {f for f in (abaikan or set()) if f}
    if lewat:
        # Tambahkan hanya berkas yang bukan garis dasar. `git add -A` dipakai
        # untuk sisanya supaya berkas yang dihapus tetap tercatat.
        _, untracked = _git(["ls-files", "--others", "--exclude-standard"], d)
        baru = [f.strip() for f in untracked.splitlines() if f.strip() and f.strip() not in lewat]
        if baru:
            _git(["add", "--", *baru], d, timeout=40)
        _git(["add", "-u"], d, timeout=40)
        _, belum = _git(["diff", "--cached", "--name-only"], d)
        if not (belum or "").strip():
            return {"rc": 0, "out": "nothing to commit"}
    else:
        _git(["add", "-A"], d)
    rc, out = _git(["commit", "-qm", message], d, timeout=40)
    hub.emit("git", f"Commit: {message}", rc=rc, out=out[:500])
    return {"rc": rc, "out": out}


def _hash_berkas(p: pathlib.Path) -> str:
    """Isi satu berkas jadi sidik jari pendek; berkas tidak terbaca dianggap kosong."""
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest()[:16]
    except Exception:
        return ""


def _lewati(p: pathlib.Path, d: pathlib.Path) -> bool:
    """True kalau berkas ini bukan hasil kerja siapa pun dan tak perlu dipantau."""
    if p.name in SKIP_FILES:
        return True
    try:
        rel = p.relative_to(d)
    except Exception:
        return True
    return any(b in rel.parts for b in SKIP_DIRS) or any(x.startswith(".git") for x in rel.parts)


def _susun(p: pathlib.Path, d: pathlib.Path) -> dict:
    """Satu baris catatan untuk satu berkas: isi, ukuran, waktu ubah."""
    try:
        st = p.stat()
        return {"hash": _hash_berkas(p), "size": st.st_size, "mtime": round(st.st_mtime, 3)}
    except Exception:
        return {"hash": "", "size": 0, "mtime": 0.0}


def _jalur_kunci(d: pathlib.Path, rel: str) -> pathlib.Path | None:
    """Ubah jalur relatif jadi Path yang benar-benar di dalam folder kerja.

    `lstrip("./")` TIDAK dipakai di sini: ia membuang semua karakter titik dan
    garis miring di depan, jadi `../rahasia.txt` berubah jadi `rahasia.txt` dan
    terlihat seperti berkas di dalam folder kerja. Akibatnya berkas di luar
    folder kerja bisa ikut dipulihkan atau dihapus. Yang dibuang hanya awalan
    `./` yang utuh.
    """
    if not rel:
        return None
    bersih = rel.strip()
    if bersih.startswith("./"):
        bersih = bersih[2:]
    if not bersih:
        return None
    d_nyata = d.resolve()
    p = (d_nyata / bersih).resolve()
    if p != d_nyata and not str(p).startswith(str(d_nyata) + os.sep):
        return None
    return p


def snap_berkas(daftar: Iterable[str] | None = None, maks_scan: int = BATAS_BERKAS) -> dict:
    """Isi tiap berkas di folder kerja, sebagai pembanding sebelum dan sesudah.

    Dipakai Lapis 2 orkestrator: sebelum pekerja paralel dilepas, folder kerja
    disidik jari; sesudahnya, selisihnya menunjukkan berkas mana yang BENAR-BENAR
    berubah, bukan berkas mana yang diklaim berubah.

    Tanpa `daftar`, seluruh folder kerja dipindai. Pemindaiannya selalu
    dipotong di `maks_scan` berkas: folder kerja bisa berisi puluhan ribu berkas
    (node_modules, hasil build) dan memindai semuanya membuat satu tugas
    menggantung di langkah yang seharusnya selesai dalam sekejap. Berkas yang
    terlewat karena batas itu dilaporkan di `terpotong`, bukan disembunyikan.
    """
    d = project_dir()
    out: dict[str, dict] = {}
    if daftar:
        for rel in daftar:
            p = _jalur_kunci(d, rel)
            if p is None or not p.is_file() or _lewati(p, d):
                continue
            out[str(p.relative_to(d))] = _susun(p, d)
        return {"berkas": out, "terpotong": False}
    jumlah = 0
    terpotong = False
    for p in d.rglob("*"):
        jumlah += 1
        if jumlah > maks_scan:
            terpotong = True
            break
        if not p.is_file() or _lewati(p, d):
            continue
        out[str(p.relative_to(d))] = _susun(p, d)
    return {"berkas": out, "terpotong": terpotong}


def beda_snap(sebelum: dict, sesudah: dict) -> dict:
    """Berkas yang berubah di antara dua sidik jari.

    Hasilnya dipisah jadi `diubah` (isi berbeda), `dibuat` (tidak ada sebelum),
    dan `dihapus`. Berkas yang cuma berubah waktunya (mtime) tidak dihitung:
    beberapa CLI menulis ulang berkas dengan isi yang sama persis.
    """
    a = (sebelum or {}).get("berkas") or {}
    b = (sesudah or {}).get("berkas") or {}
    diubah, dibuat, dihapus = [], [], []
    for rel, info in b.items():
        lama = a.get(rel)
        if lama is None:
            dibuat.append(rel)
        elif lama.get("hash") != info.get("hash"):
            diubah.append(rel)
    for rel in a:
        if rel not in b:
            dihapus.append(rel)
    return {
        "diubah": sorted(diubah),
        "dibuat": sorted(dibuat),
        "dihapus": sorted(dihapus),
        "terpotong": bool((sebelum or {}).get("terpotong") or (sesudah or {}).get("terpotong")),
    }


def _salin_cadangan(p: pathlib.Path, tempat: pathlib.Path) -> None:
    tempat.parent.mkdir(parents=True, exist_ok=True)
    if p.is_file():
        shutil.copy2(p, tempat)


def pulihkan_berkas(relatif: Iterable[str], cadangan: pathlib.Path, awal: dict | None = None) -> dict:
    """Kembalikan berkas ke isi sebelum tugas, dari salinan di luar folder kerja.

    Dipakai Lapis 2: berkas yang diklaim oleh lebih dari satu pekerja tidak
    boleh dipercaya, jadi isinya dikembalikan dulu supaya tugas yang sama bisa
    dijalankan ulang dari kondisi bersih, bukan dari hasil campur dua pekerja.

    Berkas yang tadi dibuat dari nol (tidak ada di `awal`) dihapus, bukan
    dikosongkan: sisa berkas kosong akan terbaca sebagai perubahan di tugas
    berikutnya. Salinannya dibaca dari `cadangan`, jadi berkas hasil pekerja
    tidak perlu disimpan di dalam folder kerja itu sendiri.
    """
    d = project_dir()
    asal = (awal or {}).get("berkas") or {}
    kembali: list[str] = []
    hapus: list[str] = []
    gagal: list[str] = []
    for rel in relatif:
        p = _jalur_kunci(d, rel)
        if p is None:
            gagal.append(rel)
            continue
        asli = cadangan / rel
        if asli.is_file():
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(asli, p)
                kembali.append(rel)
            except Exception:
                gagal.append(rel)
            continue
        if rel in asal:
            # Berkas lama yang isinya tidak sempat disalin (mis. biner besar):
            # dipulihkan lewat git, bukan dibiarkan berisi kerja yang bentrok.
            rc, _ = _git(["checkout", "--", rel], d, timeout=30)
            (kembali if rc == 0 else gagal).append(rel)
            continue
        try:
            p.unlink()
            hapus.append(rel)
        except FileNotFoundError:
            hapus.append(rel)
        except Exception:
            gagal.append(rel)
    return {"kembali": kembali, "dihapus": hapus, "gagal": gagal}


def snap_sementara(berkas: Iterable[str], tag: str = "tugas", maks: int = 4000) -> pathlib.Path | None:
    """Salin berkas di luar folder kerja supaya bisa dipulihkan nanti.

    Salinannya sengaja diletakkan di luar folder kerja (runtime/), bukan di
    dalamnya: berkas cadangan di dalam folder kerja akan terbaca sebagai
    perubahan tugas oleh panel berkas, ringkasan, dan penilai.
    """
    d = project_dir()
    tempat = config.RUNTIME / "cadangan" / (tag or "tugas")
    berkas = list(dict.fromkeys([b for b in berkas if b]))[:maks]
    if not berkas:
        return None
    try:
        tempat.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    for rel in berkas:
        p = _jalur_kunci(d, rel)
        if p is None or not p.is_file():
            continue
        try:
            _salin_cadangan(p, tempat / rel)
        except Exception:
            continue
    return tempat


def berkas_sejak(mulai: float, maks: int = 80) -> dict:
    """Berkas yang berubah sesudah `mulai`, di folder kerja.

    Dipakai panel samping untuk memperlihatkan hasil satu tugas tanpa membaca
    seluruh folder kerja. Batasnya: berhenti setelah BATAS_BERKAS berkas atau
    setelah cukup banyak berkas cocok, mana yang lebih dulu. Tanpa batas itu,
    folder kerja besar membuat permintaan ini berjalan detik-detikan dan UI
    tampak menggantung.
    """
    d = project_dir()
    out: list[dict] = []
    jumlah = 0
    if not d.exists() or not mulai:
        return {"dir": str(d), "berkas": [], "jumlah": 0, "terpotong": False}
    for p in d.rglob("*"):
        jumlah += 1
        if jumlah > BATAS_BERKAS:
            break
        if p.is_dir() or p.name in SKIP_FILES:
            continue
        if any(b in p.parts for b in SKIP_DIRS):
            continue
        try:
            st = p.stat()
        except Exception:
            continue
        if st.st_mtime >= mulai - 1:
            out.append({"path": str(p.relative_to(d)), "size": st.st_size, "mtime": st.st_mtime})
    out.sort(key=lambda x: -x["mtime"])
    return {
        "dir": str(d),
        "berkas": out[:maks],
        "jumlah": len(out),
        "terpotong": jumlah > BATAS_BERKAS or len(out) > maks,
    }


def _punya_pytest(py: str) -> bool:
    """Apakah interpreter ini benar-benar bisa menjalankan pytest?"""
    if not py:
        return False
    try:
        p = subprocess.run(
            [py, "-c", "import pytest"],
            capture_output=True,
            timeout=20,
        )
        return p.returncode == 0
    except Exception:
        return False


def _interpreter_tes(d: pathlib.Path) -> str:
    """Interpreter yang benar-benar punya pytest, bukan sekadar venv yang ada.

    Diukur pada mesin ini: folder kerja punya .venv sendiri yang berisi pytest,
    sementara .venv milik AstroZ sendiri tidak (dependensinya hanya fastapi,
    uvicorn, PyYAML). Memilih venv pertama yang ada membuat setiap tugas
    melaporkan "tests: FAIL" dengan keluaran `No module named pytest`, walau
    tes proyeknya hijau, dan penilai ikut membaca FAIL itu sebagai kegagalan
    pekerjaan. Jadi yang diperiksa pytest-nya, bukan keberadaan foldernya.

    Urutan: $PY, lalu venv folder kerja, lalu venv AstroZ, lalu python3.
    """
    kandidat: list[str] = []
    env = os.environ.get("PY")
    if env and pathlib.Path(env).exists():
        kandidat.append(env)
    for venv in (d / ".venv", ROOT / ".venv", d / "venv", ROOT / "venv"):
        py = venv / "bin" / "python"
        if py.exists():
            kandidat.append(str(py))
    py3 = shutil.which("python3")
    if py3:
        kandidat.append(py3)
    for py in kandidat:
        if _punya_pytest(py):
            return py
    # Tidak ada yang punya pytest: pakai kandidat pertama supaya pesan
    # kegagalannya tetap menyebut interpreter yang paling masuk akal.
    return kandidat[0] if kandidat else (py3 or "python3")


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
        # Interpreter yang pytest-nya benar-benar ada, bukan venv pertama yang
        # ditemukan: lihat _interpreter_tes.
        return f"{_interpreter_tes(d)} -m pytest -q"
    if (d / "Makefile").exists():
        return "make test"
    return ""


def _venv_python(d: pathlib.Path) -> str:
    """Interpreter yang punya dependensi tes proyek, kalau ada venv-nya."""
    for venv in (d / ".venv", ROOT / ".venv", d / "venv", ROOT / "venv"):
        if (venv / "bin" / "python").exists():
            return str(venv / "bin" / "python")
    return ""


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
