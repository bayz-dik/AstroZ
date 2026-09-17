"""Akun dan pemisahan antar pengguna.

Yang diuji di sini adalah batas antar pengguna: percakapan, tugas, dan folder
kerja. Ini bagian yang paling mudah salah dan paling mahal akibatnya, karena
kesalahannya tidak terlihat sampai ada orang lain yang membuka UI.

Folder rumah dialihkan ke tmp_path supaya tes tidak menyentuh akun asli di
runtime/ milik mesin ini.
"""
from __future__ import annotations

import json

import pytest

import config
import sessions
import users


@pytest.fixture
def bersih(tmp_path, monkeypatch):
    """Runtime bersih di tmp_path: akun, sesi, dan folder kerja terpisah."""
    rt = tmp_path / "runtime"
    rt.mkdir(parents=True)
    monkeypatch.setattr(config, "RUNTIME", rt)
    monkeypatch.setattr(sessions, "SESSIONS_FILE", rt / "sessions.json")
    users._U.clear()
    sessions._S.clear()
    yield rt
    # Keadaan modul dikembalikan: kalau tidak, tes berikutnya mewarisi akun uji
    # dan menulisnya ke runtime milik mesin ini.
    users._U.clear()
    sessions._S.clear()


# ------------------------------------------------------------------ akun

def test_admin_pertama_dibuat_dengan_token(bersih):
    a = users.siapkan_pertama()
    assert a["nama"] == "admin"
    assert a["peran"] == "admin"
    assert len(a["token"]) >= 32
    # Token tidak disimpan dalam bentuk asli, hanya sidik jarinya.
    isi = (bersih / "users.json").read_text()
    assert a["token"] not in isi
    # Dan memang tertulis di runtime sementara, bukan runtime mesin ini.
    assert (bersih / "users.json").exists()


def test_token_pertama_ditulis_ke_berkas_bukan_feed(bersih):
    """Token harus terbaca pemilik mesin, tetapi tidak lewat UI."""
    a = users.siapkan_pertama()
    f = bersih / "admin_token.txt"
    assert f.exists()
    assert a["token"] in f.read_text()
    # Berkasnya hanya boleh dibaca pemilik.
    assert oct(f.stat().st_mode)[-3:] == "600"


def test_verifikasi_token(bersih):
    a = users.siapkan_pertama()
    u = users.verifikasi(a["token"])
    assert u and u["nama"] == "admin"
    assert users.verifikasi("token-palsu") is None
    assert users.verifikasi("") is None


def test_hasil_verifikasi_tidak_membawa_sidik_jari(bersih):
    a = users.siapkan_pertama()
    u = users.verifikasi(a["token"])
    assert "sidik" not in u
    assert "garam" not in u


def test_buat_akun_dan_token_sekali(bersih):
    users.siapkan_pertama()
    u = users.buat("budi", "user")
    assert u["peran"] == "user"
    assert users.verifikasi(u["token"])["nama"] == "budi"
    # Nama tidak boleh dipakai dua kali.
    with pytest.raises(ValueError):
        users.buat("budi", "user")


def test_nama_akun_dibatasi(bersih):
    users.siapkan_pertama()
    for jelek in ("", "a", "Ada Spasi", "tanda!", "../keluar", "../../etc", "x" * 40):
        with pytest.raises(ValueError):
            users.buat(jelek, "user")


def test_nama_akun_huruf_besar_dinormalkan(bersih):
    """Nama diketik apa saja, tetapi disimpan huruf kecil supaya konsisten.

    Ini disengaja: pemilik mesin mengetik "Budi" dan tetap bisa masuk sebagai
    "budi", tanpa dua akun yang tampak sama.
    """
    users.siapkan_pertama()
    u = users.buat("Budi", "user")
    assert u["nama"] == "budi"
    assert users.verifikasi(u["token"])["nama"] == "budi"
    # Yang sama tidak bisa dibuat dua kali walau beda huruf besar-kecil.
    with pytest.raises(ValueError):
        users.buat("BUDI", "user")


def test_token_baru_mematikan_yang_lama(bersih):
    users.siapkan_pertama()
    u = users.buat("budi", "user")
    baru = users.setel_ulang_token("budi")
    assert users.verifikasi(u["token"]) is None
    assert users.verifikasi(baru["token"])["nama"] == "budi"


def test_akun_mati_tidak_bisa_masuk(bersih):
    users.siapkan_pertama()
    u = users.buat("budi", "user")
    users.setel_aktif("budi", False)
    assert users.verifikasi(u["token"]) is None


def test_admin_terakhir_tidak_bisa_dihapus_atau_dimatikan(bersih):
    """Kalau ini lolos, tidak ada lagi yang bisa mengelola akun dan kunci API."""
    users.siapkan_pertama()
    with pytest.raises(ValueError):
        users.setel_aktif("admin", False)
    with pytest.raises(ValueError):
        users.hapus("admin")


def test_admin_kedua_membuat_yang_pertama_boleh_dihapus(bersih):
    users.siapkan_pertama()
    users.buat("admin2", "admin")
    assert users.hapus("admin")["dihapus"] is True


# ------------------------------------------------------------------ sesi

def test_sesi_punya_pemilik(bersih):
    s = sessions.create("punya budi", owner="budi")
    assert s["owner"] == "budi"


def test_sesi_lama_dibaca_milik_admin(bersih):
    """Percakapan yang sudah ada sebelum pemisahan tidak boleh hilang."""
    (bersih / "sessions.json").write_text(json.dumps([
        {"id": "lama123", "title": "Percakapan lama", "created": 1, "updated": 1, "tasks": []}
    ]))
    sessions._S.clear()
    sessions.load()
    s = sessions.get("lama123")
    assert s["owner"] == "admin"


def test_get_milik_menolak_pemilik_lain(bersih):
    sessions.create("punya budi", owner="budi")
    sid = sessions.list_sessions("budi")[0]["id"]
    assert sessions.get_milik(sid, "budi") is not None
    assert sessions.get_milik(sid, "ani") is None


def test_ensure_membuat_sesi_baru_kalau_sid_milik_orang_lain(bersih):
    """Menebak id sesi orang lain tidak boleh memberi akses ke isinya."""
    s_budi = sessions.create("punya budi", owner="budi")
    s_ani = sessions.ensure(s_budi["id"], "halo", owner="ani")
    assert s_ani["id"] != s_budi["id"]
    assert s_ani["owner"] == "ani"


def test_daftar_sesi_menyaring_pemilik(bersih):
    sessions.create("budi", owner="budi")
    sessions.create("ani", owner="ani")
    assert [s["title"] for s in sessions.list_sessions("budi")] == ["budi"]
    assert len(sessions.list_sessions(None)) == 2


def test_hapus_dan_ganti_nama_menghormati_pemilik(bersih):
    s = sessions.create("punya budi", owner="budi")
    assert sessions.rename(s["id"], "dibajak", owner="ani") is None
    assert sessions.delete(s["id"], owner="ani") is False
    assert sessions.get(s["id"])["title"] == "punya budi"
    assert sessions.rename(s["id"], "punya budi sendiri", owner="budi") is not None
    assert sessions.delete(s["id"], owner="budi") is True


def test_sematkan_menghormati_pemilik(bersih):
    s = sessions.create("punya budi", owner="budi")
    assert sessions.toggle_pin(s["id"], True, owner="ani") is None
    assert sessions.toggle_pin(s["id"], True, owner="budi")["pinned"] is True


# ------------------------------------------------------------------ folder kerja

def test_admin_memakai_folder_kerja_yang_sudah_ada(bersih, monkeypatch):
    """Pekerjaan lama tidak boleh berpindah tempat."""
    monkeypatch.setattr(config, "CONFIG_PATH", bersih / "team.yaml")
    users.siapkan_pertama()
    lama = config.load()["project_dir"]
    assert str(users.ruang_kerja("admin")) == lama


def test_pengguna_biasa_dapat_folder_sendiri(bersih):
    users.siapkan_pertama()
    users.buat("budi", "user")
    users.buat("ani", "user")
    b = users.ruang_kerja("budi")
    a = users.ruang_kerja("ani")
    assert b != a
    assert "budi" in str(b)
    assert "ani" in str(a)
    # Foldernya di dalam runtime, bukan di dalam repo.
    assert str(b).startswith(str(bersih))


def test_ruang_kerja_tidak_keluar_dari_runtime(bersih):
    """Nama akun sudah dibatasi, tetapi jalurnya tetap diperiksa."""
    users.siapkan_pertama()
    users.buat("budi", "user")
    p = users.ruang_kerja("budi").resolve()
    assert str(p).startswith(str(bersih.resolve()))
