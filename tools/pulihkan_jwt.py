"""Pulihkan paket jwt dari wheel PyJWT yang benar.

Kasus nyata: dua paket berbeda memakai nama modul `jwt` (PyJWT dan paket
lama bernama `jwt`). Ketika perbaikan otomatis menyalin berkas dari paket yang
salah, isinya tercampur dan impor gagal dengan pesan seperti
"cannot import name 'InvalidKeyTypeError'". Skrip ini membuang folder yang
tercampur lalu menyalin ulang hanya dari wheel PyJWT.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import zipfile


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit("pakai: python pulihkan_jwt.py <site-packages> <python-yang-punya-pip>")
    sp = pathlib.Path(sys.argv[1]).resolve()
    python_pip = sys.argv[2]

    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        r = subprocess.run(
            [python_pip, "-m", "pip", "download", "--no-deps", "--only-binary", ":all:",
             "--dest", str(tmp), "PyJWT"],
            capture_output=True, text=True, timeout=300,
        )
        wheel = next((p for p in tmp.glob("*.whl") if p.name.lower().startswith("pyjwt")), None)
        if not wheel:
            print("wheel PyJWT tidak didapat:", r.stderr.strip()[:200])
            return 1

        # Buang folder jwt dan dist-info paket yang salah, supaya tidak ada
        # sisa berkas dari dua versi yang berbeda.
        for d in list(sp.glob("jwt")):
            subprocess.run(["rm", "-rf", str(d)], check=False)
        for d in list(sp.glob("jwt-1.*.dist-info")):
            subprocess.run(["rm", "-rf", str(d)], check=False)

        n = 0
        with zipfile.ZipFile(wheel) as z:
            for entri in z.namelist():
                if entri.endswith("/") or "__pycache__" in entri:
                    continue
                tujuan = sp / entri
                tujuan.parent.mkdir(parents=True, exist_ok=True)
                tujuan.write_bytes(z.read(entri))
                n += 1
        print(f"PyJWT dipulihkan: {n} berkas dari {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
