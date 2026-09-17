"""Project: garis dasar berkas, commit tersaring, dan pemilihan interpreter tes.

Ketiganya pernah membuat tugas melaporkan hasil yang salah: berkas tugas lama
ikut dilaporkan sebagai hasil tugas baru, commit tugas menelan berkas asing, dan
setiap tugas melaporkan \"tests: FAIL\" karena venv yang dipilih tidak punya
pytest walau tes proyeknya hijau.
"""
from __future__ import annotations

import pathlib
import subprocess

import project


def _git(d: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(d), capture_output=True, text=True).stdout


def _repo(d: pathlib.Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(d), check=True)
    subprocess.run(["git", "config", "user.email", "uji@local"], cwd=str(d), check=True)
    subprocess.run(["git", "config", "user.name", "Uji"], cwd=str(d), check=True)


# ------------------------------------------------------------ garis dasar
def test_berkas_lama_tidak_dilaporkan_sebagai_hasil_tugas_ini(folder_kerja):
    """Sisa tugas sebelumnya tidak boleh muncul di ringkasan tugas baru.

    Diukur di mesin ini: `.riset/ads.md` dari tugas riset lama muncul sebagai
    \"new file\" di setiap tugas berikutnya, dan penilai membacanya sebagai hasil
    pekerjaan yang tidak diminta.
    """
    _repo(folder_kerja)
    (folder_kerja / "lama.txt").write_text("sisa tugas lama\n")
    dasar = project.berkas_baru()
    assert "lama.txt" in dasar

    (folder_kerja / "baru.txt").write_text("hasil tugas ini\n")
    ringkas = project.change_summary(2000, abaikan=dasar)
    assert "baru.txt" in ringkas
    assert "lama.txt" not in ringkas


def test_commit_tersaring_tidak_menelan_berkas_asing(folder_kerja):
    """Commit tugas yang lolos verifikasi hanya berisi isi tugas itu."""
    _repo(folder_kerja)
    (folder_kerja / "catatan_kerja.txt").write_text("bukan hasil tugas\n")
    dasar = project.berkas_baru()

    (folder_kerja / "hasil.txt").write_text("isi tugas\n")
    res = project.git_commit_all("Uji commit tersaring", abaikan=dasar)
    assert res["rc"] == 0, res
    dilacak = _git(folder_kerja, "show", "--name-only", "--pretty=format:", "HEAD")
    assert "hasil.txt" in dilacak
    assert "catatan_kerja.txt" not in dilacak


def test_commit_tanpa_perubahan_mengaku_tidak_ada(folder_kerja):
    """Tugas yang tidak mengubah apa pun tidak boleh dianggap commit berhasil.

    `git commit` di pohon bersih keluar dengan kode 1 dan pesan "nothing to
    commit": pemanggil (orchestrator._auto_commit) memperlakukan itu sebagai
    sukses, jadi tes ini memastikan pesannya benar-benar ada, bukan kode keluarnya.
    """
    _repo(folder_kerja)
    (folder_kerja / "a.txt").write_text("a\n")
    subprocess.run(["git", "add", "-A"], cwd=str(folder_kerja), check=True)
    subprocess.run(["git", "commit", "-qm", "awal"], cwd=str(folder_kerja), check=True)
    dasar = project.berkas_baru()

    res = project.git_commit_all("Tidak ada perubahan", abaikan=dasar)
    assert res["rc"] == 0 or "nothing to commit" in res["out"]
    assert "nothing to commit" in res["out"]
    assert len(_git(folder_kerja, "log", "--oneline").splitlines()) == 1


# ------------------------------------------------- interpreter tes
def test_interpreter_tes_dipilih_karena_pytest_nya_ada(folder_kerja, tmp_path):
    """Yang dipilih adalah interpreter yang benar-benar bisa menjalankan pytest.

    Diukur di mesin ini: folder kerja punya .venv sendiri yang berisi pytest,
    sementara .venv milik AstroZ tidak punya. Memilih venv pertama yang ada
    membuat setiap tugas melaporkan \"tests: FAIL\" dengan keluaran
    `No module named pytest`, walau tes proyeknya hijau.
    """
    kosong = folder_kerja / ".venv" / "bin"
    kosong.mkdir(parents=True)
    (kosong / "python").symlink_to("/bin/false")

    dipilih = project._interpreter_tes(folder_kerja)
    assert dipilih != str(kosong / "python")
    assert project._punya_pytest(dipilih)


def test_punya_pytest_menolak_yang_bukan_interpreter():
    assert project._punya_pytest("") is False
    assert project._punya_pytest("/tidak/ada/python") is False


def test_detect_test_command_memakai_interpreter_yang_punya_pytest(folder_kerja):
    (folder_kerja / "test_contoh.py").write_text("def test_a():\n    assert True\n")
    cmd = project.detect_test_command()
    assert cmd.endswith("-m pytest -q")
    assert project._punya_pytest(cmd.split(" ")[0])
