"""Penyimpanan per pengguna: satu tempat yang menentukan di mana berkas siapa.

Kebutuhan yang dilayani: setiap pengguna menanggung bebannya sendiri. Tidak ada
berkas bersama yang tumbuh karena orang lain bekerja, dan menghapus satu akun
berarti menghapus satu folder. Tidak ada cloud dan tidak ada batas ukuran:
hitungannya per orang, bukan dibatasi.

Bentuknya:

    runtime/users/<nama>/
    ├── workspace/     folder kerja pengguna (berkas proyeknya)
    ├── tasks.json     tugas yang pernah dibuatnya
    ├── sessions.json  percakapan miliknya
    ├── events.jsonl   catatan kejadian yang ia hasilkan
    └── cadangan/      salinan berkas kerja untuk pemulihan

Yang TETAP bersama, dengan alasan:

    runtime/users.json      daftar akun. Autentikasi terjadi sebelum tahu siapa
                            pemilik permintaan, jadi daftarnya harus satu tempat.
                            Isinya kecil (nama, peran, sidik jari token).
    runtime/undangan.json   kode undangan, dibaca sebelum ada pengguna.
    runtime/model_meta.json hasil probe model. Itu keadaan gateway, bukan
                            pekerjaan pengguna, dan hasilnya berlaku untuk semua.

Semua jalur di sini fungsi, bukan nilai yang dihitung saat impor: `config.RUNTIME`
dipindahkan oleh aplikasi Android sebelum modul inti diimpor, dan nilai yang
sudah terlanjur dihitung akan menunjuk jalur lama.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import time

import config

# Nama folder untuk akun yang tidak dikenal. Tidak pernah dipakai untuk menulis
# berkas pengguna sungguhan; hanya jaring pengaman supaya jalur tidak pernah
# kosong dan tidak pernah menulis ke akar runtime/users.
NAMA_AMAN = "admin"


def _nama(nama: str | None) -> str:
    n = (nama or "").strip().lower()
    return n if n else NAMA_AMAN


def folder(nama: str | None) -> pathlib.Path:
    """Folder penyimpanan satu pengguna."""
    return config.RUNTIME / "users" / _nama(nama)


def workspace(nama: str | None) -> pathlib.Path:
    return folder(nama) / "workspace"


def tasks_file(nama: str | None) -> pathlib.Path:
    return folder(nama) / "tasks.json"


def sessions_file(nama: str | None) -> pathlib.Path:
    return folder(nama) / "sessions.json"


def events_file(nama: str | None) -> pathlib.Path:
    return folder(nama) / "events.jsonl"


def cadangan_dir(nama: str | None) -> pathlib.Path:
    return folder(nama) / "cadangan"


def siapkan(nama: str | None) -> pathlib.Path:
    """Pastikan folder pengguna ada, lalu kembalikan jalurnya."""
    d = folder(nama)
    for sub in ("", "workspace", "cadangan"):
        p = d / sub if sub else d
        p.mkdir(parents=True, exist_ok=True)
    return d


def daftar_pengguna() -> list[str]:
    """Nama pengguna yang punya folder penyimpanan."""
    akar = config.RUNTIME / "users"
    if not akar.is_dir():
        return []
    return sorted(p.name for p in akar.iterdir() if p.is_dir())


def ukuran(nama: str | None) -> int:
    """Ukuran penyimpanan satu pengguna, dalam byte."""
    d = folder(nama)
    if not d.is_dir():
        return 0
    total = 0
    for p in d.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def pemakaian(semua: list[str] | None = None) -> dict:
    """Pemakaian per pengguna, untuk ditampilkan di UI.

    Tidak ada batas yang ditegakkan: ini hitungan, bukan kuota. Tujuannya supaya
    terlihat siapa menanggung berapa, dan supaya berkas besar bisa ditemukan
    sebelum perangkatnya penuh.
    """
    hasil = {}
    for nama in (semua if semua is not None else daftar_pengguna()):
        d = folder(nama)
        rinci: dict[str, object] = {"total": 0, "workspace": 0, "tasks": 0, "sessions": 0, "events": 0, "cadangan": 0}
        if d.is_dir():
            rinci["workspace"] = _ukuran_pohon(d / "workspace")
            rinci["cadangan"] = _ukuran_pohon(d / "cadangan")
            for kunci, berkas in (("tasks", "tasks.json"), ("sessions", "sessions.json"), ("events", "events.jsonl")):
                try:
                    rinci[kunci] = (d / berkas).stat().st_size
                except OSError:
                    rinci[kunci] = 0
            rinci["total"] = _ukuran_pohon(d)
        rinci["folder"] = str(d)
        hasil[nama] = rinci
    return hasil


def _ukuran_pohon(d: pathlib.Path) -> int:
    if not d.is_dir():
        return 0
    total = 0
    for p in d.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def hapus(nama: str | None) -> bool:
    """Hapus seluruh penyimpanan satu pengguna.

    Dipanggil saat akun dihapus. Tidak menyentuh daftar akun (itu urusan
    users.py); di sini hanya berkasnya.
    """
    d = folder(nama)
    if not d.is_dir():
        return False
    try:
        shutil.rmtree(d)
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ pindahan

# Berkas lama yang dulu bersama di akar runtime. Dibaca sebagai milik admin lalu
# DIGABUNG ke foldernya. Daftar ini dipertahankan sebagai rujukan; urutan
# pemrosesan yang sebenarnya ada di pindahkan_berkas_lama karena tiap jenis
# berkas butuh cara gabung yang berbeda.
PINDAHAN_LAMA = (
    ("tasks.json", "tasks.json"),
    ("sessions.json", "sessions.json"),
    ("events.jsonl", "events.jsonl"),
)


def _gabung_jsonl(sumber: pathlib.Path, tuju: pathlib.Path) -> str:
    """Gabungkan berkas JSONL: isi sumber DITAMBAHKAN ke tujuan.

    Bukan ditimpa dan bukan dilewati. Ditimpa berarti riwayat tujuan hilang;
    dilewati berarti riwayat sumber (yang justru data lama milik pengguna)
    tertinggal di luar penyimpanannya dan tidak pernah terlihat lagi. Kejadian
    adalah catatan tambah-saja, jadi menambahkan aman.
    """
    try:
        tuju.parent.mkdir(parents=True, exist_ok=True)
        with open(sumber, "rb") as f:
            isi = f.read()
        if not isi.strip():
            sumber.unlink()
            return "sumber kosong"
        with open(tuju, "ab") as f:
            f.write(isi if isi.endswith(b"\n") else isi + b"\n")
        sumber.unlink()
        return "digabung"
    except Exception as e:
        return f"gagal: {e}"


def _gabung_json_list(sumber: pathlib.Path, tuju: pathlib.Path, kunci: str = "id") -> str:
    """Gabungkan dua berkas JSON berisi daftar, tanpa kehilangan entri.

    Entri yang sudah ada di tujuan dipertahankan (lebih baru); entri dari sumber
    yang belum ada ditambahkan. Dipakai untuk tasks.json dan sessions.json, yang
    bentuknya daftar.
    """
    try:
        def baca(p: pathlib.Path) -> list:
            if not p.is_file():
                return []
            try:
                d = json.loads(p.read_text())
            except Exception:
                return []
            return d if isinstance(d, list) else []

        a = baca(tuju)
        b = baca(sumber)
        ada = {str(x.get(kunci)) for x in a if isinstance(x, dict)}
        tambah = [x for x in b if isinstance(x, dict) and str(x.get(kunci)) not in ada]
        a.extend(tambah)
        tuju.parent.mkdir(parents=True, exist_ok=True)
        tuju.write_text(json.dumps(a, ensure_ascii=False, default=str))
        sumber.unlink()
        return f"digabung (+{len(tambah)})"
    except Exception as e:
        return f"gagal: {e}"


def pindahkan_berkas_lama(owner: str = NAMA_AMAN) -> dict:
    """Pindahkan berkas bersama yang lama ke folder pemiliknya (admin).

    DIGABUNG, bukan dilewati kalau tujuan sudah ada. Alasannya nyata dan terukur:
    di mesin ini folder admin sudah berisi berkas dari percobaan sebelumnya,
    sehingga aturan "lewati kalau tujuan ada" meninggalkan berkas bersama
    berukuran 7,2 MB (riwayat kejadian asli) di luar penyimpanan pengguna dan UI
    hanya menampilkan data percobaan. Menggabungkan menjaga keduanya.
    """
    tujuan_dir = siapkan(owner)
    hasil: dict[str, str] = {}
    for lama, baru, jenis in (
        ("tasks.json", "tasks.json", "list"),
        ("sessions.json", "sessions.json", "list"),
        ("events.jsonl", "events.jsonl", "jsonl"),
    ):
        sumber = config.RUNTIME / lama
        if not sumber.is_file():
            continue
        tuju = tujuan_dir / baru
        if jenis == "list":
            hasil[lama] = _gabung_json_list(sumber, tuju)
        else:
            hasil[lama] = _gabung_jsonl(sumber, tuju)
    # Cadangan: satu folder berisi banyak subfolder tugas. Yang belum ada di
    # tujuan dipindah; yang namanya sama dibiarkan (tujuan dianggap lebih baru).
    lama_cad = config.RUNTIME / "cadangan"
    tuju_cad = cadangan_dir(owner)
    if lama_cad.is_dir():
        tuju_cad.mkdir(parents=True, exist_ok=True)
        dipindah = 0
        for item in list(lama_cad.iterdir()):
            tuju_item = tuju_cad / item.name
            if tuju_item.exists():
                continue
            try:
                shutil.move(str(item), str(tuju_item))
                dipindah += 1
            except Exception as e:
                hasil[f"cadangan/{item.name}"] = f"gagal: {e}"
        if dipindah:
            hasil["cadangan/"] = f"dipindah {dipindah} folder"
        try:
            lama_cad.rmdir()
        except OSError:
            pass
    return hasil


def pindahkan_workspace_lama(tujuan: pathlib.Path | None = None, owner: str = NAMA_AMAN) -> str:
    """Pindahkan folder kerja lama (di luar runtime) ke dalam folder pengguna.

    Folder kerja admin dulu berada di luar penyimpanan pengguna, sehingga
    bebannya tidak terhitung di tempat yang sama dengan pengguna lain. Dipindah
    hanya kalau tujuannya belum ada isinya.
    """
    sumber = pathlib.Path(config.load()["project_dir"]).expanduser()
    tuju = tujuan or workspace(owner)
    # Kalau setelannya sudah menunjuk ke dalam penyimpanan pengguna (keadaan
    # sesudah pemisahan ini), tidak ada yang perlu dipindah.
    if str(sumber).startswith(str(config.RUNTIME / "users")):
        return "setelan sudah menunjuk penyimpanan pengguna"
    if not sumber.is_dir():
        return "tidak ada folder kerja lama"
    if sumber.resolve() == tuju.resolve():
        return "sudah di tempatnya"
    if tuju.is_dir() and any(tuju.iterdir()):
        return "dilewati: tujuan sudah ada isinya"
    try:
        tuju.parent.mkdir(parents=True, exist_ok=True)
        if tuju.exists():
            tuju.rmdir()
        shutil.move(str(sumber), str(tuju))
        return "dipindah"
    except Exception as e:
        return f"gagal: {e}"


def stempel() -> dict:
    """Ringkasan keadaan penyimpanan, untuk /api/versi dan layar diagnostik."""
    return {
        "akar": str(config.RUNTIME / "users"),
        "pengguna": daftar_pengguna(),
        "waktu": time.time(),
    }
