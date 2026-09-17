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
    """Runtime bersih di tmp_path: akun, sesi, dan folder kerja terpisah.

    Penyimpanan sekarang per pengguna (storage.py), jadi cukup memindahkan
    config.RUNTIME: semua jalur di bawahnya ikut pindah karena storage menghitung
    jalurnya saat dipakai, bukan saat impor.
    """
    rt = tmp_path / "runtime"
    rt.mkdir(parents=True)
    monkeypatch.setattr(config, "RUNTIME", rt)
    users._U.clear()
    users._UNDANGAN.clear()
    sessions._S.clear()
    yield rt
    # Keadaan modul dikembalikan: kalau tidak, tes berikutnya mewarisi akun uji
    # dan menulisnya ke runtime milik mesin ini.
    users._U.clear()
    users._UNDANGAN.clear()
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
    """Percakapan yang sudah ada sebelum pemisahan tidak boleh hilang.

    Berkas lamanya bersama di akar runtime; sesudah pemisahan ia pindah ke folder
    pemiliknya. Yang diuji di sini adalah jalur pindahannya, bukan sekadar
    pembacaan: tanpa pemindahan, seluruh riwayat percakapan hilang dari UI.
    """
    import storage

    (bersih / "sessions.json").write_text(json.dumps([
        {"id": "lama123", "title": "Percakapan lama", "created": 1, "updated": 1, "tasks": []}
    ]))
    hasil = storage.pindahkan_berkas_lama()
    assert hasil.get("sessions.json", "").startswith("digabung")
    assert not (bersih / "sessions.json").exists()
    assert storage.sessions_file("admin").is_file()

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


# ------------------------------------------------------------------ kode undangan

def test_undangan_sekali_pakai(bersih):
    users.siapkan_pertama()
    k = users.undangan_buat()
    assert len(k["kode"]) == users.KODE_PANJANG
    u = users.undangan_pakai(k["kode"], "ani")
    assert u["nama"] == "ani"
    assert users.verifikasi(u["token"])["nama"] == "ani"
    # Sekali pakai: percobaan kedua harus ditolak.
    with pytest.raises(ValueError):
        users.undangan_pakai(k["kode"], "orang-lain")


def test_undangan_bisa_dipakai_beberapa_orang(bersih):
    users.siapkan_pertama()
    k = users.undangan_buat(maks=3)
    for nama in ("ani", "tono", "wati"):
        assert users.undangan_pakai(k["kode"], nama)["nama"] == nama
    # Habis di pemakaian ketiga.
    with pytest.raises(ValueError):
        users.undangan_pakai(k["kode"], "keempat")


def test_undangan_kedaluwarsa_ditolak(bersih):
    users.siapkan_pertama()
    k = users.undangan_buat(detik=60)
    k["kedaluwarsa"] = 1  # sudah lewat
    with pytest.raises(ValueError):
        users.undangan_pakai(k["kode"], "ani")


def test_undangan_kode_salah_ditolak(bersih):
    users.siapkan_pertama()
    users.undangan_buat()
    for kode in ("", "XXXXXXXY", "salah"):
        with pytest.raises(ValueError):
            users.undangan_pakai(kode, "ani")


def test_undangan_tidak_bisa_membuat_admin(bersih):
    """Undangan admin berarti menyerahkan seluruh kendali mesin."""
    users.siapkan_pertama()
    with pytest.raises(ValueError):
        users.undangan_buat(peran="admin")


def test_undangan_nama_bentrok_ditolak(bersih):
    users.siapkan_pertama()
    users.buat("ani", "user")
    k = users.undangan_buat()
    with pytest.raises(ValueError):
        users.undangan_pakai(k["kode"], "ani")
    # Kode tidak hangus karena percobaan yang gagal: namanya yang salah.
    assert users.undangan_pakai(k["kode"], "tono")["nama"] == "tono"


def test_token_tidak_ikut_tersimpan_ke_disk(bersih):
    """Token asli tidak boleh ada di users.json, hanya sidik jarinya."""
    users.siapkan_pertama()
    k = users.undangan_buat()
    u = users.undangan_pakai(k["kode"], "ani")
    isi = (bersih / "users.json").read_text()
    assert u["token"] not in isi
    assert "_token_sekali" not in isi


def test_undangan_disimpan_dan_dimuat_ulang(bersih):
    """Kode yang masih berlaku harus selamat dari restart server."""
    users.siapkan_pertama()
    k = users.undangan_buat()
    users._UNDANGAN.clear()
    n = users.undangan_load()
    assert n == 1
    assert users.undangan_pakai(k["kode"], "ani")["nama"] == "ani"


def test_undangan_kedaluwarsa_tidak_dimuat(bersih):
    users.siapkan_pertama()
    k = users.undangan_buat(detik=60)
    (bersih / "invites.json").write_text(json.dumps([{**k, "kedaluwarsa": 1}]))
    users._UNDANGAN.clear()
    assert users.undangan_load() == 0


def test_daftar_undangan_hanya_yang_hidup(bersih):
    users.siapkan_pertama()
    a = users.undangan_buat()
    b = users.undangan_buat()
    users.undangan_pakai(b["kode"], "ani")   # b habis (sekali pakai)
    kode = [x["kode"] for x in users.undangan_daftar()]
    assert a["kode"] in kode
    assert b["kode"] not in kode


def test_undangan_hapus(bersih):
    users.siapkan_pertama()
    k = users.undangan_buat()
    assert users.undangan_hapus(k["kode"])["dihapus"] is True
    with pytest.raises(ValueError):
        users.undangan_pakai(k["kode"], "ani")


def test_undangan_pemakai_dapat_folder_sendiri(bersih):
    """Pendaftar lewat undangan harus terpisah seperti akun lain."""
    users.siapkan_pertama()
    k = users.undangan_buat()
    users.undangan_pakai(k["kode"], "ani")
    p = users.ruang_kerja("ani")
    assert "ani" in str(p)
    assert p != users.ruang_kerja("admin")


def test_undangan_bukan_admin(bersih):
    users.siapkan_pertama()
    k = users.undangan_buat()
    u = users.undangan_pakai(k["kode"], "ani")
    assert u["peran"] == "user"
    assert users.peran("ani") == "user"


# ------------------------------------------------------------------ folder kerja

def test_admin_juga_punya_penyimpanan_sendiri(bersih, monkeypatch):
    """Admin pun menanggung storage-nya sendiri.

    Sebelumnya admin memakai folder lama di luar runtime, jadi bebannya tidak
    terhitung bersama pengguna lain. Sekarang semua pengguna, termasuk admin,
    memakai runtime/users/<nama>/, dan folder lama DIPINDAH ke sana supaya
    pekerjaan yang sudah ada tidak hilang.
    """
    import storage

    monkeypatch.setattr(config, "CONFIG_PATH", bersih / "team.yaml")
    users.siapkan_pertama()
    # Folder kerja lama berisi pekerjaan, seperti keadaan sebelum pemisahan.
    lama = bersih / "workspace_lama"
    lama.mkdir(parents=True)
    (lama / "catatan.txt").write_text("pekerjaan lama")
    cfg = config.load()
    cfg["project_dir"] = str(lama)
    config.save(cfg)

    assert storage.pindahkan_workspace_lama() == "dipindah"

    baru = users.ruang_kerja("admin")
    assert baru == storage.workspace("admin")
    assert baru.is_dir()
    assert (baru / "catatan.txt").read_text() == "pekerjaan lama"
    # Pemindahan kedua tidak boleh mengulang atau menimpa.
    assert storage.pindahkan_workspace_lama() != "dipindah"


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


# ------------------------------------------------------------------ pemindahan

def test_pemindahan_menggabung_bukan_menimpa(bersih):
    """Berkas lama DIGABUNG ke penyimpanan admin, tidak ditimpa dan tidak dibuang.

    Kejadian nyata yang membuat aturan ini ada: folder admin sudah berisi berkas
    dari percobaan sebelumnya, dan aturan "lewati kalau tujuan ada" meninggalkan
    riwayat kejadian asli berukuran megabyte di luar penyimpanan pengguna. UI lalu
    hanya menampilkan data percobaan, dan data aslinya tidak pernah terlihat lagi.
    """
    import storage

    # Keadaan tujuan: sudah ada, dari percobaan sebelumnya.
    storage.siapkan("admin")
    storage.tasks_file("admin").write_text(json.dumps([{"id": "t_baru", "owner": "admin"}]))
    storage.sessions_file("admin").write_text(json.dumps([{"id": "s_baru", "owner": "admin"}]))
    storage.events_file("admin").write_text('{"id": 2, "task": "t_baru"}\n')

    # Keadaan sumber: berkas bersama yang lama, berisi riwayat asli.
    (bersih / "tasks.json").write_text(json.dumps([{"id": "t_lama", "owner": "admin"}]))
    (bersih / "sessions.json").write_text(json.dumps([{"id": "s_lama", "owner": "admin"}]))
    (bersih / "events.jsonl").write_text('{"id": 1, "task": "t_lama"}\n')
    (bersih / "cadangan" / "t9").mkdir(parents=True)
    (bersih / "cadangan" / "t9" / "x.txt").write_text("isi")

    hasil = storage.pindahkan_berkas_lama()
    assert hasil["tasks.json"].startswith("digabung")
    assert hasil["sessions.json"].startswith("digabung")
    assert hasil["events.jsonl"] == "digabung"

    # Keduanya ada: yang lama TIDAK hilang, yang baru tidak tertimpa.
    tugas = {t["id"] for t in json.loads(storage.tasks_file("admin").read_text())}
    assert tugas == {"t_baru", "t_lama"}
    sesi = {s["id"] for s in json.loads(storage.sessions_file("admin").read_text())}
    assert sesi == {"s_baru", "s_lama"}
    kejadian = storage.events_file("admin").read_text()
    assert "t_lama" in kejadian and "t_baru" in kejadian

    # Cadangan ikut pindah, dan berkas bersama yang lama sudah tidak ada.
    assert (storage.cadangan_dir("admin") / "t9" / "x.txt").read_text() == "isi"
    assert not (bersih / "tasks.json").exists()
    assert not (bersih / "events.jsonl").exists()
    assert not (bersih / "cadangan").exists()


def test_pemindahan_aman_dijalankan_dua_kali(bersih):
    """Boot kedua tidak boleh menggandakan atau menghapus apa pun."""
    import storage

    (bersih / "tasks.json").write_text(json.dumps([{"id": "t1", "owner": "admin"}]))
    storage.pindahkan_berkas_lama()
    pertama = storage.tasks_file("admin").read_text()
    hasil2 = storage.pindahkan_berkas_lama()
    assert hasil2 == {}
    assert storage.tasks_file("admin").read_text() == pertama
