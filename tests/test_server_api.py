"""Server: bentuk API yang dipakai UI.

Dua hal yang pernah salah dan mahal: rute tetap `/api/tasks/running` ditelan
oleh rute dinamis `/api/tasks/{tid}` (404 walau di tes impor benar, jadi strip
kerja di UI tidak pernah muncul), dan `/api/state` ikut mengirim API key gateway
ke seluruh jaringan karena servernya bind 0.0.0.0.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import urllib.error
import urllib.request

import pytest

server = pytest.importorskip("server", reason="butuh fastapi (venv repo)")


def _rute() -> list[str]:
    return [getattr(r, "path", "") for r in server.app.routes]


def test_rute_tetap_sebelum_rute_dinamis():
    """`/api/tasks/running` harus terdaftar sebelum `/api/tasks/{tid}`.

    Kalau tidak, \"running\" dibaca sebagai id tugas dan endpointnya menjawab 404:
    strip kerja di UI tidak pernah muncul, walau di tes impor langsung benar.
    """
    jalur = _rute()
    assert jalur.index("/api/tasks/running") < jalur.index("/api/tasks/{tid}")


def _req(token: str = ""):
    """Request palsu untuk memanggil endpoint langsung di dalam tes.

    Sejak ada autentikasi, endpoint menerima `request` dan membacanya untuk tahu
    siapa yang meminta. Tes yang memanggil fungsinya langsung harus menyediakan
    satu, dan di sini sengaja dibuat lewat jalur yang sama dengan server:
    token di header Authorization.
    """
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"authorization", f"Bearer {token}".encode())] if token else [],
        "query_string": b"",
    }
    r = server.Request(scope)
    r.state.pengguna = None
    return r


def _token_admin() -> str:
    """Token admin yang sah untuk tes.

    Token asli tidak bisa dibaca lagi (hanya sidik jarinya yang disimpan), jadi
    akun khusus tes dibuat sekali. Dipanggil berulang: kalau akunnya sudah ada,
    tokennya diterbitkan ulang supaya tes tidak gagal karena "nama sudah dipakai".
    """
    import users
    users.load()
    if not users.admin_pertama():
        a = users.siapkan_pertama()
        return (a or {}).get("token", "")
    for nama in ("uji-admin", "uji-biasa"):
        if users.ambil(nama):
            return users.setel_ulang_token(nama)["token"]
    return users.buat("uji-admin", "admin")["token"]


def test_api_state_tidak_membocorkan_kunci_gateway(cfg_sementara):
    """UI bind 0.0.0.0: apa pun di /api/state terbaca semua host di jaringan."""
    hasil = asyncio.run(server.state(_req(_token_admin())))
    teks = json.dumps(hasil)
    assert "kunci-uji" not in teks
    assert hasil["gateway"].get("api_key") in (None, "")
    assert "has_key" in hasil["gateway"]


def test_state_menyembunyikan_daftar_model_dari_pengguna_biasa(cfg_sementara):
    """Daftar model menyangkut kunci dan kuota pemilik mesin."""
    import users
    users.load()
    if users.ambil("uji-biasa"):
        token = users.setel_ulang_token("uji-biasa")["token"]
    else:
        token = users.buat("uji-biasa", "user")["token"]
    hasil = asyncio.run(server.state(_req(token)))
    assert hasil["peran"] == "user"
    assert "models" not in hasil["gateway"]
    assert "model_meta" not in hasil["gateway"]
    assert hasil["worker_cfg"] == {}


def test_endpoint_running_menjawab_lewat_fungsi(cfg_sementara):
    hasil = asyncio.run(server.tasks_running(_req(_token_admin())))
    assert hasil["ok"] is True
    assert isinstance(hasil["running"], list)


def _http_get(jalur: str, port: int, timeout: float = 8.0, token: str = "") -> tuple[int, str]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{jalur}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _token_dari_runtime() -> str:
    """Token admin dari runtime server yang sedang jalan.

    Server menyimpan hanya sidik jarinya, jadi token aslinya dibaca dari berkas
    yang ditulis sekali saat akun pertama dibuat.
    """
    import re
    import pathlib
    import config
    f = pathlib.Path(config.RUNTIME) / "admin_token.txt"
    if not f.exists():
        return ""
    m = re.search(r"^([A-Za-z0-9_-]{20,})$", f.read_text(), re.M)
    return m.group(1) if m else ""


def test_endpoint_bersama_wajib_admin():
    """Endpoint yang mengubah keadaan BERSAMA mesin ini harus khusus admin.

    Kejadian nyata: pengguna biasa bisa memasang server MCP, skill, capability,
    dan bahkan memasang CLI pekerja. Semuanya menulis ke konfigurasi dan folder
    yang dibaca keempat pekerja milik pemilik mesin, jadi bukan milik satu
    pengguna. Daftarnya dijaga di sini supaya tidak ada yang lolos lagi saat
    endpoint baru ditambahkan.
    """
    import inspect
    bersama = [
        ("POST", "/api/mcp"),
        ("DELETE", "/api/mcp/{nama}"),
        ("POST", "/api/skills"),
        ("DELETE", "/api/skills/{nama}"),
        ("POST", "/api/skills/bawaan"),
        ("POST", "/api/capability/pasang"),
        ("DELETE", "/api/capability/{nama}"),
        ("POST", "/api/workers/{key}/pasang"),
        ("POST", "/api/workers/{key}"),
        ("POST", "/api/config"),
        ("POST", "/api/apply"),
        ("POST", "/api/gateway/key"),
        ("POST", "/api/gateway/sync"),
        ("GET", "/api/gateway/models"),
        ("GET", "/api/akun"),
        ("POST", "/api/akun"),
    ]
    # Endpoint yang menyebut satu tugas wajib memeriksa PEMILIK tugasnya, bukan
    # hanya status admin: kalau tidak, pengguna lain bisa menghentikan atau
    # membaca tugas orang lewat id yang ditebak.
    per_tugas = [
        ("GET", "/api/tasks/{tid}"),
        ("GET", "/api/tasks/{tid}/berkas"),
        ("POST", "/api/tasks/{tid}/hentikan"),
    ]
    # Endpoint yang MEMBUAT pekerjaan wajib menetapkan pemiliknya. Tanpa ini
    # tugas pengguna biasa tercatat milik admin dan menulis ke folder kerja admin.
    pembuat = [
        ("POST", "/api/tasks"),
        ("POST", "/api/chat"),
    ]
    # Nama fungsi endpoint diambil dari tabel rute supaya cocok walau
    # penamaannya berbeda dari dugaan.
    peta: dict[tuple[str, str], object] = {}
    for r in server.app.routes:
        p = getattr(r, "path", "")
        for m in (getattr(r, "methods", None) or []):
            peta[(m, p)] = r
    kurang: list[str] = []
    for metode, jalur in bersama:
        r = peta.get((metode, jalur))
        if r is None:
            kurang.append(f"{metode} {jalur} (rute tidak ada)")
            continue
        fn = getattr(r, "endpoint", None)
        if fn is None:
            kurang.append(f"{metode} {jalur} (tanpa endpoint)")
            continue
        if "_admin_saja" not in inspect.getsource(fn):
            kurang.append(f"{metode} {jalur}")
    for metode, jalur in per_tugas:
        r = peta.get((metode, jalur))
        fn = getattr(r, "endpoint", None) if r else None
        if fn is None:
            kurang.append(f"{metode} {jalur} (rute tidak ada)")
            continue
        # Pemeriksaan pemilik terlihat dari pemakaian get_task + owner.
        src = inspect.getsource(fn)
        if "get_task" not in src or "owner" not in src:
            kurang.append(f"{metode} {jalur} (tanpa pemeriksaan pemilik)")
    for metode, jalur in pembuat:
        r = peta.get((metode, jalur))
        fn = getattr(r, "endpoint", None) if r else None
        if fn is None:
            kurang.append(f"{metode} {jalur} (rute tidak ada)")
            continue
        if "owner=" not in inspect.getsource(fn):
            kurang.append(f"{metode} {jalur} (tidak menetapkan owner)")
    assert not kurang, "endpoint tanpa penjagaan: " + ", ".join(kurang)


def test_api_lewat_http_sungguhan():
    """Uji batas jaringan, bukan cuma fungsi: rute dinamis pernah menelannya.

    Diukur: `/api/tasks/running` benar saat diimpor langsung, tetapi 404 lewat
    HTTP karena `/api/tasks/{tid}` didaftarkan lebih dulu. Hanya panggilan HTTP
    yang bisa menangkap itu, jadi tes ini memanggil server yang sedang jalan.

    Sejak ada autentikasi, tes ini juga memeriksa gerbangnya: tanpa token harus
    401, dan halaman UI sendiri harus tetap terbuka supaya layar masuk bisa
    dimuat.
    """
    port = int(os.environ.get("UI_PORT") or 8799)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
    except OSError:
        pytest.skip(f"UI belum jalan di :{port} (jalankan ./run.sh)")

    # Tanpa token: API tertutup, halaman UI terbuka.
    try:
        _http_get("/api/state", port)
        raise AssertionError("/api/state tanpa token seharusnya 401")
    except urllib.error.HTTPError as e:
        assert e.code == 401
    status, body = _http_get("/", port)
    assert status == 200
    assert "<html" in body.lower()

    token = _token_dari_runtime()
    if not token:
        pytest.skip("token admin belum ada di runtime; buka UI sekali dulu")

    status, body = _http_get("/api/tasks/running", port, token=token)
    assert status == 200
    assert json.loads(body)["ok"] is True

    status, body = _http_get("/api/state", port, token=token)
    assert status == 200
    state = json.loads(body)
    assert state["gateway"].get("api_key") in (None, "")

    try:
        _http_get("/api/tasks/tidak-ada-tugas-ini", port, token=token)
        raise AssertionError("id tugas palsu seharusnya 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404
