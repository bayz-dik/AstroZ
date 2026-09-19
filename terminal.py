"""Terminal AstroZ: shell sungguhan untuk pengguna, bukan terminal tiruan.

Isi modul ini adalah sisi server dari terminal yang ada di aplikasi Android.
Perintah benar-benar dijalankan oleh shell di perangkat, dengan PATH, HOME, dan
TMPDIR milik prefix terminal AstroZ (busybox + git + curl + npm).

Dua cara pakai:

  Terminal.jalankan(...)   satu perintah, tunggu selesai, ambil keluarannya
  Terminal.sesi(owner)     shell yang tetap hidup: `cd` dan variabel bertahan,
                           keluarannya bisa diikuti sambil berjalan (SSE)

Batas keamanan: setiap pengguna hanya boleh bekerja di dalam folder kerjanya
sendiri. Permintaan `cd` ke luar folder itu ditolak, dan `cwd` selalu divalidasi
ulang sebelum perintah dijalankan.

Di mesin pengembangan (Linux/macOS) prefix Android tidak ada; modul ini jatuh ke
shell sistem supaya perilakunya tetap bisa diuji. Di perangkat, prefix itu wajib
ada, dan kalau tidak ada kita melaporkan apa adanya -- bukan berpura-pura siap.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import threading
import time
import uuid

import config

# Berapa banyak keluaran yang disimpan per sesi. Terminal bisa mengeluarkan
# puluhan ribu baris (mis. `npm install`), dan menyimpan semuanya akan
# menghabiskan memori tanpa manfaat: yang dibaca pengguna hanya bagian akhir.
BATAS_BUFFER = 400_000
SIMPAN_SETELAH_POTONG = 250_000

TIMEOUT_BAWAAN = 120
TIMEOUT_MAKS = 1800


def _kandidat_prefix() -> list[pathlib.Path]:
    """Tempat prefix terminal mungkin berada, dari yang paling mungkin."""
    kandidat = []
    env = os.environ.get("ASTROZ_TERM_PREFIX")
    if env:
        kandidat.append(pathlib.Path(env))
    # Di perangkat: filesDir/astroz/term, ditunjuk Java lewat env saat start.
    if getattr(config, "ROOT", None):
        kandidat.append(pathlib.Path(config.ROOT) / "term")
    kandidat.append(pathlib.Path(config.RUNTIME).parent / "term")
    # Di mesin pengembangan: aset yang sama dipakai untuk menguji.
    kandidat.append(pathlib.Path(__file__).resolve().parent / "android/app/src/main/assets/term")
    return kandidat


def prefix() -> pathlib.Path | None:
    """Folder prefix terminal (berisi bin/, lib/, etc/) kalau ada."""
    for k in _kandidat_prefix():
        if (k / "bin/sh").exists() or (k / "bin/busybox").exists():
            return k
    return None


def _shell_sistem() -> str:
    for s in ("/bin/bash", "/bin/sh", "/usr/bin/sh"):
        if pathlib.Path(s).is_file():
            return s
    return "sh"


def tersedia() -> bool:
    return prefix() is not None or shutil.which("sh") is not None


def info() -> dict:
    """Keadaan terminal, apa adanya: prefix mana yang dipakai dan alat apa saja
    yang benar-benar ada (diperiksa dengan menjalankannya, bukan diasumsikan)."""
    p = prefix()
    alat = ["sh", "bash", "git", "curl", "npm", "node", "python", "pip", "busybox"]
    ada = {}
    for a in alat:
        if p is not None:
            # `sh` di paket adalah symlink ke busybox dan bisa tidak ada di
            # perangkat; kalau begitu busybox yang dipakai, jadi itu yang
            # dilaporkan -- bukan "tidak ada" yang menyesatkan.
            if a == "sh":
                ada[a] = (p / "bin/sh").exists() or (p / "bin/busybox").exists()
            elif a == "python":
                # Alias tanpa versi dibuat Java di perangkat; yang pasti ada di
                # aset adalah python3.14.
                ada[a] = (p / "bin/python").exists() or (p / "bin/python3").exists() \
                    or (p / "bin/python3.14").exists()
            else:
                ada[a] = (p / "bin" / a).exists()
        else:
            ada[a] = shutil.which(a) is not None
    return {
        "tersedia": tersedia(),
        "prefix": str(p) if p else "",
        "mode": "android" if p else "sistem",
        "alat": ada,
    }


# Penjara `cd` untuk shell pengguna.
#
# Kenapa perlu: semua pengguna berbagi satu sandbox aplikasi Android (satu UID),
# jadi izin berkas sistem tidak memisahkan mereka. Tanpa penjagaan ini,
# `cd ../pengguna-lain` dari terminal akan membuka folder kerja orang lain.
# Fungsi ini mengganti `cd` bawaan supaya folder kerja tidak pernah ditinggalkan.
#
# Ditulis SATU BARIS dan tanpa newline di dalamnya, karena teks ini dikirim ke
# shell hidup sebagai perintah. Versi multi-baris pernah digabung dengan
# `replace("\n", " ")` dan itu merusak sintaks `case`:
#     sh: line 1: syntax error: unexpected ")" (expecting "}")
# Satu baris aman untuk kedua cara pakai (shell hidup dan `sh -c`).
#
# Batas kejujuran: ini penjagaan di tingkat shell, bukan sandbox kernel. Orang
# yang sengaja memanggil shell lain (`busybox sh`) masih bisa keluar. Untuk
# pemisahan yang tidak bisa dilewati, berkas harus dienkripsi per pengguna --
# belum dilakukan. Yang dijamin di sini: perintah biasa, termasuk `cd ..` dan
# jalur absolut, tidak membawa pengguna ke luar foldernya.
PENJARA = (
    'cd() { __t="${1:-$HOME}"; command cd "$__t" 2>/dev/null || return 1; '
    '__p="$(pwd)"; case "$__p" in "$ASTROZ_KERJA"|"$ASTROZ_KERJA"/*) return 0 ;; esac; '
    'echo "cd: di luar folder kerja -- tetap di $ASTROZ_KERJA" >&2; '
    'command cd "$ASTROZ_KERJA"; return 1; }'
)


def env(owner: str = "") -> dict:
    """Lingkungan shell.

    Yang penting dan mudah terlewat: sertifikat TLS. Tanpa SSL_CERT_FILE dan
    GIT_SSL_CAINFO, `git clone` dan `curl` https gagal dengan galat sertifikat
    walau jaringannya sehat.
    """
    p = prefix()
    e = dict(os.environ)
    if p is not None:
        e["PATH"] = f"{p}/bin:{p}/libexec/git-core:/system/bin:/system/xbin"
        e["LD_LIBRARY_PATH"] = f"{p}/lib"
        e["PREFIX"] = str(p)
        e["HOME"] = str(p / "home")
        e["TMPDIR"] = str(p / "tmp")
        for d in (p / "home", p / "tmp"):
            d.mkdir(parents=True, exist_ok=True)
        ca = p / "etc/tls/cert.pem"
        if ca.is_file():
            e["SSL_CERT_FILE"] = str(ca)
            e["GIT_SSL_CAINFO"] = str(ca)
            e["CURL_CA_BUNDLE"] = str(ca)
        # Basis data terminfo ikut di aset. Tanpa ini `clear`, `less`, `vi`, dan
        # program berkursor lainnya mengeluh "terminfo database is not
        # accessible" walau TERM sudah benar.
        ti = p / "share/terminfo"
        if ti.is_dir():
            e["TERMINFO"] = str(ti)
            e["TERMINFO_DIRS"] = str(ti)
        e["GIT_EXEC_PATH"] = str(p / "libexec/git-core")
        e["GIT_TEMPLATE_DIR"] = str(p / "share/git-core/templates")
    e.setdefault("TERM", "xterm-256color")
    e["LANG"] = "C.UTF-8"
    # Batas folder kerja, dibaca oleh PENJARA.
    if owner:
        e["ASTROZ_KERJA"] = str(folder_kerja(owner))
    e.pop("PYTHONHOME", None)  # jangan sampai Python tertukar dengan milik app
    return e


def shell_cmd() -> list[str]:
    """Perintah shell sebagai daftar argv.

    Busybox hanya berperilaku sebagai shell kalau argv[0]-nya "sh", jadi kalau
    yang dipakai busybox, kata "sh" harus ikut sebagai argumen pertama. Tanpa itu
    busybox mencetak bantuan lalu keluar, dan seluruh terminal tampak mati.
    """
    p = prefix()
    if p is not None:
        sh = p / "bin/sh"
        if sh.is_file():
            return [str(sh)]
        bb = p / "bin/busybox"
        if bb.is_file():
            return [str(bb), "sh"]
    return [_shell_sistem()]


def shell() -> str:
    """Shell yang dipakai untuk menjalankan perintah (untuk pesan/log)."""
    return " ".join(shell_cmd())


def folder_kerja(owner: str) -> pathlib.Path:
    """Folder kerja pengguna, tempat perintah dijalankan."""
    import users as modul_users

    try:
        w = modul_users.ruang_kerja(owner)
    except Exception:
        w = pathlib.Path(config.RUNTIME) / "users" / (owner or "admin") / "workspace"
    w = pathlib.Path(w)
    w.mkdir(parents=True, exist_ok=True)
    return w


def cwd_sah(owner: str, cwd: str) -> pathlib.Path:
    """Pastikan folder kerja tetap di dalam milik pengguna.

    Tanpa ini, satu pengguna bisa membaca data pengguna lain lewat `cd`.
    """
    akar = folder_kerja(owner).resolve()
    if not cwd:
        return akar
    c = pathlib.Path(cwd)
    if not c.is_absolute():
        c = akar / c
    try:
        c = c.resolve()
    except Exception:
        return akar
    if c == akar or akar in c.parents:
        return c if c.is_dir() else akar
    return akar


def jalankan(perintah: str, owner: str = "", cwd: str = "", timeout: int = TIMEOUT_BAWAAN) -> dict:
    """Menjalankan satu perintah sampai selesai."""
    if not perintah.strip():
        return {"ok": False, "keluaran": "", "kode": -1, "error": "perintah kosong"}
    timeout = max(1, min(int(timeout or TIMEOUT_BAWAAN), TIMEOUT_MAKS))
    kerja = cwd_sah(owner, cwd)
    mulai = time.time()
    try:
        p = subprocess.run(
            # Tanpa -l: shell login membaca /etc/profile, dan di lingkungan
            # berbagi berkas itu milik sistem lain (mis. menjalankan run-parts),
            # sehingga keluarannya bercampur dengan keluaran perintah pengguna.
            # Lingkungannya sudah kita set sendiri lewat env().
            [*shell_cmd(), "-c", PENJARA + "\n" + perintah],
            cwd=str(kerja),
            env=env(owner),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        keluaran = (p.stdout or "") + (p.stderr or "")
        return {
            "ok": p.returncode == 0,
            "kode": p.returncode,
            "keluaran": keluaran,
            "cwd": str(kerja),
            "durasi": round(time.time() - mulai, 2),
        }
    except subprocess.TimeoutExpired as e:
        sebagian = ""
        for bagian in (e.stdout, e.stderr):
            if bagian:
                sebagian += bagian if isinstance(bagian, str) else bagian.decode("utf-8", "replace")
        return {
            "ok": False,
            "kode": 124,
            "keluaran": sebagian,
            "cwd": str(kerja),
            "durasi": round(time.time() - mulai, 2),
            "error": f"melewati batas waktu {timeout} detik",
        }
    except Exception as e:  # pragma: no cover - kegagalan lingkungan
        return {"ok": False, "kode": -1, "keluaran": "", "cwd": str(kerja), "error": str(e)}


class Sesi:
    """Shell yang tetap hidup untuk satu pengguna.

    Kenapa persisten: `cd`, variabel, dan proses latar harus bertahan antar
    perintah. Kalau setiap perintah dijalankan di shell baru, `cd proyek` lalu
    `ls` pada perintah berikutnya akan berada di folder yang salah.

    Keluarannya ditampung di buffer dan dibagikan ke pelanggan (SSE), jadi
    perintah panjang seperti `npm install` bisa diikuti sambil berjalan.
    """

    def __init__(self, owner: str) -> None:
        self.owner = owner
        self.id = uuid.uuid4().hex[:12]
        self.proc: subprocess.Popen | None = None
        self._buffer = ""
        self._lock = threading.Lock()
        self._pelanggan: list[threading.Event] = []
        self._pos: dict[int, int] = {}
        self.cwd = folder_kerja(owner)
        self.mulai = time.time()
        self.sibuk = False

    # ---------------------------------------------------------------- siklus

    def nyalakan(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        self.proc = subprocess.Popen(
            [*shell_cmd()],
            cwd=str(self.cwd),
            env=env(self.owner),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._baca, daemon=True).start()
        # Penjara dipasang di shell yang hidup juga, bukan hanya di jalankan():
        # shell ini yang dipakai perintah dari UI. PENJARA sudah satu baris, jadi
        # bisa dikirim apa adanya.
        self.kirim(PENJARA)
        self.kirim(f"cd {_kutip(str(self.cwd))} 2>/dev/null; export PS1=''")

    def _baca(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for baris in self.proc.stdout:
            self._tambah(baris.rstrip("\n"))
        self._tambah("[shell berhenti]")

    def _tambah(self, baris: str) -> None:
        with self._lock:
            self._buffer += baris + "\n"
            if len(self._buffer) > BATAS_BUFFER:
                self._buffer = self._buffer[-SIMPAN_SETELAH_POTONG:]
            pelanggan = list(self._pelanggan)
        for ev in pelanggan:
            ev.set()

    def kirim(self, perintah: str) -> None:
        if self.proc is None or self.proc.poll() is not None:
            self.nyalakan()
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write(perintah + "\n")
        self.proc.stdin.flush()

    def jalankan(self, perintah: str, timeout: int = TIMEOUT_BAWAAN) -> dict:
        """Kirim perintah ke shell hidup lalu tunggu penandanya muncul.

        Penanda dipakai supaya kita tahu perintahnya benar-benar selesai, bukan
        hanya karena keluarannya sedang sepi. Folder kerja ikut dilaporkan pada
        penanda yang sama, sebab `cd` di dalam shell mengubah posisi dan UI
        perlu tahu posisi barunya.
        """
        self.nyalakan()
        tanda = f"__ASTROZ_SELESAI_{uuid.uuid4().hex[:8]}__"
        awal = len(self.buffer())
        self.sibuk = True
        try:
            self.kirim(f"{perintah}; __kode=$?; echo {tanda}:$__kode:$(pwd)")
            batas = time.time() + max(1, min(int(timeout or TIMEOUT_BAWAAN), TIMEOUT_MAKS))
            while time.time() < batas:
                isi = self.buffer()[awal:]
                idx = isi.rfind(tanda)
                if idx >= 0:
                    sisa = isi[idx:].split("\n", 1)[0]
                    bagian = sisa.split(":", 2)
                    kode = 0
                    if len(bagian) > 1:
                        try:
                            kode = int(bagian[1] or 0)
                        except ValueError:
                            kode = 0
                    if len(bagian) > 2 and bagian[2].strip():
                        self.cwd = pathlib.Path(bagian[2].strip())
                    return {"ok": kode == 0, "kode": kode, "keluaran": isi[:idx],
                            "cwd": str(self.cwd)}
                time.sleep(0.15)
            return {"ok": False, "kode": 124, "keluaran": self.buffer()[awal:],
                    "cwd": str(self.cwd), "error": f"melewati batas waktu {timeout} detik"}
        finally:
            self.sibuk = False

    # --------------------------------------------------------------- keluaran

    def buffer(self) -> str:
        with self._lock:
            return self._buffer

    def bersihkan(self) -> None:
        with self._lock:
            self._buffer = ""

    def pelanggan_tambah(self) -> int:
        ev = threading.Event()
        with self._lock:
            self._pelanggan.append(ev)
            kid = id(ev)
        return kid

    def pelanggan_buang(self, kid: int) -> None:
        with self._lock:
            self._pelanggan = [e for e in self._pelanggan if id(e) != kid]

    def tunggu_baru(self, kid: int, posisi: int, timeout: float = 20.0) -> tuple[str, int]:
        """Ambil keluaran baru sejak `posisi`. Dipakai oleh SSE."""
        waktu_habis = time.time() + timeout
        while time.time() < waktu_habis:
            isi = self.buffer()
            if len(isi) > posisi:
                return isi[posisi:], len(isi)
            time.sleep(0.2)
        return "", posisi

    def matikan(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()
        self.proc = None


def _kutip(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


# Satu shell hidup per pengguna. Dua pengguna berbeda tidak boleh berbagi shell,
# karena `cd` salah satu akan menggeser folder kerja yang lain.
_sesi: dict[str, Sesi] = {}
_sesi_lock = threading.Lock()


def sesi(owner: str) -> Sesi:
    with _sesi_lock:
        s = _sesi.get(owner)
        if s is None or (s.proc is not None and s.proc.poll() is not None and not s.buffer().endswith("[shell berhenti]\n")):
            s = Sesi(owner)
            _sesi[owner] = s
        return s


def semua_sesi() -> dict[str, Sesi]:
    with _sesi_lock:
        return dict(_sesi)


def matikan_sesi(owner: str) -> None:
    with _sesi_lock:
        s = _sesi.pop(owner, None)
    if s is not None:
        s.matikan()
