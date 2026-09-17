"""Akun pengguna AstroZ: masuk dengan token, dan tiap orang punya ruangnya sendiri.

Kenapa token, bukan kata sandi biasa: AstroZ dipakai dari browser HP maupun
skrip, dan token bisa dicabut tanpa mengubah apa pun di sisi klien. Kata sandi
disimpan hanya sebagai sidik jari PBKDF2-SHA256, jadi berkas akunnya tidak
berguna walau terbaca.

Peran:
  admin  semua endpoint, termasuk kunci API gateway dan setelan
  user   percakapan, tugas, dan folder kerjanya sendiri

Aturan yang dipegang di sini:
  - Token asli hanya ditampilkan SEKALI, saat akun dibuat. Setelah itu yang
    tersimpan hanya sidik jarinya.
  - Token tidak pernah masuk feed kejadian: feed itu tampil di UI, dan token di
    sana sama saja mengumumkannya.
  - Perbandingan sidik jari memakai hmac.compare_digest supaya waktu balasannya
    tidak membocorkan berapa banyak karakter yang sudah benar.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import pathlib
import re
import secrets
import threading
import time

import config

def _users_file() -> pathlib.Path:
    """Jalur berkas akun, dihitung saat dipakai.

    Sengaja bukan konstanta: kalau dihitung sekali saat impor, tes yang
    mengalihkan config.RUNTIME tetap menulis ke runtime milik mesin ini, dan
    akun sungguhan tercampur akun uji. Kejadiannya nyata.
    """
    return pathlib.Path(config.RUNTIME) / "users.json"


def _token_file() -> pathlib.Path:
    return pathlib.Path(config.RUNTIME) / "admin_token.txt"

# Sidik jari token: PBKDF2-SHA256. Jumlah putarannya dipilih supaya masuk akal
# di HP (sekitar 0,1 detik) tetapi tetap mahal untuk ditebak berulang kali.
PUTARAN = 200_000
PANJANG_TOKEN = 32          # byte acak; hasilnya 43 karakter base64url

NAMA_AMAN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,30}$")
PERAN = ("admin", "user")

_lock = threading.Lock()
_U: dict[str, dict] = {}


# ------------------------------------------------------------------ sidik jari

def _sidik(token: str, garam: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", token.encode(), bytes.fromhex(garam), PUTARAN).hex()


def _token_baru() -> str:
    return secrets.token_urlsafe(PANJANG_TOKEN)


# ------------------------------------------------------------------ simpan/muat

def _persist() -> None:
    try:
        _users_file().parent.mkdir(parents=True, exist_ok=True)
        _users_file().write_text(json.dumps(list(_U.values()), ensure_ascii=False, indent=2))
        # Berkas akun memuat sidik jari token: hanya pemilik mesin yang boleh
        # membacanya.
        _users_file().chmod(0o600)
    except Exception:
        pass


def load() -> int:
    if not _users_file().exists():
        return 0
    try:
        items = json.loads(_users_file().read_text())
    except Exception:
        return 0
    if not isinstance(items, list):
        return 0
    for u in items:
        if isinstance(u, dict) and u.get("nama"):
            _U[u["nama"]] = u
    return len(_U)


def _tulis_token_awal(token: str) -> None:
    """Simpan token admin pertama ke berkas terpisah yang hanya bisa dibaca pemilik.

    Ditulis ke berkas, bukan ke feed kejadian: feed itu tampil di UI, dan token
    di sana sama saja mengumumkannya ke siapa pun yang membuka halaman.
    """
    try:
        _token_file().parent.mkdir(parents=True, exist_ok=True)
        _token_file().write_text(
            "Token masuk AstroZ untuk akun admin.\n"
            "Simpan di tempat aman, lalu hapus berkas ini.\n\n" + token + "\n"
        )
        _token_file().chmod(0o600)
    except Exception:
        pass


def siapkan_pertama() -> dict | None:
    """Buat akun admin pertama kalau belum ada akun sama sekali.

    Tanpa ini, tidak ada yang bisa masuk setelah autentikasi dinyalakan.
    """
    if _U:
        return None
    token = _token_baru()
    garam = secrets.token_hex(16)
    u = {
        "nama": "admin",
        "peran": "admin",
        "garam": garam,
        "sidik": _sidik(token, garam),
        "dibuat": time.time(),
        "aktif": True,
    }
    with _lock:
        _U["admin"] = u
    _persist()
    _tulis_token_awal(token)
    return {"nama": "admin", "peran": "admin", "token": token}


# ------------------------------------------------------------------ periksa

def _publik(u: dict) -> dict:
    return {
        "nama": u["nama"],
        "peran": u.get("peran", "user"),
        "aktif": bool(u.get("aktif", True)),
        "dibuat": u.get("dibuat"),
    }


def daftar() -> list[dict]:
    return [_publik(u) for u in sorted(_U.values(), key=lambda x: x["nama"])]


def ambil(nama: str) -> dict | None:
    u = _U.get((nama or "").strip().lower())
    return _publik(u) if u else None


def verifikasi(token: str) -> dict | None:
    """Cocokkan token dengan semua akun. Hasilnya data publik, bukan sidik jari."""
    token = (token or "").strip()
    if not token:
        return None
    for u in _U.values():
        if not u.get("aktif", True):
            continue
        if hmac.compare_digest(_sidik(token, u["garam"]), u["sidik"]):
            return _publik(u)
    return None


def peran(nama: str) -> str:
    u = _U.get((nama or "").strip().lower())
    return (u or {}).get("peran", "user")


def admin_pertama() -> str:
    """Nama akun admin, dipakai untuk memberi tahu siapa yang berhak mengatur."""
    for u in _U.values():
        if u.get("peran") == "admin":
            return u["nama"]
    return ""


# ------------------------------------------------------------------ ubah akun

def buat(nama: str, peran: str = "user") -> dict:
    nama = (nama or "").strip().lower()
    if not NAMA_AMAN.match(nama):
        raise ValueError("nama hanya huruf kecil, angka, titik, garis bawah, dan strip (2-31 karakter)")
    if peran not in PERAN:
        raise ValueError(f"peran harus salah satu dari: {', '.join(PERAN)}")
    if nama in _U:
        raise ValueError("nama sudah dipakai")
    token = _token_baru()
    garam = secrets.token_hex(16)
    u = {
        "nama": nama,
        "peran": peran,
        "garam": garam,
        "sidik": _sidik(token, garam),
        "dibuat": time.time(),
        "aktif": True,
    }
    with _lock:
        _U[nama] = u
    _persist()
    # Token hanya ada di balasan ini. Tidak disimpan dalam bentuk asli.
    return {**_publik(u), "token": token}


def setel_ulang_token(nama: str) -> dict:
    """Terbitkan token baru untuk satu akun, dan yang lama langsung mati."""
    nama = (nama or "").strip().lower()
    u = _U.get(nama)
    if not u:
        raise ValueError("akun tidak ada")
    token = _token_baru()
    garam = secrets.token_hex(16)
    with _lock:
        u["garam"] = garam
        u["sidik"] = _sidik(token, garam)
    _persist()
    return {**_publik(u), "token": token}


def setel_aktif(nama: str, aktif: bool) -> dict:
    nama = (nama or "").strip().lower()
    u = _U.get(nama)
    if not u:
        raise ValueError("akun tidak ada")
    # Admin terakhir tidak boleh dimatikan: kalau itu terjadi, tidak ada lagi
    # yang bisa mengelola akun dan kunci API.
    if not aktif and u.get("peran") == "admin":
        admin_aktif = [x for x in _U.values() if x.get("peran") == "admin" and x.get("aktif", True)]
        if len(admin_aktif) <= 1:
            raise ValueError("ini admin aktif terakhir, tidak boleh dimatikan")
    with _lock:
        u["aktif"] = bool(aktif)
    _persist()
    return _publik(u)


def hapus(nama: str) -> dict:
    nama = (nama or "").strip().lower()
    u = _U.get(nama)
    if not u:
        raise ValueError("akun tidak ada")
    if u.get("peran") == "admin":
        admin_aktif = [x for x in _U.values() if x.get("peran") == "admin" and x.get("aktif", True)]
        if len(admin_aktif) <= 1:
            raise ValueError("ini admin aktif terakhir, tidak boleh dihapus")
    with _lock:
        _U.pop(nama, None)
    _persist()
    return {"nama": nama, "dihapus": True}


# ------------------------------------------------------------------ ruang kerja

def ruang_kerja(nama: str) -> pathlib.Path:
    """Folder kerja milik satu pengguna.

    Admin memakai folder kerja yang sudah ada di setelan supaya pekerjaan lama
    tidak berpindah tempat. Pengguna lain mendapat foldernya sendiri di bawah
    runtime/users/<nama>/workspace: terpisah dari yang lain, dan di luar repo
    supaya tidak ikut ter-commit.
    """
    nama = (nama or "").strip().lower() or "user"
    if peran(nama) == "admin":
        return pathlib.Path(config.load()["project_dir"]).expanduser()
    return config.RUNTIME / "users" / nama / "workspace"
