"""Klaim berkas sebelum dispatch, dan deteksi tabrakan sesudahnya.

Dua lapis ini ada karena mode "Besar" dulu hanya DIKATAKAN paralel: tidak ada
mekanisme yang mencegah dua pekerja menulis berkas yang sama, dan tidak ada yang
memeriksa hasilnya sesudah mereka selesai. Tes di sini menguji tiga hal yang
mudah salah dan mahal akibatnya: pembacaan daftar berkas dari jawaban model,
penyusunan batch, dan pemulihan berkas yang bentrok dari salinan di luar folder
kerja. Semuanya diuji tanpa CLI pekerja dan tanpa model, jadi hasilnya tidak
bergantung pada gateway yang hidup.
"""
from __future__ import annotations

import pathlib
import subprocess

import hub
import orchestrator
import project


def _repo(d: pathlib.Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(d), check=True)
    subprocess.run(["git", "config", "user.email", "uji@local"], cwd=str(d), check=True)
    subprocess.run(["git", "config", "user.name", "Uji"], cwd=str(d), check=True)


# ------------------------------------------------- membaca daftar berkas
def test_daftar_berkas_berlabel_dibaca():
    """Baris `BERKAS:` adalah daftar yang disengaja, jadi isinya dipakai apa adanya."""
    teks = "Berkas yang akan saya ubah:\nBERKAS: src/a.py, src/b.py\n"
    assert orchestrator.berkas_diklaim(teks, 12) == ["src/a.py", "src/b.py"]


def test_daftar_butir_dibaca():
    teks = "Saya akan mengubah:\n- app/main.py\n- app/util.py\n"
    assert orchestrator.berkas_diklaim(teks, 12) == ["app/main.py", "app/util.py"]


def test_jalur_dinormalkan_supaya_dua_klaim_bisa_dibandingkan():
    """Jalur absolut dan berawalan ./ harus jadi bentuk yang sama.

    Tanpa normalisasi, dua klaim atas berkas yang sama terlihat berbeda dan
    Lapis 1 meloloskannya ke batch yang sama.
    """
    assert orchestrator._normalisasi_jalur("/root/AstroZ/workspace/src/a.py") == "src/a.py"
    assert orchestrator._normalisasi_jalur("./src/a.py") == "src/a.py"
    assert orchestrator._normalisasi_jalur("src/a.py.") == "src/a.py"


def test_kalimat_bukan_klaim_berkas():
    """Model yang menjawab dengan kalimat tidak boleh menghasilkan klaim palsu."""
    klaim = orchestrator.berkas_diklaim("Saya belum tahu berkas mana yang perlu diubah.", 12)
    assert klaim == [] or all(" " not in k for k in klaim)


def test_tebakan_dibatasi_lebih_ketat_daripada_daftar():
    """Tanpa daftar yang disengaja, jumlah jalur yang ditebak dibatasi.

    Klaim yang terlalu luas membuat semua tugas beririsan dan seluruh tugas
    dikerjakan gantian tanpa perlu.
    """
    teks = " ".join(f"berkas{i}.py" for i in range(20))
    assert len(orchestrator.berkas_diklaim(teks, 12, maks_tebak=3)) == 3


# ------------------------------------------------- penyusunan batch (Lapis 1)
def test_klaim_beririsan_tidak_sebatch():
    """Dua tugas yang menyentuh berkas sama tidak boleh dilepas bareng."""
    items = [
        {"klaim": ["a.py"], "_pekerja": "omp"},
        {"klaim": ["a.py"], "_pekerja": "codex"},
    ]
    batch = orchestrator._pembagian_klaim(items, 3)
    assert len(batch) == 2
    assert all(len(b) == 1 for b in batch)


def test_klaim_berbeda_tetap_paralel():
    """Tugas yang tidak beririsan tetap satu batch: parallelismenya tidak dikorbankan."""
    items = [
        {"klaim": ["a.py"], "_pekerja": "omp"},
        {"klaim": ["b.py"], "_pekerja": "codex"},
    ]
    batch = orchestrator._pembagian_klaim(items, 3)
    assert len(batch) == 1
    assert len(batch[0]) == 2


def test_klaim_kosong_tidak_mengunci_semua_orang():
    """Tugas tanpa klaim tidak otomatis dianggap bentrok dengan semua.

    Kalau klaim kosong dianggap beririsan dengan segalanya, satu pekerja yang
    gagal menjawab pertanyaan berkas membuat seluruh tugas berjalan gantian.
    """
    items = [
        {"klaim": [], "_pekerja": "omp"},
        {"klaim": ["b.py"], "_pekerja": "codex"},
        {"klaim": ["c.py"], "_pekerja": "claude"},
    ]
    batch = orchestrator._pembagian_klaim(items, 3)
    assert len(batch) == 1
    assert len(batch[0]) == 3


def test_batas_paralel_dihormati():
    items = [{"klaim": [f"{i}.py"], "_pekerja": f"w{i}"} for i in range(4)]
    batch = orchestrator._pembagian_klaim(items, 2)
    assert [len(b) for b in batch] == [2, 2]


# ------------------------------------------------- sidik jari berkas
def test_snap_menangkap_perubahan_dan_penghapusan(folder_kerja):
    (folder_kerja / "ada.txt").write_text("awal\n")
    (folder_kerja / "hilang.txt").write_text("akan dihapus\n")
    awal = project.snap_berkas()
    (folder_kerja / "ada.txt").write_text("berubah\n")
    (folder_kerja / "hilang.txt").unlink()
    (folder_kerja / "baru.txt").write_text("baru\n")
    beda = project.beda_snap(awal, project.snap_berkas())
    assert beda["diubah"] == ["ada.txt"]
    assert beda["dihapus"] == ["hilang.txt"]
    assert beda["dibuat"] == ["baru.txt"]


def test_snap_menyembunyikan_folder_sampah(folder_kerja):
    """node_modules dan kawan-kawan tidak boleh ikut disidik jari."""
    sampah = folder_kerja / "node_modules" / "paket"
    sampah.mkdir(parents=True)
    (sampah / "besar.js").write_text("x" * 100)
    (folder_kerja / ".gitkeep").write_text("")
    assert project.snap_berkas()["berkas"] == {}


# ------------------------------------------------- pemulihan berkas (Lapis 2)
def test_berkas_bentrok_dikembalikan_dan_berkas_baru_dihapus(folder_kerja):
    """Inti Lapis 2: hasil campur dua pekerja dibuang, bukan dipakai.

    Berkas yang sudah ada dikembalikan isinya, dan berkas yang tadi dibuat dari
    nol dihapus. Salinannya dibaca dari luar folder kerja, jadi berkas hasil
    pekerja tidak perlu disimpan di dalam folder kerja itu sendiri.
    """
    (folder_kerja / "lama.txt").write_text("isi asli\n")
    awal = project.snap_berkas()
    cadangan = project.snap_sementara(["lama.txt"], tag="uji")
    assert cadangan is not None

    # Beginilah kerusakan yang mau dicegah: dua pekerja menulis ke berkas yang
    # sama, dan satu berkas baru yang tidak diklaim siapa pun.
    (folder_kerja / "lama.txt").write_text("hasil pekerja A\nhasil pekerja B\n")
    (folder_kerja / "nyasar.txt").write_text("dibuat pekerja tanpa klaim\n")

    hasil = project.pulihkan_berkas(["lama.txt", "nyasar.txt"], cadangan, awal)
    assert (folder_kerja / "lama.txt").read_text() == "isi asli\n"
    assert not (folder_kerja / "nyasar.txt").exists()
    assert "lama.txt" in hasil["kembali"]
    assert "nyasar.txt" in hasil["dihapus"]


def test_cadangan_tidak_ditaruh_di_folder_kerja(folder_kerja):
    """Salinan cadangan harus di luar folder kerja.

    Kalau ditaruh di dalam, berkas cadangan terbaca sebagai perubahan tugas oleh
    panel berkas, ringkasan, dan penilai.
    """
    (folder_kerja / "a.txt").write_text("isi\n")
    project.snap_sementara(["a.txt"], tag="uji-luar")
    assert project.snap_berkas()["berkas"].keys() == {"a.txt"}


def test_pemulihan_menolak_jalur_keluar_folder(folder_kerja, tmp_path):
    """Jalur yang keluar dari folder kerja tidak boleh menyentuh berkas lain."""
    luar = tmp_path / "rahasia.txt"
    luar.write_text("jangan disentuh\n")
    awal = project.snap_berkas()
    hasil = project.pulihkan_berkas(["../rahasia.txt"], tmp_path / "cadangan", awal)
    assert luar.read_text() == "jangan disentuh\n"
    assert hasil["gagal"] == ["../rahasia.txt"]


# ------------------------------------------------- deteksi tabrakan
class _Kerja:
    """Orkestrator tanpa gateway: hanya bagian klaim yang diuji di sini."""

    def __init__(self) -> None:
        self.cfg = {"workflow": {"auto_commit": True}}

    _cek_bentrok = orchestrator.Orchestrator._cek_bentrok

    def _worker_prompt(self, *a, **k) -> dict:  # pragma: no cover - selalu ditimpa tes
        raise AssertionError("_worker_prompt harus ditimpa di tes ini")


def _hasil(pekerja: str, klaim: list[str], prompt: str = "kerjakan") -> dict:
    return {"worker": pekerja, "_pekerja": pekerja, "klaim": klaim, "ok": True,
            "text": "selesai", "_prompt": prompt}


def _cek_bentrok_untuk_tes(monkeypatch, o, jawab=None):
    """Jalankan _cek_bentrok dengan _worker_prompt palsu, catat yang dipanggil."""
    dipanggil: list[str] = []

    def palsu(w, p, t, c, m, **k):
        dipanggil.append(w)
        return _hasil(w, (jawab or {}).get(w, ["bersama.py"]))

    monkeypatch.setattr(o, "_worker_prompt", palsu)
    return dipanggil


def _kejadian(teks: str) -> list[dict]:
    return [e for e in hub.recent(300) if teks in (e.get("text") or "")]


def test_dua_pekerja_menulis_berkas_yang_sama_dipulihkan_dan_diulang(folder_kerja, monkeypatch):
    """Berkas yang diklaim DUA tugas dan berubah: dikembalikan, lalu diulang gantian.

    Yang harus terbukti: isi berkas kembali seperti sebelum batch, hasil paralel
    yang bentrok dibuang (bukan dipakai untuk tes dan penilaian), dan kedua
    pekerja dijalankan ulang satu per satu.
    """
    monkeypatch.setattr(project, "project_dir", lambda: folder_kerja)
    (folder_kerja / "bersama.py").write_text("awal\n")
    snap = project.snap_berkas()
    # Salinan diambil sebelum batch berjalan, seperti di orkestrator.
    cadangan = project.snap_sementara(["bersama.py"], tag="t1")
    (folder_kerja / "bersama.py").write_text("ditulis dua pekerja\n")

    o = _Kerja()
    dipanggil = _cek_bentrok_untuk_tes(monkeypatch, o)
    hasil = [_hasil("omp", ["bersama.py"]), _hasil("codex", ["bersama.py"])]
    keluar = o._cek_bentrok("t1", hasil, snap, set(), folder_kerja, o.cfg, set(), 0, "m", [], cadangan)

    assert (folder_kerja / "bersama.py").read_text() == "awal\n"
    assert sorted(dipanggil) == ["codex", "omp"], "kedua pekerja harus dijalankan ulang"
    assert len(keluar) == 2 and all(r.get("ok") for r in keluar)
    assert not any(r.get("bentrok") for r in keluar), "hasil gantian tidak boleh ditandai bentrok"
    assert _kejadian("Hasil paralel dibuang"), "pembuangan hasil harus tercatat"
    assert _kejadian("Tabrakan berkas terdeteksi")


def test_berkas_milik_satu_pekerja_bukan_tabrakan(folder_kerja, monkeypatch):
    """Berkas yang jelas milik satu pekerja tidak menuduh siapa pun."""
    monkeypatch.setattr(project, "project_dir", lambda: folder_kerja)
    (folder_kerja / "milikku.py").write_text("awal\n")
    snap = project.snap_berkas()
    cadangan = project.snap_sementara(["milikku.py"], tag="t2")
    (folder_kerja / "milikku.py").write_text("hasil kerja omp\n")

    o = _Kerja()
    dipanggil = _cek_bentrok_untuk_tes(monkeypatch, o)
    hasil = [_hasil("omp", ["milikku.py"]), _hasil("codex", ["lain.py"])]
    keluar = o._cek_bentrok("t2", hasil, snap, set(), folder_kerja, o.cfg, set(), 0, "m", [], cadangan)
    assert keluar == hasil
    assert dipanggil == [], "tidak ada yang perlu dijalankan ulang"
    assert (folder_kerja / "milikku.py").read_text() == "hasil kerja omp\n"


def test_pekerja_tanpa_klaim_yang_menulis_berkas_orang_lain_terdeteksi(folder_kerja, monkeypatch):
    """Klaim kosong berarti bisa menyentuh apa saja.

    Tanpa aturan ini, pekerja yang gagal menjawab pertanyaan berkas lalu menulis
    ke berkas milik pekerja lain justru lolos: berkas itu terlihat diklaim satu
    orang, padahal ada dua yang menulis.
    """
    monkeypatch.setattr(project, "project_dir", lambda: folder_kerja)
    (folder_kerja / "punyaku.py").write_text("awal\n")
    snap = project.snap_berkas()
    cadangan = project.snap_sementara(["punyaku.py"], tag="t3")
    (folder_kerja / "punyaku.py").write_text("ditulis dua orang\n")

    o = _Kerja()
    dipanggil = _cek_bentrok_untuk_tes(monkeypatch, o, {"omp": ["punyaku.py"], "codex": []})
    hasil = [_hasil("omp", ["punyaku.py"]), _hasil("codex", [])]
    o._cek_bentrok("t3", hasil, snap, set(), folder_kerja, o.cfg, set(), 0, "m", [], cadangan)
    assert (folder_kerja / "punyaku.py").read_text() == "awal\n"
    assert sorted(dipanggil) == ["codex", "omp"]


def test_berkas_setelan_tidak_menuduh_pekerja(folder_kerja, monkeypatch):
    """team.yaml berubah bukan alasan menjalankan ulang pekerja mana pun."""
    monkeypatch.setattr(project, "project_dir", lambda: folder_kerja)
    (folder_kerja / "team.yaml").write_text("gateway: {}\n")
    snap = project.snap_berkas()
    (folder_kerja / "team.yaml").write_text("gateway: {model: lain}\n")

    o = _Kerja()
    dipanggil = _cek_bentrok_untuk_tes(monkeypatch, o, {"omp": [], "codex": []})
    hasil = [_hasil("omp", []), _hasil("codex", [])]
    keluar = o._cek_bentrok("t4", hasil, snap, set(), folder_kerja, o.cfg, set(), 0, "m",
                            orchestrator.klaim_aman({"workflow": {"berkas_aman": ["team.yaml"]}}),
                            None)
    assert keluar == hasil
    assert dipanggil == []
    assert _kejadian("Berkas setelan berubah"), "perubahan berkas setelan harus tetap terlihat"


def test_berkas_yang_sudah_dipulihkan_tidak_menuduh_lagi(folder_kerja, monkeypatch):
    """Sesudah dipulihkan sekali, berkas itu tidak dihitung dua kali.

    Ini yang membuat pengulangan terbatas, bukan berputar selamanya.
    """
    monkeypatch.setattr(project, "project_dir", lambda: folder_kerja)
    (folder_kerja / "sama.py").write_text("awal\n")
    snap = project.snap_berkas()
    (folder_kerja / "sama.py").write_text("ditulis dua orang\n")

    o = _Kerja()
    dipanggil = _cek_bentrok_untuk_tes(monkeypatch, o)
    hasil = [_hasil("omp", ["sama.py"]), _hasil("codex", ["sama.py"])]
    keluar = o._cek_bentrok("t5", hasil, snap, set(), folder_kerja, o.cfg, {"sama.py"}, 0, "m", [], None)
    assert keluar == hasil
    assert dipanggil == []


def test_pengulangan_bersarang_dihentikan(folder_kerja, monkeypatch):
    """Hasil gantian yang masih bentrok tidak diulang tanpa batas.

    Yang diuji: pemulihan tetap dilakukan (folder kerja bersih), hasilnya
    ditandai bentrok, dan tidak ada pengulangan baru dijadwalkan.
    """
    monkeypatch.setattr(project, "project_dir", lambda: folder_kerja)
    (folder_kerja / "sama.py").write_text("awal\n")
    snap = project.snap_berkas()
    cadangan = project.snap_sementara(["sama.py"], tag="t6")
    (folder_kerja / "sama.py").write_text("masih bentrok\n")

    o = _Kerja()
    dipanggil = _cek_bentrok_untuk_tes(monkeypatch, o)
    hasil = [_hasil("omp", ["sama.py"]), _hasil("codex", ["sama.py"])]
    keluar = o._cek_bentrok("t6", hasil, snap, set(), folder_kerja, o.cfg, set(), 1, "m", [], cadangan)
    assert dipanggil == [], "pengulangan bersarang harus berhenti di sini"
    assert all(r.get("bentrok") for r in keluar)
    assert (folder_kerja / "sama.py").read_text() == "awal\n"
    assert _kejadian("Lapis 3")


def test_tanpa_salinan_isi_lama_tidak_dikembalikan_dan_dilaporkan(folder_kerja, monkeypatch):
    """Kalau salinan sebelum batch tidak ada, itu dilaporkan, bukan didiamkan.

    Mengambil salinan sesudah pekerja selesai hanya akan menyalin isi yang sudah
    rusak. Jadi ketiadaan salinan adalah kegagalan penjagaan dan harus terlihat.
    """
    monkeypatch.setattr(project, "project_dir", lambda: folder_kerja)
    (folder_kerja / "sama.py").write_text("awal\n")
    snap = project.snap_berkas()
    (folder_kerja / "sama.py").write_text("rusak\n")

    o = _Kerja()
    _cek_bentrok_untuk_tes(monkeypatch, o)
    hasil = [_hasil("omp", ["sama.py"]), _hasil("codex", ["sama.py"])]
    o._cek_bentrok("t7", hasil, snap, set(), folder_kerja, o.cfg, set(), 0, "m", [], None)
    assert _kejadian("Tidak ada salinan sebelum batch"), "kegagalan salinan harus tercatat"


# ------------------------------------------------- kunci berkas (Lapis 3)
def test_pegang_berkas_semua_atau_tidak_sama_sekali():
    """Pegang sebagian lalu gagal membuat dua pekerja merasa berhak."""
    hub.lepas_berkas(list(hub.pegang_siapa()), "omp")
    hub.lepas_berkas(list(hub.pegang_siapa()), "codex")
    assert hub.pegang_berkas(["a.py", "b.py"], "omp")["ok"] is True
    hasil = hub.pegang_berkas(["b.py", "c.py"], "codex")
    assert hasil["ok"] is False
    assert hasil["bentrok"] == {"b.py": "omp"}
    # c.py tidak boleh ikut dipegang codex setelah permintaannya ditolak.
    assert hub.pegang_siapa().get("c.py") is None


def test_lepas_berkas_tidak_menyentuh_milik_pekerja_lain():
    hub.lepas_berkas(list(hub.pegang_siapa()), "omp")
    hub.lepas_berkas(list(hub.pegang_siapa()), "codex")
    hub.pegang_berkas(["d.py"], "omp")
    assert hub.lepas_berkas(["d.py"], "codex") == []
    assert hub.pegang_siapa()["d.py"] == "omp"
    assert hub.lepas_berkas(["d.py"], "omp") == ["d.py"]
    assert "d.py" not in hub.pegang_siapa()


# ------------------------------------------------- tetap seperti sekarang
def test_commit_tetap_menunggu_tes_dan_penilaian_lulus():
    """auto_commit tidak boleh ikut berubah karena Lapis 1 dan 2.

    Lapis 2 hanya mengembalikan berkas; keputusan commit tetap milik
    _task_is_green (tes lulus + penilaian PASS).
    """
    o = orchestrator.Orchestrator.__new__(orchestrator.Orchestrator)
    assert o._task_is_green({"ok": True}, {"verdict": "PASS"}) is True
    assert o._task_is_green({"ok": False}, {"verdict": "PASS"}) is False
    assert o._task_is_green({"ok": True}, {"verdict": "FAIL"}) is False
    assert o._task_is_green(None, None) is False
