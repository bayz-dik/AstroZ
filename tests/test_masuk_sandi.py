"""Tes masuk dengan sandi (POST /api/masuk).

Kenapa diuji di berkas sendiri: masuk dengan sandi menggantikan alur "tempel token
panjang" yang dianggap ribet. Dua hal yang mudah salah dan sudah pernah salah di
proyek ini:

1. Sandi diterima di /api/masuk tetapi TIDAK di jalur lain. `_pengguna()` sudah
   lama menerima token aplikasi, sedangkan `/api/masuk` hanya memakai
   `users.verifikasi()`. Akibatnya token aplikasi bekerja lewat header
   Authorization tetapi ditolak saat dipakai masuk dari peramban, dengan pesan
   "token tidak dikenali" padahal tokennya benar.
2. Sandi yang salah harus DITOLAK dengan jelas, dan sandi yang kosong di
   konfigurasi harus berarti "hanya token" (perilaku lama), bukan "semua boleh
   masuk".

Tes ini memanggil fungsi endpointnya langsung, jadi tidak butuh server hidup dan
tidak menyentuh team.yaml asli.
"""
from __future__ import annotations

import asyncio

import pytest

import config
import server
import users


@pytest.fixture()
def cfg_sandi(tmp_path, monkeypatch):
    """Config sementara berisi sandi, tanpa menyentuh team.yaml pengguna."""
    cfg_path = tmp_path / "team.yaml"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(config, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(server, "_TOKEN_APLIKASI", "token-aplikasi-uji-panjang")
    monkeypatch.setattr(users, "_U", {}, raising=False)
    monkeypatch.setattr(users, "_UNDANGAN", {}, raising=False)
    monkeypatch.setattr(server, "_SANDI", "")
    return cfg_path


class _Req:
    """Permintaan tiruan: yang dipakai endpoint hanya header origin."""

    def __init__(self, origin: str = ""):
        self.headers = {"origin": origin} if origin else {}
        self.state = type("S", (), {})()


def _masuk(payload: dict):
    """Memanggil endpoint masuk dan mengembalikan (kode, isi)."""
    r = asyncio.run(server.masuk(payload, _Req()))
    if hasattr(r, "status_code"):
        import json
        return r.status_code, json.loads(bytes(r.body).decode())
    return 200, r


def test_sandi_benar_diterima(cfg_sandi, monkeypatch):
    monkeypatch.setattr(server, "_SANDI", "12345")
    kode, isi = _masuk({"token": "12345"})
    assert kode == 200, isi
    assert isi["ok"] and isi["pengguna"]["peran"] == "admin", isi


def test_sandi_salah_ditolak(cfg_sandi, monkeypatch):
    monkeypatch.setattr(server, "_SANDI", "12345")
    kode, isi = _masuk({"token": "salah"})
    assert kode == 403, isi
    assert not isi["ok"]


def test_tanpa_sandi_hanya_token_yang_diterima(cfg_sandi, monkeypatch):
    """Sandi kosong = perilaku lama. Ini yang menjaga agar tidak ada yang bisa
    masuk hanya dengan mengosongkan kolom."""
    monkeypatch.setattr(server, "_SANDI", "")
    kode, isi = _masuk({"token": ""})
    assert kode == 403, isi
    kode, isi = _masuk({"token": "12345"})
    assert kode == 403, isi


def test_token_aplikasi_tetap_diterima(cfg_sandi, monkeypatch):
    """Jalur aplikasi Android tidak boleh rusak oleh perubahan ini."""
    monkeypatch.setattr(server, "_SANDI", "12345")
    kode, isi = _masuk({"token": "token-aplikasi-uji-panjang"})
    assert kode == 200, isi
    assert isi["pengguna"]["nama"] == "admin", isi


def test_muat_sandi_membaca_config(cfg_sandi):
    cfg_sandi.write_text('gateway:\n  model: uji\nsandi: "rahasia-uji"\n')
    assert server.muat_sandi() == "rahasia-uji"
    assert server.sandi_diatur() is True
    cfg_sandi.write_text('gateway:\n  model: uji\n')
    assert server.muat_sandi() == ""
    assert server.sandi_diatur() is False


# ------------------------------------------------------------ ganti sandi

class _ReqAdmin(_Req):
    """Permintaan tiruan yang lolos pemeriksaan admin.

    `_admin_saja` membaca request.state.pengguna lebih dulu, jadi mengisinya
    sudah cukup -- dan itu memang cara middleware menandai permintaan yang sudah
    terverifikasi. `url` diperlukan karena /api/sandi memeriksa asal permintaan.
    """

    def __init__(self, origin: str = "http://127.0.0.1:8799", peran: str = "admin"):
        super().__init__(origin)
        self.state = type("S", (), {})()
        self.state.pengguna = {"nama": "admin", "peran": peran, "aktif": True}
        self.url = type("U", (), {"hostname": "127.0.0.1", "port": 8799, "scheme": "http"})()


def _ganti_sandi(payload: dict, req=None):
    r = asyncio.run(server.ganti_sandi(payload, req or _ReqAdmin()))
    if hasattr(r, "status_code"):
        import json
        return r.status_code, json.loads(bytes(r.body).decode())
    return 200, r


def test_ganti_sandi_menulis_ke_config(cfg_sandi):
    """Sandi baru harus benar-benar tertulis ke team.yaml dan dipakai server.

    Yang dijaga di sini bukan hanya nilainya, tetapi juga bahwa sandi lama
    TIDAK bisa dipakai masuk sesudahnya. Tanpa pemeriksaan kedua, endpoint bisa
    "berhasil" tanpa mengubah apa pun yang dibaca /api/masuk.
    """
    cfg_sandi.write_text('gateway:\n  model: uji\nsandi: "lama-123"\n')
    monkeypatch_sandi = server.muat_sandi()
    assert monkeypatch_sandi == "lama-123"

    kode, isi = _ganti_sandi({"sandi": "baru-456"})
    assert kode == 200, isi
    assert isi["ok"] is True
    assert server.muat_sandi() == "baru-456"
    assert server.sandi_diatur() is True
    # Berkasnya benar-benar berubah di disk, bukan hanya di memori.
    assert "baru-456" in cfg_sandi.read_text()


def test_ganti_sandi_terlalu_pendek_ditolak(cfg_sandi):
    cfg_sandi.write_text('gateway:\n  model: uji\nsandi: "lama-123"\n')
    server.muat_sandi()
    kode, isi = _ganti_sandi({"sandi": "ab"})
    assert kode == 400, isi
    # Sandi lama harus tetap berlaku kalau penggantinya ditolak.
    assert server.muat_sandi() == "lama-123"


def test_ganti_sandi_bukan_admin_ditolak(cfg_sandi):
    """Pengguna biasa tidak boleh mengganti sandi mesin.

    Tanpa pemeriksaan ini, akun non-admin bisa mengambil alih mesin: sandi
    adalah satu-satunya kunci, dan pemiliknya tidak akan tahu sampai terkunci
    di luar.
    """
    cfg_sandi.write_text('gateway:\n  model: uji\nsandi: "lama-123"\n')
    server.muat_sandi()
    kode, isi = _ganti_sandi({"sandi": "diambil-alih"}, _ReqAdmin(peran="user"))
    assert kode == 403, isi
    assert server.muat_sandi() == "lama-123"


def test_ganti_sandi_dari_situs_lain_ditolak(cfg_sandi):
    """Origin asing harus ditolak, walau permintaannya membawa token admin.

    Situs lain bisa mengirim permintaan atas nama peramban korban; tanpa
    pemeriksaan asal, halaman jahat dapat mengganti sandi lalu mengunci
    pemiliknya keluar dari mesinnya sendiri.
    """
    cfg_sandi.write_text('gateway:\n  model: uji\nsandi: "lama-123"\n')
    server.muat_sandi()
    kode, isi = _ganti_sandi({"sandi": "dari-situs-lain"},
                             _ReqAdmin(origin="http://jahat.example"))
    assert kode == 403, isi
    assert server.muat_sandi() == "lama-123"

