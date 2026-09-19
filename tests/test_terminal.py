"""Tes terminal: lingkungan yang diberikan ke perintah pengguna.

Yang diuji di sini bukan "endpoint menjawab 200", tetapi sifat lingkungan yang
sudah dua kali membuat terminal mati di perangkat:

1. Variabel Python milik proses aplikasi bocor ke perintah pengguna.

   Server AstroZ berjalan di dalam proses Python Chaquopy (3.13). `os.environ`
   proses itu memuat PYTHONPATH/PYTHONHOME yang menunjuk stdlib Chaquopy berbentuk
   zip. Kalau variabel itu diteruskan, Python CLI dari aset (3.14) membaca zip
   stdlib 3.13 dan mati sebelum menjalankan apa pun:

     Fatal Python error: Failed to import encodings module
     zipimport.ZipImportError: module load failed: bad magic number in
       'encodings': b'\\xf3\\r\\r\\n'

   Byte \\xf3\\r\\r\\n adalah magic Python 3.13. PYTHONHOME pernah dibuang untuk
   alasan yang sama; PYTHONPATH terlewat dan gejalanya kambuh.

2. Pustaka terminal harus memakai prefix milik aplikasi, dan variabel yang
   dibutuhkan biner Termux (LD_LIBRARY_PATH) tidak boleh hilang.

Tes ini tidak butuh aset terminal: yang diperiksa adalah bentuk lingkungan.
"""
from __future__ import annotations

import os

import pytest

import terminal


@pytest.fixture()
def env_tercemar(monkeypatch):
    """Meniru proses aplikasi: os.environ memuat variabel Python Chaquopy."""
    monkeypatch.setenv("PYTHONPATH", "/data/user/0/id.astroz.app/files/chaquopy/lib/python313.zip")
    monkeypatch.setenv("PYTHONHOME", "/data/user/0/id.astroz.app/files/chaquopy")
    monkeypatch.setenv("PYTHONSTARTUP", "/data/user/0/id.astroz.app/files/chaquopy/startup.py")
    return os.environ


def test_pythonpath_chaquopy_tidak_diwariskan(env_tercemar):
    e = terminal.env()
    for k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONEXECUTABLE"):
        assert k not in e, f"{k} bocor ke perintah pengguna: {e.get(k)}"


def test_pythonsafepath_dinyalakan(env_tercemar):
    """Tanpa ini, folder skrip masuk sys.path dan modul di folder kerja bisa
    menutupi modul stdlib dengan nama yang sama."""
    assert terminal.env().get("PYTHONSAFEPATH") == "1"


def test_ld_library_path_ada_saat_prefix_ditemukan():
    """Biner Termux (busybox, git, python) gagal memuat pustakanya tanpa ini:
    'CANNOT LINK EXECUTABLE: library libbusybox.so.1.38.0 not found'."""
    p = terminal.prefix()
    if p is None:
        pytest.skip("aset terminal tidak ada di mesin ini")
    e = terminal.env()
    assert e.get("LD_LIBRARY_PATH", "").startswith(str(p / "lib"))
    assert e.get("PREFIX") == str(p)


def test_terminfo_diarahkan_ke_prefix():
    """clear, less, vi, dan curses gagal tanpa basis data terminfo."""
    p = terminal.prefix()
    if p is None or not (p / "share/terminfo").is_dir():
        pytest.skip("terminfo belum ada di aset")
    assert terminal.env().get("TERMINFO") == str(p / "share/terminfo")


def test_python_benar_benar_berjalan_walau_env_aplikasi_tercemar(env_tercemar, tmp_path):
    """Uji ujung ke ujung: jalankan python3 SUNGGUHAN dari prefix aset.

    Ini yang membuktikan perbaikannya, bukan sekadar bentuk dict env. Di
    perangkat, kegagalannya muncul persis seperti ini:

        Fatal Python error: Failed to import encodings module
        zipimport.ZipImportError: module load failed: bad magic number in
          'encodings': b'\\xf3\\r\\r\\n'

    PYTHONPATH di fixture menunjuk jalur zip yang tidak ada; yang penting adalah
    variabelnya TIDAK diteruskan, karena di perangkat jalur itu benar-benar ada
    dan berisi stdlib Python 3.13 milik Chaquopy.
    """
    p = terminal.prefix()
    if p is None or not (p / "bin/python3.14").is_file():
        pytest.skip("Python CLI belum ada di aset")
    # Folder kerja dipindah ke tmp supaya tes tidak menulis ke runtime asli.
    monkey = tmp_path / "kerja"
    monkey.mkdir()
    import config
    asli = config.RUNTIME
    config.RUNTIME = tmp_path / "runtime"
    try:
        hasil = terminal.jalankan("python3 -c \"print(6*7)\"", owner="uji", cwd=str(monkey))
    finally:
        config.RUNTIME = asli
    assert "42" in hasil.get("keluaran", ""), hasil
    assert hasil.get("ok"), hasil
