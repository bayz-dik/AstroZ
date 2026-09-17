"""Pulihkan berkas paket yang hilang setelah dipasang dengan uv.

Masalah lingkungan, bukan masalah paketnya: di container proot ini `uv pip
install` kadang tidak menyalin sebagian berkas sebuah paket. Yang paling sering
kena `__init__.py`, sehingga paket terbaca sebagai namespace package dan
impor gagal dengan pesan menyesatkan:

    module 'requests' has no attribute 'Session'
    cannot import name '__version__' from 'pydantic_core'

Terukur kena di requests, charset_normalizer, anyio, uvicorn, PyJWT, dan
pydantic_core.

Cara kerja: setiap paket yang terpasang punya `*.dist-info/RECORD` yang
mendaftar semua berkasnya. Skrip ini membandingkan daftar itu dengan isi folder
yang sebenarnya, lalu mengambil berkas yang hilang dari wheel aslinya. Ini
menangkap berkas apa pun (termasuk .so dan data), bukan hanya __init__.py.

Dipakai: python perbaiki_venv.py <venv> [python-yang-punya-pip]
"""
from __future__ import annotations

import csv
import pathlib
import subprocess
import sys
import tempfile
import zipfile


def site_packages(venv: pathlib.Path) -> pathlib.Path:
    for p in sorted(venv.rglob("site-packages")):
        if p.is_dir():
            return p
    raise SystemExit(f"site-packages tidak ditemukan di {venv}")


def _nama_dist(nama: str) -> str:
    """Nama paket untuk diunduh: ambil bagian sebelum penanda versi."""
    return nama.split("-")[0]


def _hilang(sp: pathlib.Path) -> dict[str, list[str]]:
    """Peta nama-paket -> berkas yang tercatat di RECORD tapi tidak ada di disk."""
    out: dict[str, list[str]] = {}
    for di in sorted(sp.glob("*.dist-info")):
        rec = di / "RECORD"
        if not rec.is_file():
            continue
        nama = di.name.split("-")[0]
        hilang: list[str] = []
        try:
            with open(rec, encoding="utf-8", errors="replace") as fh:
                for baris in csv.reader(fh):
                    if not baris:
                        continue
                    rel = baris[0]
                    if rel.endswith("/") or ".dist-info" in rel or "__pycache__" in rel:
                        continue
                    if not (sp / rel).exists():
                        hilang.append(rel)
        except Exception:
            continue
        if hilang:
            out[nama] = hilang
    return out


def _pulihkan(sp: pathlib.Path, nama: str, berkas: list[str], tmp: pathlib.Path, python_pip: str) -> int:
    unduh = tmp / nama
    unduh.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [python_pip, "-m", "pip", "download", "--no-deps", "--only-binary", ":all:",
         "--dest", str(unduh), _nama_dist(nama)],
        capture_output=True, text=True, timeout=300,
    )
    wheel = next(iter(sorted(unduh.glob("*.whl"))), None)
    if not wheel:
        print(f"  {nama}: wheel tidak didapat ({r.stderr.strip()[:110]})")
        return 0
    perlu = set(berkas)
    n = 0
    with zipfile.ZipFile(wheel) as z:
        for entri in z.namelist():
            if entri.endswith("/") or entri not in perlu:
                continue
            tujuan = sp / entri
            tujuan.parent.mkdir(parents=True, exist_ok=True)
            tujuan.write_bytes(z.read(entri))
            n += 1
    print(f"  {nama}: {n} dari {len(perlu)} berkas dipulihkan ({wheel.name})")
    return n


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    akar = pathlib.Path(sys.argv[1]).expanduser().resolve()
    # Penerjemah yang punya pip dipakai untuk mengunduh wheel: venv pekerja
    # sering dibuat uv tanpa pip, jadi jalurnya harus bisa ditunjuk terpisah.
    python_pip = sys.argv[2] if len(sys.argv) > 2 else sys.executable
    sp = site_packages(akar)
    rusak = _hilang(sp)
    if not rusak:
        print("Tidak ada berkas paket yang hilang.")
        return 0
    print(f"Paket dengan berkas hilang di {sp}:")
    for nama, berkas in sorted(rusak.items()):
        contoh = ", ".join(berkas[:2])
        print(f" - {nama}: {len(berkas)} berkas (mis. {contoh})")
    total = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        for nama, berkas in sorted(rusak.items()):
            try:
                total += _pulihkan(sp, nama, berkas, tmp, python_pip)
            except Exception as e:
                print(f"  {nama}: gagal ({type(e).__name__}: {e})")
    print(f"Selesai: {total} berkas dipulihkan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
