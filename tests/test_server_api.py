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
    if users.ambil("uji-admin"):
        return users.setel_ulang_token("uji-admin")["token"]
    if not users.admin_pertama():
        a = users.siapkan_pertama()
        return (a or {}).get("token", "")
    return users.buat("uji-admin", "admin")["token"]


def _token_biasa() -> str:
    """Token akun peran `user` untuk tes pemisahan hak.

    Tokennya SELALU diterbitkan ulang: kalau tidak, tes yang jalan dua kali
    memakai token dari jalan sebelumnya, dan hasilnya bergantung urutan tes.
    """
    import users
    users.load()
    if users.ambil("uji-biasa"):
        return users.setel_ulang_token("uji-biasa")["token"]
    return users.buat("uji-biasa", "user")["token"]


def test_api_state_tidak_membocorkan_kunci_gateway(cfg_sementara):
    """UI bind 0.0.0.0: apa pun di /api/state terbaca semua host di jaringan."""
    hasil = asyncio.run(server.state(_req(_token_admin())))
    teks = json.dumps(hasil)
    assert "kunci-uji" not in teks
    assert hasil["gateway"].get("api_key") in (None, "")
    assert "has_key" in hasil["gateway"]


def test_state_menyembunyikan_daftar_model_dari_pengguna_biasa(cfg_sementara):
    """Daftar model menyangkut kunci dan kuota pemilik mesin."""
    token = _token_biasa()
    hasil = asyncio.run(server.state(_req(token)))
    assert hasil["peran"] == "user"
    assert "models" not in hasil["gateway"]
    assert "model_meta" not in hasil["gateway"]
    assert hasil["worker_cfg"] == {}


def test_state_menyembunyikan_jalur_pekerja_dari_pengguna_biasa(cfg_sementara):
    """Jalur konfigurasi CLI menunjuk tata letak mesin pemilik.

    `/api/state` ikut mengirim daftar pekerja. Tanpa penyaringan, pengguna biasa
    menerima `/root/.claude/settings.json` dan sejenisnya di setiap muat halaman,
    padahal UI-nya hanya memakai label, versi, dan status terpasang.
    """
    hasil = asyncio.run(server.state(_req(_token_biasa())))
    for w in hasil["workers"]:
        assert "path" not in w, w
        assert "config_path" not in w, w
        assert "error" not in w, w
        assert w["key"] and "installed" in w
    # Admin tetap menerimanya: halaman Pengaturan menampilkan jalur berkasnya.
    admin = asyncio.run(server.state(_req(_token_admin())))
    assert all("config_path" in w for w in admin["workers"])


def test_workers_menyembunyikan_jalur_dari_pengguna_biasa(cfg_sementara):
    """`/api/workers` dan `/api/workers/paket` memakai penyaring yang sama."""
    umum = asyncio.run(server.workers(_req(_token_biasa())))
    assert umum["workers"], "daftar pekerja tidak boleh kosong"
    assert all("path" not in w and "config_path" not in w for w in umum["workers"])
    paket = asyncio.run(server.workers_paket(_req(_token_biasa())))
    assert paket["ok"] is True
    assert len(paket["pekerja"]) == 4
    admin = asyncio.run(server.workers(_req(_token_admin())))
    assert all("config_path" in w for w in admin["workers"])


def test_gateway_model_dan_probe_menolak_pengguna_biasa(cfg_sementara):
    """Model satu mesin dipakai semua orang: menggantinya bukan hak satu pengguna.

    Terukur sebelum diperbaiki: `POST /api/gateway/model` dari akun peran `user`
    menjawab HTTP 200 dan benar-benar menulis ulang model di config.yaml Hermes.
    `/api/gateway/probe` juga terbuka, padahal ia memakai kunci API dan kuota
    pemilik mesin.
    """
    for fn, kwargs in (
        (server.gateway_set_model, {"payload": {"model": "x/y"}}),
        (server.gateway_probe, {"payload": {}}),
    ):
        jawab = asyncio.run(fn(request=_req(_token_biasa()), **kwargs))
        assert jawab.status_code == 403, f"{fn.__name__} menerima pengguna biasa"
    # Admin tetap bisa memanggilnya (di sini sengaja dikirim model kosong supaya
    # tidak ada permintaan jaringan: yang diperiksa hanya gerbangnya).
    jawab = asyncio.run(server.gateway_set_model(payload={}, request=_req(_token_admin())))
    assert jawab.status_code == 400, "model kosong seharusnya 400, bukan 403"


def test_jobs_dan_capability_pratinjau_menolak_pengguna_biasa(cfg_sementara):
    """Antrean pekerjaan latar dan unduhan paket milik mesin pemilik."""
    jawab = asyncio.run(server.jobs_list(_req(_token_biasa())))
    assert jawab.status_code == 403
    jawab = asyncio.run(server.capability_preview({"url": "https://contoh.invalid/x"}, _req(_token_biasa())))
    assert jawab.status_code == 403
    # Daftar paket tetap boleh dibaca, hanya jalur foldernya yang dibuang.
    cap = asyncio.run(server.capability_list(_req(_token_biasa())))
    assert cap["ok"] is True
    assert all("akar" not in p for p in cap["terpasang"])


def test_skills_menyembunyikan_jalur_tapi_tetap_ada_isi(cfg_sementara):
    """`/api/skills` tetap berguna untuk pengguna biasa, tanpa jalur mesin.

    Dua hal yang mudah salah di sini: `path` menunjuk folder pemilik, dan hasil
    pemindaian disimpan di cache. Cache satu slot akan menyajikan jawaban admin
    ke pengguna biasa (atau sebaliknya), jadi cache-nya harus dipisah per peran.
    """
    admin = asyncio.run(server.skills_list(_req(_token_admin())))
    umum = asyncio.run(server.skills_list(_req(_token_biasa())))
    assert umum["ok"] is True
    assert "siap" in umum and "bawaan" in umum
    assert all("path" not in p for p in umum["paket"]), "paket masih membawa path"
    assert all("path" not in d and "tautan" not in d for d in umum["daftar"]), "skill masih membawa path/tautan"
    # Admin tetap menerima jalurnya.
    assert all("path" in p for p in admin["paket"])
    # Dan cache tidak mencampur keduanya.
    umum2 = asyncio.run(server.skills_list(_req(_token_biasa())))
    assert all("path" not in p for p in umum2["paket"]), "cache admin bocor ke pengguna biasa"


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
        ("POST", "/api/capability/pratinjau"),
        ("DELETE", "/api/capability/{nama}"),
        ("POST", "/api/workers/{key}/pasang"),
        ("POST", "/api/workers/{key}"),
        ("POST", "/api/config"),
        ("POST", "/api/apply"),
        ("POST", "/api/gateway/key"),
        ("POST", "/api/gateway/sync"),
        ("POST", "/api/gateway/model"),
        ("POST", "/api/gateway/probe"),
        ("GET", "/api/gateway/models"),
        ("GET", "/api/jobs"),
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


def test_masuk_menolak_origin_situs_lain():
    """Cookie token tidak boleh bisa ditanam dari halaman orang lain.

    Halaman UI memang terbuka tanpa token. Tanpa pemeriksaan asal, situs lain
    bisa mengirim POST /api/masuk dengan token miliknya sendiri; peramban korban
    menyimpan cookie itu dan seluruh aksinya berjalan sebagai penyerang.
    Diuji lewat HTTP sungguhan karena yang diperiksa adalah header permintaan.
    """
    port = int(os.environ.get("UI_PORT") or 8799)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
    except OSError:
        pytest.skip(f"UI belum jalan di :{port} (jalankan ./run.sh)")

    body = json.dumps({"token": "token-palsu-untuk-uji"}).encode()
    for asal, harus_ditolak in (
        ("http://situs-jahat.example", True),
        ("http://127.0.0.1:9/", True),
        ("http://127.0.0.1:" + str(port), False),
    ):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/masuk", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Origin", asal)
        kode, pesan = 0, ""
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                kode, pesan = r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            kode, pesan = e.code, e.read().decode()
        # Tokennya memang palsu, jadi 403 muncul di kedua kasus. Yang membedakan
        # adalah ALASANNYA, jadi pesannya yang diperiksa: tanpa itu tes ini lulus
        # walau pemeriksaan asalnya belum ada.
        ditolak_asal = "halaman AstroZ sendiri" in pesan
        assert ditolak_asal is harus_ditolak, (
            f"Origin {asal}: ditolak_asal={ditolak_asal}, diharapkan {harus_ditolak} (HTTP {kode}: {pesan[:120]})"
        )


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
