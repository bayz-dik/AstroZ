"""Tes hitungan pemakaian penyimpanan (storage.pemakaian).

Kenapa diuji: fungsi ini dipanggil dari panel Pengaturan, dan versi lamanya
menelusuri folder pengguna TIGA kali (workspace, cadangan, lalu seluruh folder
untuk total -- yang melewati ulang workspace). Di mesin nyata dengan 7.400 entri
satu permintaan memakan puluhan detik, dan karena angka ini dulu dihitung saat
login, SETIAP kali halaman dibuka terasa menggantung.

Tes di sini mengunci empat hal:

  1. angkanya benar (total, workspace, cadangan, dan berkas JSON-nya),
  2. hanya SATU penelusuran per pengguna -- tidak ada folder yang ditelusuri dua
     kali. Yang ini yang mencegah perbaikan kinerjanya dicabut tanpa sadar,
  3. `pathlib.rglob` tidak dipakai lagi. Diukur pada folder admin di mesin ini
     (6.932 berkas, 88 MB): rglob 20 detik, os.scandir 6 detik,
  4. jenis entri ditentukan dari `stat(follow_symlinks=False)`, BUKAN dari
     `Direntry.is_file()`. Di proot ini readdir melaporkan d_type = DT_LNK untuk
     berkas biasa, dan pemeriksaan yang mempercayai d_type menghilangkan 107
     berkas `.git/objects/...` dari hitungan (selisih ~14 MB, tanpa pesan).
"""
from __future__ import annotations

import json
import os

import pytest

import config
import storage


@pytest.fixture()
def akar(tmp_path, monkeypatch):
    """Akar penyimpanan sementara, tanpa menyentuh runtime pengguna asli.

    `folder()` memakai config.RUNTIME, jadi yang diarahkan adalah itu -- bukan
    variabel AKAR yang tidak ada.
    """
    monkeypatch.setattr(config, "RUNTIME", tmp_path)
    return tmp_path / "users"


def _tulis(p, isi: bytes) -> int:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(isi)
    return len(isi)


def test_hitungan_benar(akar):
    d = storage.folder("admin")
    uk_kerja = _tulis(d / "workspace" / "a.txt", b"x" * 100)
    uk_kerja += _tulis(d / "workspace" / "sub" / "b.txt", b"y" * 50)
    uk_cadangan = _tulis(d / "cadangan" / "t1" / "c.txt", b"z" * 30)
    uk_tasks = _tulis(d / "tasks.json", json.dumps([{"id": "t"}]).encode())
    uk_sessions = _tulis(d / "sessions.json", b"[]")
    uk_events = _tulis(d / "events.jsonl", b'{"a":1}\n')

    r = storage.pemakaian(["admin"])["admin"]

    assert r["workspace"] == uk_kerja, r
    assert r["cadangan"] == uk_cadangan, r
    assert r["tasks"] == uk_tasks, r
    assert r["sessions"] == uk_sessions, r
    assert r["events"] == uk_events, r
    # total = seluruh berkas di folder pengguna, termasuk yang di luar workspace
    assert r["total"] == uk_kerja + uk_cadangan + uk_tasks + uk_sessions + uk_events, r
    assert r["berkas"] == 6, r
    assert r["folder"].endswith("admin")


def test_tidak_ada_folder_ditelusuri_dua_kali(akar, monkeypatch):
    """Mengunci perbaikan kinerjanya, bukan cuma hasilnya.

    Versi lama menelusuri workspace, cadangan, lalu seluruh folder pengguna --
    workspace masuk hitungan dua kali. Bentuk itu tidak boleh kembali, jadi yang
    diperiksa di sini bukan jumlah panggilan, melainkan apakah ada folder yang
    di-scandir lebih dari sekali.
    """
    d = storage.folder("admin")
    for i in range(20):
        _tulis(d / "workspace" / f"f{i}.txt", b"x" * 10)
    _tulis(d / "workspace" / "sub" / "g.txt", b"x" * 10)
    _tulis(d / "cadangan" / "t" / "c.txt", b"z" * 5)

    asli = os.scandir
    dipanggil: list[str] = []

    def hitung(path):
        dipanggil.append(os.fspath(path))
        return asli(path)

    monkeypatch.setattr(os, "scandir", hitung)
    storage.pemakaian(["admin"])

    ulang = sorted({p for p in dipanggil if dipanggil.count(p) > 1})
    assert ulang == [], f"folder ditelusuri lebih dari sekali: {ulang}"
    # dan memang ada penelusuran yang terjadi (kalau tidak, tes ini hampa)
    assert any(os.fspath(d) == p for p in dipanggil), dipanggil


def test_rglob_tidak_dipakai(akar, monkeypatch):
    """rglob 3x lebih lambat daripada scandir pada folder besar.

    Dijaga di sini karena bedanya tidak terlihat di tes kecil: satu permintaan
    UI memakan 20 detik di mesin ini, dan itu membuat panel Pengaturan terasa
    rusak.
    """
    import pathlib

    d = storage.folder("admin")
    _tulis(d / "workspace" / "a.txt", b"x" * 10)

    def dilarang(self, *a, **k):
        raise AssertionError(f"rglob dipakai untuk {self}")

    monkeypatch.setattr(pathlib.Path, "rglob", dilarang)
    r = storage.pemakaian(["admin"])["admin"]
    assert r["total"] == 10, r


def test_jenis_entri_dari_lstat_bukan_d_type(akar, monkeypatch):
    """Direntry yang berbohong tentang jenisnya tidak boleh dipercaya.

    Meniru perilaku proot di mesin ini: `readdir` melaporkan d_type = DT_LNK
    untuk berkas BIASA, sehingga `is_file()` menjawab False dan berkas itu
    hilang dari hitungan. Sumber kebenarannya adalah lstat.
    """
    d = storage.folder("admin")
    _tulis(d / "workspace" / ".git" / "objects" / "02" / "abc", b"q" * 77)

    asli = os.scandir

    class Bohong:
        """Pembungkus Direntry: is_file/is_dir/is_symlink selalu salah."""

        def __init__(self, e):
            self._e = e

        def __getattr__(self, nama):
            return getattr(self._e, nama)

        def is_file(self, *a, **k):
            return False

        def is_dir(self, *a, **k):
            return False

        def is_symlink(self, *a, **k):
            return True

    class It:
        def __init__(self, it):
            self._it = it

        def __iter__(self):
            return (Bohong(e) for e in self._it)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(os, "scandir", lambda p: It(asli(p)))
    r = storage.pemakaian(["admin"])["admin"]
    assert r["total"] == 77, r
    assert r["berkas"] == 1, r


def test_pengguna_tanpa_folder_tidak_error(akar):
    r = storage.pemakaian(["belum-ada"])["belum-ada"]
    assert r["total"] == 0 and r["workspace"] == 0 and r["cadangan"] == 0
    assert r["berkas"] == 0


def test_symlink_tidak_dihitung(akar):
    """Symlink tidak diikuti: kalau diikuti, satu tautan ke folder besar bisa
    membuat hitungannya jauh lebih besar dari isi sebenarnya."""
    d = storage.folder("admin")
    _tulis(d / "workspace" / "nyata.txt", b"x" * 40)
    luar = akar / "luar.txt"
    _tulis(luar, b"y" * 999)
    try:
        (d / "workspace" / "tautan.txt").symlink_to(luar)
    except (OSError, NotImplementedError):
        pytest.skip("sistem ini tidak mendukung symlink")

    r = storage.pemakaian(["admin"])["admin"]
    assert r["workspace"] == 40, r
    assert r["berkas"] == 1, r
