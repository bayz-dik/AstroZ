"""AstroZ web server: mobile-first dashboard + JSON API + SSE feed."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import pathlib
import re
import shutil
import threading
import time
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

import adapters
import adapters_plugin
import config
import hub
import orchestrator
import plugins
import project
import sessions
import storage
import terminal
import users
from gateway import Gateway

ROOT = pathlib.Path(__file__).resolve().parent
WEB = ROOT / "web"

app = FastAPI(title="AstroZ")
_started = time.time()

# ------------------------------------------------------------------ masuk

# Nama cookie yang menyimpan token. Cookie dipakai supaya UI tidak perlu
# menyimpan token di localStorage, dan tokennya tidak ikut terlihat di URL.
COOKIE = "astroz_token"
# Jalur yang boleh dibuka tanpa masuk. Hanya halaman UI dan berkasnya: tanpa ini
# halaman masuk sendiri tidak bisa dimuat.
TERBUKA = {"/", "/app.css", "/app.js", "/manifest.webmanifest", "/favicon.ico"}
# Endpoint yang boleh dibuka tanpa masuk. Pendaftaran lewat kode undangan masuk
# di sini karena orang yang mendaftar memang belum punya token. Syaratnya tetap
# satu: harus tahu kodenya.
TERBUKA_AWALAN = ("/api/masuk", "/api/undangan/")


def _token_dari(request: Request) -> str:
    """Token dari cookie, atau dari header Authorization untuk pemakaian skrip."""
    t = request.cookies.get(COOKIE) or ""
    if not t:
        h = request.headers.get("authorization") or ""
        if h.lower().startswith("bearer "):
            t = h[7:].strip()
    return t.strip()


def _pengguna(request: Request) -> dict | None:
    """Pengguna yang sedang meminta, disimpan di request.state supaya middleware
    dan endpoint tidak perlu memverifikasi token dua kali."""
    ada = getattr(request.state, "pengguna", None)
    if ada is not None:
        return ada
    u = users.verifikasi(_token_dari(request))
    request.state.pengguna = u
    return u


def _admin_saja(request: Request) -> bool:
    u = _pengguna(request)
    return bool(u and u.get("peran") == "admin")


def _tolak(msg: str, kode: int = 401) -> JSONResponse:
    return JSONResponse({"ok": False, "error": msg}, status_code=kode)


def _asal_sendiri(asal: str, request: Request) -> bool:
    """True kalau `Origin` menunjuk host DAN port yang sama dengan permintaan ini.

    Dipakai untuk menolak cookie yang ditanam dari situs lain. Host yang
    diizinkan adalah host yang benar-benar dipakai permintaan itu (localhost,
    IP LAN, atau nama host), jadi tidak ada daftar yang harus dirawat.

    Port ikut dibandingkan: `http://127.0.0.1:9` adalah origin yang berbeda dari
    `http://127.0.0.1:8799`, dan menyamakan keduanya membuat halaman lain di
    mesin yang sama tetap bisa menanam cookie.
    """
    try:
        p = urlparse(asal)
    except Exception:
        return False
    host_asal = (p.hostname or "").lower()
    if not host_asal:
        return False
    port_asal = p.port or (443 if p.scheme == "https" else 80)
    port_ini = request.url.port or (443 if request.url.scheme == "https" else 80)
    if port_asal != port_ini:
        return False
    host_ini = (request.url.hostname or "").lower()
    if host_asal == host_ini:
        return True
    # localhost dan 127.0.0.1 menunjuk mesin yang sama, tetapi hanya kalau
    # portnya juga sama.
    lokal = {"localhost", "127.0.0.1", "::1"}
    return host_asal in lokal and host_ini in lokal


@app.middleware("http")
async def gerbang_masuk(request: Request, call_next):
    """Semua permintaan API wajib membawa token yang sah.

    Halaman UI sendiri dibiarkan terbuka supaya bisa memuat dan menampilkan
    layar masuk; yang dilindungi adalah datanya. Tanpa gerbang ini, siapa pun
    yang bisa menjangkau portnya dapat membaca percakapan dan folder kerja.
    """
    jalan = request.url.path
    if jalan in TERBUKA or jalan.startswith(TERBUKA_AWALAN):
        return await call_next(request)
    if jalan.startswith("/api/"):
        u = _pengguna(request)
        if not u:
            return _tolak("belum masuk, kirim token lewat cookie atau header Authorization")
        request.state.pengguna = u
        # Pemilik kejadian dikunci untuk thread ini selama permintaan berjalan.
        # Tanpa ini, kejadian yang dipancarkan dari penangan permintaan (mis.
        # "pesan baru" di /api/chat) tidak punya pemilik dan jatuh ke berkas
        # admin, sehingga id tugas pengguna lain muncul di catatan admin.
        # Dikunci di sini, bukan di tiap penangan, supaya tidak ada yang terlewat.
        hub.set_pemilik(u.get("nama"))
        try:
            return await call_next(request)
        finally:
            hub.set_pemilik(None)
    return await call_next(request)


@app.post("/api/masuk")
async def masuk(payload: dict, request: Request):
    """Tukar token dengan cookie. Token tidak dikembalikan lagi setelah ini.

    Cookie hanya ditulis kalau permintaannya datang dari halaman sendiri.
    Halaman UI memang terbuka, jadi tanpa pemeriksaan asal, situs lain bisa
    mengirim permintaan ke sini dan menanam cookie berisi token yang dia pilih
    sendiri: peramban korban lalu memakai token penyerang tanpa sadar. Ini
    serangan yang sama seperti login CSRF, dan biayanya satu baris pemeriksaan.
    """
    asal = (request.headers.get("origin") or "").strip()
    if asal and not _asal_sendiri(asal, request):
        return _tolak("permintaan masuk harus dari halaman AstroZ sendiri", 403)
    token = ((payload or {}).get("token") or "").strip()
    u = users.verifikasi(token)
    if not u:
        # Pesan sengaja tidak membedakan token salah dan akun mati.
        return _tolak("token tidak dikenali", 403)
    r = JSONResponse({"ok": True, "pengguna": u})
    r.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return r


@app.post("/api/keluar")
async def keluar():
    r = JSONResponse({"ok": True})
    r.delete_cookie(COOKIE)
    return r


@app.get("/api/saya")
async def saya(request: Request):
    u = _pengguna(request)
    if not u:
        return _tolak("belum masuk")
    return {"ok": True, "pengguna": u}


# ------------------------------------------------------------------ akun
# Hanya admin yang mengelola akun: kalau pengguna biasa bisa membuat akun
# sendiri, batas antar pengguna tidak berarti apa-apa.
@app.get("/api/akun")
async def akun_daftar(request: Request):
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh mengelola akun", 403)
    return {"ok": True, "akun": users.daftar()}


@app.get("/api/storage")
async def storage_pemakaian(request: Request):
    """Pemakaian penyimpanan per pengguna.

    Tidak ada batas yang ditegakkan: ini hitungan, bukan kuota. Tujuannya supaya
    terlihat siapa menanggung berapa dan berkas besar bisa ditemukan sebelum
    perangkatnya penuh. Pengguna biasa hanya melihat pemakaiannya sendiri;
    daftar lengkap hanya untuk admin, karena menyebut nama orang lain.
    """
    u = _pengguna(request) or {}
    saya = (u.get("nama") or "admin").strip().lower()
    semua = storage.pemakaian()
    if u.get("peran") != "admin":
        semua = {saya: semua.get(saya) or storage.pemakaian([saya])[saya]}
    return {
        "ok": True,
        "pemakaian": semua,
        "total": sum(int(r.get("total") or 0) for r in semua.values()),
        "akar": str(config.RUNTIME / "users"),
        "kuota": None,  # tidak ada batas; field ini ada supaya UI tidak menebak
    }


@app.post("/api/akun")
async def akun_buat(payload: dict, request: Request):
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh mengelola akun", 403)
    try:
        u = users.buat((payload or {}).get("nama") or "", (payload or {}).get("peran") or "user")
    except ValueError as e:
        return _tolak(str(e), 400)
    # Token hanya muncul di balasan ini, dan tidak masuk feed kejadian.
    hub.emit("system", f"Akun baru dibuat: {u['nama']} ({u['peran']})")
    return {"ok": True, "akun": u, "catatan": "token hanya ditampilkan sekali, simpan sekarang"}


@app.post("/api/akun/{nama}/token")
async def akun_token_baru(nama: str, request: Request):
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh mengelola akun", 403)
    try:
        u = users.setel_ulang_token(nama)
    except ValueError as e:
        return _tolak(str(e), 404)
    hub.emit("system", f"Token akun {nama} diterbitkan ulang")
    return {"ok": True, "akun": u, "catatan": "token lama langsung tidak berlaku"}


@app.post("/api/akun/{nama}/aktif")
async def akun_aktif(nama: str, payload: dict, request: Request):
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh mengelola akun", 403)
    try:
        u = users.setel_aktif(nama, bool((payload or {}).get("aktif", True)))
    except ValueError as e:
        return _tolak(str(e), 400)
    return {"ok": True, "akun": u}


# ------------------------------------------------------------------ undangan
# Admin membuat kode pendek, lalu membagikannya. Orangnya mendaftar sendiri dan
# tokennya dibuat otomatis, jadi admin tidak perlu menyentuh token sama sekali.
@app.get("/api/undangan")
async def undangan_daftar(request: Request):
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh mengelola undangan", 403)
    return {"ok": True, "undangan": users.undangan_daftar()}


@app.post("/api/undangan")
async def undangan_buat(payload: dict, request: Request):
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh membuat undangan", 403)
    body = payload or {}
    try:
        k = users.undangan_buat(
            peran=(body.get("peran") or "user"),
            detik=int(body.get("detik") or users.KODE_DETIK),
            maks=int(body.get("maks") or users.KODE_MAKS_PAKAI),
        )
    except ValueError as e:
        return _tolak(str(e), 400)
    hub.emit("system", f"Kode undangan dibuat (berlaku sampai {int(k['kedaluwarsa'])})")
    return {"ok": True, "undangan": users._publik_undangan(k)}


@app.delete("/api/undangan/{kode}")
async def undangan_hapus(kode: str, request: Request):
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh menghapus undangan", 403)
    try:
        r = users.undangan_hapus(kode)
    except ValueError as e:
        return _tolak(str(e), 404)
    return {"ok": True, **r}


# Dua endpoint di bawah ini SENGAJA terbuka: yang memakainya belum punya token.
# Yang menjaga adalah kodenya sendiri.
@app.get("/api/undangan/cek")
async def undangan_cek(kode: str = ""):
    """Periksa kode tanpa memakainya, supaya pendaftar tahu kodenya sah."""
    k = users._UNDANGAN.get((kode or "").strip().upper())
    if not k or not users._undangan_hidup(k):
        return {"ok": False, "error": "kode tidak berlaku atau sudah kedaluwarsa"}
    return {"ok": True, "peran": k.get("peran") or "user"}


@app.post("/api/undangan/pakai")
async def undangan_pakai(payload: dict):
    """Tukar kode dengan akun baru. Token dikembalikan SEKALI, untuk disalin."""
    body = payload or {}
    try:
        u = await asyncio.to_thread(users.undangan_pakai, body.get("kode") or "", body.get("nama") or "")
    except ValueError as e:
        return _tolak(str(e), 400)
    # Nama akun saja yang dicatat, bukan tokennya: feed kejadian tampil di UI.
    hub.emit("system", f"Akun baru dari kode undangan: {u['nama']} ({u['peran']})")
    return {"ok": True, "akun": u, "catatan": "token hanya ditampilkan sekali, salin sekarang"}


@app.delete("/api/akun/{nama}")
async def akun_hapus(nama: str, request: Request):
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh mengelola akun", 403)
    try:
        r = users.hapus(nama)
    except ValueError as e:
        return _tolak(str(e), 400)
    hub.emit("system", f"Akun dihapus: {nama}")
    return {"ok": True, **r}


@app.on_event("startup")
async def _startup() -> None:
    hub.bind_loop(asyncio.get_running_loop())
    # Pemindahan sekali jalan: berkas bersama yang lama (tasks/sessions/events/
    # cadangan) pindah ke folder pemiliknya, dan folder kerja lama pindah ke
    # dalam penyimpanan admin. Dilakukan SEBELUM memuat apa pun, supaya data yang
    # dimuat sudah dari tempat yang benar dan tidak ada yang hilang.
    pindah = storage.pindahkan_berkas_lama()
    pindah_ws = storage.pindahkan_workspace_lama()
    for k, v in {**pindah, "workspace": pindah_ws}.items():
        if v and not str(v).startswith(("dilewati", "sudah", "setelan", "tidak ada")):
            hub.emit("system", f"Penyimpanan lama dipindah: {k} -> {v}", phase="boot")
    n = hub.load_from_disk(1500)
    nu = users.load()
    # Akun admin pertama dibuat di sini kalau belum ada akun sama sekali.
    # Tokennya ditulis ke runtime/admin_token.txt (hanya bisa dibaca pemilik
    # mesin), BUKAN ke feed kejadian yang tampil di UI.
    baru = users.siapkan_pertama()
    if baru:
        hub.emit("system", "Akun admin dibuat. Token masuk ada di runtime/admin_token.txt", phase="boot")
    # Kode undangan yang masih berlaku dimuat supaya tidak hilang saat restart.
    nk = users.undangan_load()
    nt = orchestrator.load_tasks()
    ns = sessions.load()
    hub.emit("system", f"UI AstroZ siap ({n} kejadian, {nt} tugas, {ns} percakapan, "
                       f"{nu or 1} akun, {nk} kode undangan)", phase="boot")
    asyncio.create_task(_bg_health())
    # Sinkron sekali saat start. Tanpa ini, orang yang baru mengkloning repo
    # membuka UI dan melihat daftar model kosong walau 9Router-nya hidup, karena
    # sinkron hanya jalan kalau tombolnya ditekan. Kunci API dan alamat gateway
    # juga diambil di sini: 9Router yang sudah dikonfigurasi sudah menyimpan
    # kuncinya, jadi tidak perlu dimasukkan ulang lewat UI.
    asyncio.create_task(_sync_awal())
    # mirror Hermes activity feeds into the hub: the astroz plugin feed and the
    # live-activity plugin feed (both are written by separate processes).
    home = pathlib.Path(config.hermes_home())
    for rel, tag in (("runtime/hermes_plugin.jsonl", "astroz"), ("runtime/live_activity.jsonl", "live-activity")):
        threading.Thread(target=hub.follow_file, args=(home / rel,), kwargs={"kind": "hermes", "tag": tag}, daemon=True).start()
    threading.Thread(target=_refresh_workers, daemon=True).start()
    # Skill bawaan repo dipasang sekali di sini, jadi clone baru langsung punya
    # skill tanpa memasangnya satu per satu dari UI. Jalan di thread sendiri:
    # menautkan ratusan folder bisa makan beberapa detik.
    threading.Thread(target=plugins.pasang_bawaan_sekali, daemon=True).start()


async def _sync_awal() -> None:
    """Ambil kunci, alamat, dan daftar model dari 9Router begitu server hidup."""
    try:
        cfg = config.load()
        gw = Gateway(cfg)
        if not cfg["gateway"].get("api_key"):
            kunci = gw.api_key
            if kunci:
                cfg = config.load()
                cfg["gateway"]["api_key"] = kunci
                config.save(cfg)
                hub.emit("gateway", "Kunci API diambil dari 9Router yang sudah dikonfigurasi", has_key=True)
        h = await asyncio.to_thread(gw.health)
        if not h.get("online"):
            hub.emit("gateway", "9Router belum menjawab, sinkron model dilewati", online=False)
            return
        res = await asyncio.to_thread(gw.sync, False)
        hub.emit("gateway", f"Model tersinkron sendiri saat mulai: {res.get('models', 0)} model", **res)
    except Exception as e:
        hub.emit("gateway", f"Sinkron awal gagal: {type(e).__name__}: {e}", ok=False)


def _refresh_workers() -> None:
    try:
        adapters.status_all(refresh=True)
        hub.emit("system", "Pemeriksaan pekerja: " + ", ".join(f"{w['key']}{' siap' if w['installed'] else ' tidak ada'}" for w in adapters.status_all()))
    except Exception as e:
        hub.emit("system", f"Pemeriksaan pekerja gagal: {e}", ok=False)


async def _bg_health() -> None:
    while True:
        try:
            gw = Gateway()
            h = await asyncio.to_thread(gw.health)
            cfg = config.load()
            if cfg["gateway"].get("online") != h["online"]:
                hub.emit("gateway", f"Gateway {'hidup' if h['online'] else 'mati'}", online=h["online"])
            cfg["gateway"]["online"] = h["online"]
            config.save(cfg)
        except Exception:
            pass
        await asyncio.sleep(30)


# ------------------------------------------------------------------ static
@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


@app.get("/manifest.webmanifest")
async def manifest():
    return JSONResponse(
        {
            "name": "AstroZ",
            "short_name": "AstroZ",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0b0f14",
            "theme_color": "#0b0f14",
            "icons": [],
        }
    )


# ------------------------------------------------------------------- state
@app.get("/api/state")
async def state(request: Request):
    u = _pengguna(request) or {}
    saya = u.get("nama") or "admin"
    admin = u.get("peran") == "admin"
    cfg = config.load()
    gw = Gateway(cfg)
    gwcfg = dict(cfg["gateway"])
    gwcfg["has_key"] = bool(gw.api_key)
    # Kunci API tidak pernah dikirim ke peramban: server ini bisa mendengarkan di
    # seluruh antarmuka jaringan, jadi apa pun yang ada di jawaban ini bisa
    # dibaca siapa saja di jaringan yang sama. UI hanya butuh tahu ada atau
    # tidak kuncinya.
    gwcfg.pop("api_key", None)
    # Daftar model dan catatan kesehatannya menyangkut kunci dan kuota pemilik
    # mesin, jadi pengguna biasa tidak menerimanya.
    if not admin:
        for k in ("models", "healthy", "model_meta", "fallback_models", "model_rejected",
                  "provider_names", "provider_name", "upstream_base_url", "hermes_api_base"):
            gwcfg.pop(k, None)
    return {
        "gateway": gwcfg,
        "saya": saya,
        "peran": u.get("peran") or "user",
        "workers": _status_pekerja(request),
        "worker_cfg": cfg["workers"] if admin else {},
        "tasks": orchestrator.list_tasks(30, owner=None if admin else saya),
        "project": {"dir": str(users.ruang_kerja(saya)),
                    "test_command": project.detect_test_command() if admin else ""},
        "workflow": cfg["workflow"],
        "uptime": round(time.time() - _started, 1),
        "subscribers": hub.subscribers(),
    }


def _boleh_lihat(ev: dict, u: dict) -> bool:
    """Boleh tidaknya satu kejadian dilihat pengguna ini.

    Diperiksa per kejadian, bukan dari daftar yang dihitung sekali saat koneksi
    dibuat. Daftar beku itu salah: tugas dan percakapan yang dibuat SETELAH
    koneksi terbuka tidak ada di dalamnya, sehingga umpan aktivitas tidak pernah
    menampilkan apa pun yang baru.
    """
    if u.get("peran") == "admin":
        return True
    t = ev.get("task")
    s = ev.get("session")
    # Kejadian sistem (boot, pemasangan paket) tidak menyangkut percakapan siapa pun.
    if not t and not s:
        return True
    saya = u.get("nama") or "admin"
    if s and sessions.get_milik(s, saya):
        return True
    if t:
        tugas = orchestrator.get_task(t)
        if tugas and (tugas.get("owner") or "admin") == saya:
            return True
    return False


@app.get("/api/events")
async def events(request: Request, replay: int = 80):
    # Feed kejadian memuat potongan prompt dan jawaban, jadi hanya admin yang
    # menerima semuanya. Pengguna biasa menerima kejadian miliknya sendiri.
    u = _pengguna(request) or {}
    q = hub.subscribe()

    async def gen():
        try:
            for ev in hub.recent(replay):
                if _boleh_lihat(ev, u):
                    yield f"data: {json.dumps(ev)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    if _boleh_lihat(ev, u):
                        yield f"data: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            hub.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.get("/api/events/recent")
async def events_recent(request: Request, limit: int = 300, kind: str = ""):
    u = _pengguna(request) or {}
    return {"events": [e for e in hub.recent(limit, kind or None) if _boleh_lihat(e, u)]}


# ----------------------------------------------------------------- gateway
@app.post("/api/gateway/sync")
async def gateway_sync(request: Request, apply: int = 0):
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh menyinkronkan gateway", 403)
    gw = Gateway()
    res = await asyncio.to_thread(gw.sync, bool(apply))
    return {"ok": True, **res}


@app.get("/api/gateway/models")
async def gateway_models(request: Request, q: str = "", limit: int = 300, only_healthy: int = 0,
                         provider: str = "", callable_only: int = 0):
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh melihat daftar model", 403)
    cfg = config.load()
    gw = cfg["gateway"]
    meta = gw.get("model_meta", {})
    # Sumber id, berurutan: model yang sedang dipakai, daftar hasil sync, lalu
    # kunci model_meta (di situ hasil probe disimpan). Tanpa dua tambahan itu,
    # model aktif bisa hilang dari daftar dan saringan "teruji hidup" jadi kosong.
    ids: list[str] = []
    seen: set[str] = set()
    for mid in [gw.get("model") or "", *gw.get("models", []), *meta.keys()]:
        if mid and mid not in seen:
            seen.add(mid)
            ids.append(mid)
    if not ids:
        ids = await asyncio.to_thread(lambda: [m.get("id") for m in Gateway().models()])
    items = []
    pmap = gw.get("provider_names") or {}
    for mid in ids:
        if q and q.lower() not in mid.lower():
            continue
        m = {"id": mid, **{k: v for k, v in (meta.get(mid) or {}).items()}}
        m.setdefault("provider", mid.split("/", 1)[0] if "/" in mid else "")
        if m.get("provider") in pmap:
            m["provider_id"] = m["provider"]
            m["provider"] = pmap[m["provider"]]
        if provider and m.get("provider") != provider:
            continue
        if callable_only and not m.get("callable"):
            continue
        items.append(m)
    items.sort(key=lambda m: (not (m.get("health") or {}).get("ok"), m.get("provider") or "", m["id"]))
    if only_healthy:
        # disaring di server, bukan di UI: hasil probe tidak selalu ikut terkirim
        # kalau UI hanya memotong 300 baris pertama.
        items = [m for m in items if (m.get("health") or {}).get("ok")]
    providers: dict[str, int] = {}
    for m in items:
        p = m.get("provider") or "(lain)"
        providers[p] = providers.get(p, 0) + 1
    return {
        "models": items[:limit],
        "total": len(items),
        "current": gw.get("model"),
        "healthy": gw.get("healthy", []),
        "providers": sorted(({"id": k, "count": v} for k, v in providers.items()), key=lambda x: -x["count"]),
    }


@app.post("/api/gateway/model")
async def gateway_set_model(payload: dict, request: Request):
    # Satu model dipakai seluruh mesin: pekerja, Hermes, dan folder kerja
    # bersama. Menggantinya bukan tindakan satu pengguna, jadi wajib admin.
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh mengganti model mesin", 403)
    model = (payload or {}).get("model", "").strip()
    if not model:
        return JSONResponse({"ok": False, "error": "model required"}, status_code=400)
    apply_workers = bool(payload.get("apply_workers", True))
    gw = Gateway()
    res = await asyncio.to_thread(gw.apply, model, apply_workers, True)
    return {"ok": True, **res}


@app.post("/api/gateway/key")
async def gateway_set_key(payload: dict, request: Request):
    # Kunci API gateway milik pemilik mesin. Hanya admin yang boleh menggantinya.
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh mengubah kunci API", 403)
    key = (payload or {}).get("api_key", "").strip()
    cfg = config.load()
    cfg["gateway"]["api_key"] = key
    config.save(cfg)
    hub.emit("gateway", f"Kunci API gateway {'disimpan' if key else 'dikosongkan'}", has_key=bool(key))
    return {"ok": True, "has_key": bool(key)}


@app.post("/api/gateway/probe")
async def gateway_probe(request: Request, payload: dict | None = None):
    """Ping models through 9Router and record which ones actually answer."""
    # Tes model memakai kunci API dan kuota pemilik mesin, dan hasilnya ditulis
    # ke setelan bersama. Pengguna biasa tidak boleh memicunya.
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh menguji model", 403)
    body = payload or {}
    cfg = config.load()
    ids = body.get("models") or []
    if not ids:
        # default: everything on the current provider prefix + the selected model
        cur = cfg["gateway"].get("model") or ""
        prefix = cur.split("/", 1)[0] if "/" in cur else ""
        all_ids = cfg["gateway"].get("models", [])
        ids = [m for m in all_ids if prefix and m.startswith(prefix + "/")][:40] or all_ids[:20]
        if cur and cur not in ids:
            ids.insert(0, cur)
    limit = int(body.get("limit") or 0)
    if limit:
        ids = ids[:limit]
    gw = Gateway(cfg)
    res = await asyncio.to_thread(gw.probe_models, ids, int(body.get("workers") or 6), int(body.get("timeout") or 40))
    cfg = config.load()
    meta = cfg["gateway"].setdefault("model_meta", {})
    for r in res:
        meta.setdefault(r["model"], {})["health"] = {"ok": r["ok"], "status": r["status"], "duration": r["duration"], "error": r["error"], "at": config.now()}
    cfg["gateway"]["model_meta"] = meta
    cfg["gateway"]["healthy"] = [r["model"] for r in res if r["ok"]]
    # Model yang menjawab bukan berarti modelnya dikenal: gateway bisa membalas
    # "unrecognized_model" untuk id yang sudah tidak ada. Bersihkan catatan
    # model yang ditolak begitu model itu teruji hidup lagi.
    hidup = set(cfg["gateway"]["healthy"])
    sisa = [m for m in (cfg["gateway"].get("model_rejected") or []) if m not in hidup]
    if sisa != (cfg["gateway"].get("model_rejected") or []):
        cfg["gateway"]["model_rejected"] = sisa
    config.save(cfg)
    ok = [r["model"] for r in res if r["ok"]]
    hub.emit("gateway", f"Tes model: {len(ok)} dari {len(res)} menjawab, {', '.join(ok[:8])}", healthy=ok)
    return {"ok": True, "results": res, "healthy": ok}


@app.post("/api/apply")
async def apply_everything(request: Request, payload: dict | None = None):
    """Re-apply the current model to every worker + Hermes in one call."""
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh mengubah setelan pekerja", 403)
    cfg = config.load()
    model = (payload or {}).get("model") or cfg["gateway"].get("model")
    gw = Gateway()
    res = await asyncio.to_thread(gw.apply, model, True, True)
    return {"ok": True, **res}


# ----------------------------------------------------------------- workers

# Kunci status pekerja yang boleh dilihat pengguna biasa. `path` dan
# `config_path` menunjuk tata letak mesin pemilik (mis. /root/.claude/...),
# dan `error` bisa memuat jalur atau keluaran perintah. Ketiganya hanya untuk
# admin; pengguna biasa cukup tahu pekerja mana yang hidup dan versinya.
_STATUS_UMUM = ("key", "label", "installed", "version")


def _status_pekerja(request: Request) -> list[dict]:
    """Status pekerja, disaring menurut peran yang meminta.

    Dipakai `/api/workers`, `/api/workers/paket`, dan `/api/state`. Menyaring di
    satu tempat lebih aman daripada mengingat-ingat kunci mana yang bocor di
    tiap endpoint. Jalur konfigurasi dan pesan galat CLI adalah tata letak mesin
    pemilik, bukan informasi pengguna biasa.
    """
    st = adapters.status_all()
    if _admin_saja(request):
        return st
    return [{k: w.get(k) for k in _STATUS_UMUM} for w in st]


@app.get("/api/workers")
async def workers(request: Request, refresh: int = 0):
    if refresh:
        await asyncio.to_thread(adapters.status_all, True)
    return {"workers": _status_pekerja(request)}


@app.post("/api/workers/{key}")
async def worker_update(key: str, payload: dict, request: Request):
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh mengubah setelan pekerja", 403)
    if key not in adapters.ADAPTERS:
        return JSONResponse({"ok": False, "error": "unknown worker"}, status_code=404)
    cfg = config.load()
    w = cfg["workers"].setdefault(key, {"enabled": True, "model": ""})
    if "enabled" in (payload or {}):
        w["enabled"] = bool(payload["enabled"])
    if "model" in (payload or {}):
        w["model"] = payload["model"] or ""
    config.save(cfg)
    hub.emit("system", f"Pekerja {key}: dipakai={w['enabled']} model={w['model'] or '(bawaan gateway)'}")
    return {"ok": True, "cfg": cfg["workers"]}


@app.post("/api/workers/{key}/probe")
async def worker_probe(key: str):
    if key not in adapters.ADAPTERS:
        return JSONResponse({"ok": False, "error": "unknown worker"}, status_code=404)
    w = adapters.ADAPTERS[key]
    st = await asyncio.to_thread(w.probe)
    hub.emit("system", f"Periksa {key}: {st.get('version') or st.get('error')}")
    return {"ok": True, **st}


# ------------------------------------------------------------------- tasks
@app.post("/api/tasks")
async def submit_task(payload: dict, request: Request):
    # Pemilik wajib diambil dari token yang meminta. Tanpa ini tugas dari
    # pengguna biasa tercatat milik admin, dan pekerja menulis ke folder kerja
    # admin: pekerjaan satu orang masuk ke ruang orang lain.
    saya = (_pengguna(request) or {}).get("nama") or "admin"
    prompt = (payload or {}).get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"ok": False, "error": "prompt required"}, status_code=400)
    orch = orchestrator.Orchestrator()
    tid = orch.submit(
        prompt,
        workflow=(payload.get("workflow") or "auto"),
        workers=payload.get("workers") or None,
        model=payload.get("model") or None,
        owner=saya,
    )
    return {"ok": True, "id": tid}


@app.get("/api/tasks")
async def tasks(request: Request):
    u = _pengguna(request) or {}
    owner = None if u.get("peran") == "admin" else (u.get("nama") or "admin")
    return {"tasks": orchestrator.list_tasks(50, owner=owner)}


# Rute tetap harus didaftarkan sebelum /api/tasks/{tid}: rute dinamis itu
# menelan "running" sebagai id tugas dan menjawab 404.
@app.get("/api/tasks/running")
async def tasks_running(request: Request):
    """Tugas yang sedang berjalan, ringkas, untuk strip kerja di UI.

    Satu permintaan saja: daftar tugas berjalan, pekerja yang sedang aktif
    (dihitung dari kejadian terakhir tiap pekerja, bukan dari daftar penugasan),
    dan beberapa langkah terakhir. UI memanggil ini berkala selama ada pekerjaan,
    jadi isinya dijaga kecil.
    """
    u = _pengguna(request) or {}
    owner = None if u.get("peran") == "admin" else (u.get("nama") or "admin")
    evs = hub.recent(800)
    out: list[dict] = []
    for t in orchestrator.list_tasks(50, owner=owner):
        if t.get("status") != "running":
            continue
        milik = [e for e in evs if e.get("task") == t["id"]]
        if not milik:
            # Ring di memori bisa sudah terisi kejadian lain (aktivitas plugin
            # Hermes deras). Ambil dari feed di disk supaya strip kerja tetap
            # tahu pekerja mana yang sedang aktif.
            milik = await asyncio.to_thread(hub.untuk_tugas, t["id"], 40, t.get("owner"))
        # keadaan tiap pekerja: yang kejadian terakhirnya bukan "end" masih
        # bekerja. Daftar penugasan saja tidak cukup: ia tidak tahu siapa yang
        # sudah selesai dan siapa yang masih jalan.
        per: dict[str, dict] = {}
        for e in milik:
            w = e.get("worker")
            if w:
                per[w] = e
        pekerja = []
        for w, e in per.items():
            a = adapters.ADAPTERS.get(w)
            pekerja.append({
                "key": w,
                "label": (a.label if a else w),
                "aktif": e.get("phase") not in ("end", "stall", "error"),
                "text": (e.get("text") or "")[:160],
            })
        # pekerja yang sudah ditugaskan tapi belum mengeluarkan kejadian apa pun
        for w in t.get("workers") or []:
            if w not in per:
                a = adapters.ADAPTERS.get(w)
                pekerja.append({"key": w, "label": (a.label if a else w), "aktif": True, "text": ""})
        terakhir = milik[-1] if milik else {}
        out.append({
            "id": t["id"],
            "prompt": (t.get("prompt") or "")[:200],
            "size": t.get("size") or "",
            "model": t.get("model") or "",
            "created": t.get("created"),
            "session": t.get("session") or "",
            "tahap": terakhir.get("kind") or "",
            "pekerja": pekerja,
            "langkah": [
                {
                    "kind": e.get("kind") or "",
                    "phase": e.get("phase") or "",
                    "worker": e.get("worker") or "",
                    "text": orchestrator.clean_output(e.get("text") or "")[:200],
                    "ts": e.get("ts"),
                }
                for e in milik[-8:]
            ],
        })
    return {"ok": True, "running": out}


@app.post("/api/tasks/{tid}/hentikan")
async def task_hentikan(tid: str, request: Request):
    """Hentikan tugas yang sedang berjalan dari UI.

    Pekerja CLI yang sedang bekerja dimatikan prosesnya, tahap berikutnya pada
    tugas itu dilewati, dan statusnya jadi `cancelled` supaya chat tidak terus
    menampilkan "sedang jalan" untuk pekerjaan yang sudah dibatalkan.
    """
    u = _pengguna(request) or {}
    owner = None if u.get("peran") == "admin" else (u.get("nama") or "admin")
    t = orchestrator.get_task(tid)
    if not t or (owner is not None and (t.get("owner") or "admin") != owner):
        return JSONResponse({"ok": False, "error": "tidak ditemukan"}, status_code=404)
    hasil = orchestrator.hentikan(tid)
    if not hasil.get("ok"):
        return JSONResponse(hasil, status_code=404)
    return hasil


@app.get("/api/tasks/{tid}")
async def task_detail(tid: str, request: Request):
    u = _pengguna(request) or {}
    owner = None if u.get("peran") == "admin" else (u.get("nama") or "admin")
    t = orchestrator.get_task(tid)
    if not t or (owner is not None and (t.get("owner") or "admin") != owner):
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    evs = await asyncio.to_thread(hub.untuk_tugas, tid, 300, t.get("owner"))
    # UI membaca t["answer"]; bentuk balasan ini menyamakan keduanya supaya
    # pemanggil tidak perlu tahu bedanya.
    return {"ok": True, "task": t, "answer": t.get("answer") or "", "status": t.get("status") or "", "events": evs}


@app.get("/api/tasks/{tid}/berkas")
async def task_berkas(tid: str, request: Request):
    """Berkas yang diubah satu tugas, dihitung dari mtime sesudah tugas mulai.

    Dipakai panel samping untuk menampilkan perubahan tanpa perlu git diff
    seluruh folder kerja.
    """
    u = _pengguna(request) or {}
    owner = None if u.get("peran") == "admin" else (u.get("nama") or "admin")
    t = orchestrator.get_task(tid)
    if not t or (owner is not None and (t.get("owner") or "admin") != owner):
        return JSONResponse({"ok": False, "error": "tidak ditemukan"}, status_code=404)
    mulai = float(t.get("created") or 0)
    d = pathlib.Path(t.get("workspace") or project.project_dir())
    # Dibaca di folder kerja tugas itu, bukan folder milik orang yang meminta.
    out = await asyncio.to_thread(project.dengan_workspace, d, project.berkas_sejak, mulai)
    return {"ok": True, **out}


def _ruang_saya(request: Request) -> pathlib.Path:
    """Folder kerja milik pengguna yang meminta.

    Endpoint yang membaca folder kerja harus memakai ini, bukan folder global:
    tanpa itu pengguna biasa bisa membaca berkas milik orang lain lewat panel
    Berkas.
    """
    u = _pengguna(request) or {}
    return users.ruang_kerja(u.get("nama") or "admin")


@app.get("/api/project/tree")
async def project_tree(request: Request):
    ruang = _ruang_saya(request)
    out = await asyncio.to_thread(project.dengan_workspace, ruang, project.tree)
    return {"dir": str(ruang), "entries": out}


@app.get("/api/project/file")
async def project_file(path: str, request: Request):
    ruang = _ruang_saya(request)
    return await asyncio.to_thread(project.dengan_workspace, ruang, project.read_file, path)


@app.get("/api/git")
async def git_status(request: Request):
    ruang = _ruang_saya(request)
    return await asyncio.to_thread(project.dengan_workspace, ruang, project.git_status)


@app.get("/api/git/diff")
async def git_diff(request: Request, path: str = ""):
    ruang = _ruang_saya(request)
    out = await asyncio.to_thread(project.dengan_workspace, ruang, project.git_diff, path)
    return {"diff": out}


@app.post("/api/git/commit")
async def git_commit(request: Request, payload: dict | None = None):
    """Commit the workspace so a finished task is a commit, not a dirty tree."""
    msg = ((payload or {}).get("message") or "").strip()
    if not msg:
        return JSONResponse({"ok": False, "error": "message required"}, status_code=400)
    ruang = _ruang_saya(request)
    res = await asyncio.to_thread(project.dengan_workspace, ruang, project.git_commit_all, msg)
    ok = res.get("rc") == 0
    if not ok and "nothing to commit" in (res.get("out") or ""):
        return {"ok": True, "noop": True, **res}
    return JSONResponse({"ok": ok, **res}, status_code=200 if ok else 500)


@app.post("/api/test")
async def run_test(request: Request, payload: dict | None = None):
    cmd = (payload or {}).get("command") or None
    ruang = _ruang_saya(request)
    res = await asyncio.to_thread(project.dengan_workspace, ruang, project.run_tests, cmd)
    return {"ok": True, "result": res}


@app.post("/api/config")
async def set_config(payload: dict, request: Request):
    # Mengubah folder kerja global dan alur kerja menyangkut semua orang, jadi
    # hanya admin. Pengguna biasa tetap punya setelannya sendiri lewat folder
    # kerja miliknya.
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh mengubah setelan", 403)
    allowed = {"project_dir", "workflow"}
    patch = {k: v for k, v in (payload or {}).items() if k in allowed}
    if not patch:
        return JSONResponse({"ok": False, "error": f"allowed keys: {sorted(allowed)}"}, status_code=400)
    cfg = config.update(patch)
    if "project_dir" in patch:
        project.ensure_repo()
    hub.emit("system", f"Setelan diperbarui: {json.dumps(patch)[:300]}")
    return {"ok": True, "config": {"project_dir": cfg["project_dir"], "workflow": cfg["workflow"]}}


# -------------------------------------------------------------------- chat
def _task_messages(tid: str) -> list[dict]:
    """One task as the two turns a chat shows: the ask, then the answer."""
    t = orchestrator.get_task(tid)
    if not t:
        return []
    out = [{
        "role": "user",
        "text": t.get("prompt") or "",
        "ts": t.get("created"),
        "task": tid,
    }]
    status = t.get("status") or "running"
    # Tugas lama (dibuat sebelum jawaban disimpan) tidak punya task["answer"]:
    # ambil baris paling informatif dari pekerja supaya tidak tampil kosong.
    answer = t.get("answer") or orchestrator.best_answer_text(t.get("results") or [])
    out.append({
        "role": "astroz",
        "text": answer,
        "ts": t.get("finished") or t.get("created"),
        "task": tid,
        "status": status,
        "size": t.get("size"),
        "workers": t.get("workers") or [],
        "model": t.get("model"),
        "summary": t.get("summary") or "",
        "review": (t.get("review") or {}).get("verdict") or "",
        "tests": (t.get("test") or {}).get("ok"),
        "tests_skipped": bool((t.get("test") or {}).get("skipped")),
        # Sumber dipisah dari teks jawaban: UI menampilkannya sebagai chip di
        # baris aksi, seperti sitasi di aplikasi pesan.
        "sources": t.get("sources") or [],
    })
    return out


@app.get("/api/sessions")
async def sessions_list(request: Request):
    u = _pengguna(request) or {}
    saya = u.get("nama") or "admin"
    # Admin melihat semua percakapan; pengguna biasa hanya miliknya sendiri.
    owner = None if u.get("peran") == "admin" else saya
    items = sessions.list_sessions(owner)
    tasks = {t["id"]: t for t in orchestrator.list_tasks(200, owner=owner)}
    for s in items:
        ids = s.get("tasks") or []
        s["last"] = (tasks.get(ids[-1], {}).get("answer") or tasks.get(ids[-1], {}).get("prompt") or "")[:140]
        running = [i for i in ids if (tasks.get(i) or {}).get("status") == "running"]
        s["running"] = len(running)
        s["status"] = "running" if running else "idle"
    # Urutkan di server: UI menampilkan daftar apa adanya, jadi percakapan yang
    # baru dipakai harus ada di atas tanpa bergantung pada urutan penyimpanan.
    # Yang disematkan selalu di atas, apa pun waktu pakainya.
    items.sort(key=lambda s: (bool(s.get("pinned")), s.get("updated") or s.get("created") or 0), reverse=True)
    return {"sessions": items, "saya": saya, "peran": u.get("peran") or "user"}


@app.post("/api/sessions")
async def sessions_create(request: Request, payload: dict | None = None):
    """Percakapan baru yang kosong.

    Sampai ada pesan pertama, judulnya masih kosong. UI menampilkannya sebagai
    "Percakapan baru" dan hanya menyimpan yang benar-benar dipakai, jadi daftar
    tidak penuh percakapan kosong setiap kali tombolnya ditekan.
    """
    saya = (_pengguna(request) or {}).get("nama") or "admin"
    s = sessions.create(((payload or {}).get("title") or "").strip(), owner=saya)
    return {"ok": True, "session": s}


@app.delete("/api/sessions/kosong")
async def sessions_hapus_kosong(request: Request):
    """Buang percakapan yang belum pernah dipakai (tanpa satu pun tugas)."""
    u = _pengguna(request) or {}
    owner = None if u.get("peran") == "admin" else (u.get("nama") or "admin")
    dihapus = 0
    for s in sessions.list_sessions(owner):
        if not (s.get("tasks") or []):
            if sessions.delete(s["id"], owner=None if owner is None else owner):
                dihapus += 1
    if dihapus:
        hub.emit("system", f"{dihapus} percakapan kosong dibuang dari daftar")
    return {"ok": True, "dihapus": dihapus}


@app.get("/api/sessions/{sid}")
async def sessions_get(sid: str, request: Request, events: int = 120):
    u = _pengguna(request) or {}
    owner = None if u.get("peran") == "admin" else (u.get("nama") or "admin")
    s = sessions.get_milik(sid, owner) if owner is not None else sessions.get(sid)
    if not s:
        # Percakapan milik orang lain dijawab "tidak ditemukan", bukan "terlarang":
        # membedakannya berarti memberi tahu bahwa id itu ada.
        return JSONResponse({"ok": False, "error": "percakapan tidak ditemukan"}, status_code=404)
    ids = list(s.get("tasks") or [])
    messages: list[dict] = []
    for tid in ids:
        messages.extend(_task_messages(tid))
    activity: dict[str, list[dict]] = {}
    if events:
        for tid in ids:
            evs = await asyncio.to_thread(hub.untuk_tugas, tid, events, s.get("owner"))
            if evs:
                activity[tid] = evs
    return {"ok": True, "session": {**s, "tasks": ids}, "messages": messages, "activity": activity}


@app.post("/api/sessions/{sid}")
@app.patch("/api/sessions/{sid}")
async def sessions_update(sid: str, payload: dict, request: Request):
    u = _pengguna(request) or {}
    owner = None if u.get("peran") == "admin" else (u.get("nama") or "admin")
    s = sessions.rename(sid, (payload or {}).get("title") or "", owner=owner)
    if not s:
        return JSONResponse({"ok": False, "error": "percakapan tidak ditemukan"}, status_code=404)
    return {"ok": True, "session": s}


@app.delete("/api/sessions/{sid}")
async def sessions_delete(sid: str, request: Request):
    u = _pengguna(request) or {}
    owner = None if u.get("peran") == "admin" else (u.get("nama") or "admin")
    ok = sessions.delete(sid, owner=owner)
    return {"ok": ok}


@app.post("/api/sessions/{sid}/sematkan")
async def sessions_sematkan(sid: str, request: Request, payload: dict | None = None):
    """Sematkan atau lepas sematan percakapan ini.

    Yang disematkan naik ke atas daftar riwayat, jadi percakapan yang sering
    dibuka tidak tenggelam oleh percakapan baru.
    """
    u = _pengguna(request) or {}
    owner = None if u.get("peran") == "admin" else (u.get("nama") or "admin")
    isi = payload or {}
    nilai = isi.get("pinned")
    s = sessions.toggle_pin(sid, None if nilai is None else bool(nilai), owner=owner)
    if not s:
        return JSONResponse({"ok": False, "error": "percakapan tidak ditemukan"}, status_code=404)
    return {"ok": True, "session": s, "pinned": bool(s.get("pinned"))}


@app.post("/api/chat")
async def chat_send(payload: dict, request: Request):
    """One user message: it becomes a task, and its answer lands in this thread."""
    u = _pengguna(request) or {}
    saya = u.get("nama") or "admin"
    text = ((payload or {}).get("text") or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "tulis dulu pesannya"}, status_code=400)
    # Satu percakapan baru per kiriman kalau UI tidak menyebut sesi. Tanpa ini
    # semua pesan masuk ke percakapan pertama dan daftarnya menumpuk jadi satu.
    sid = (payload or {}).get("session") or None
    if not sid and (payload or {}).get("baru"):
        sid = sessions.create("", owner=saya)["id"]
    s = sessions.ensure(sid, text, owner=saya)
    orch = orchestrator.Orchestrator()
    tid = orch.submit(
        text,
        workflow=(payload or {}).get("workflow") or "auto",
        workers=(payload or {}).get("workers") or None,
        model=(payload or {}).get("model") or None,
        session_id=s["id"],
        owner=saya,
    )
    sessions.attach(s["id"], tid, text)
    hub.emit("task", f"Percakapan {s['id']}: pesan baru", task=tid, session=s["id"], phase="created")
    return {"ok": True, "session": s["id"], "task_id": tid, "title": s["title"]}


@app.post("/api/upload")
async def upload(payload: dict, request: Request):
    """Simpan gambar lampiran ke folder kerja supaya pekerja bisa membacanya.

    UI mengirim base64, bukan multipart, supaya tidak perlu menambah pustaka.
    """
    nama = ((payload or {}).get("name") or "lampiran.png").strip()
    data = (payload or {}).get("data") or ""
    if not data:
        return JSONResponse({"ok": False, "error": "data gambar kosong"}, status_code=400)
    if data.startswith("data:") and "," in data[:120]:
        data = data.split(",", 1)[1]
    try:
        mentah = base64.b64decode(data, validate=False)
    except Exception:
        return JSONResponse({"ok": False, "error": "data bukan base64"}, status_code=400)
    if len(mentah) > 12 * 1024 * 1024:
        return JSONResponse({"ok": False, "error": "gambar lebih dari 12 MB"}, status_code=400)
    aman = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(nama))[:80] or "lampiran.png"
    # Lampiran masuk ke folder kerja milik pengirim, bukan folder bersama.
    tujuan = users.ruang_kerja((_pengguna(request) or {}).get("nama") or "admin") / "lampiran"
    tujuan.mkdir(parents=True, exist_ok=True)
    path = tujuan / f"{int(time.time())}_{aman}"
    path.write_bytes(mentah)
    hub.emit("system", f"Lampiran disimpan: {path}")
    return {"ok": True, "path": str(path), "size": len(mentah)}


# ------------------------------------------------------------------ alat
@app.get("/api/tools/status")
async def tools_status(request: Request):
    """Ringkas: gateway, pekerja, plugin MCP, dan paket skill.

    Ringkasan ini menyangkut mesin pemilik (model, jalur konfigurasi CLI,
    perintah plugin, antrean pekerjaan latar), jadi hanya admin yang menerima
    isinya. Pengguna biasa tetap dapat bentuk jawabannya supaya panel tidak
    pecah, dengan bagian mesin dikosongkan.
    """
    cfg = config.load()
    mcp = plugins.mcp_daftar()
    skills = plugins.skill_daftar()
    if not _admin_saja(request):
        return {
            "gateway": {"online": bool(cfg["gateway"].get("online")), "model": ""},
            "workers": [],
            "mcp": [],
            "skills": [],
            "skill_count": 0,
            "mcp_count": 0,
            "jobs": [],
        }
    return {
        "gateway": {"online": bool(cfg["gateway"].get("online")), "model": cfg["gateway"].get("model")},
        "workers": [{"key": w["key"], "label": w.get("label") or w["key"], "installed": w["installed"],
                     "version": w.get("version") or "", "enabled": w.get("enabled", True)} for w in adapters.status_all()],
        "mcp": mcp,
        "skills": skills,
        "skill_count": sum(s["jumlah"] for s in skills),
        "mcp_count": len(mcp),
        "jobs": plugins.job_daftar(8),
    }


@app.get("/api/workers/paket")
async def workers_paket(request: Request):
    """Paket npm tiap pekerja, plus status terpasang. Dipakai UI untuk menawarkan
    pemasangan otomatis supaya satu clone bisa langsung jalan."""
    st = {w["key"]: w for w in _status_pekerja(request)}
    out = []
    for key, paket in adapters.PAKET.items():
        s = st.get(key) or {}
        out.append({
            "key": key,
            "label": (adapters.ADAPTERS[key].label if key in adapters.ADAPTERS else key),
            "paket": paket,
            "installed": bool(s.get("installed")),
            "version": s.get("version") or "",
            "sumber": adapters.SUMBER.get(key, ""),
        })
    return {"ok": True, "pekerja": out, "npm": shutil.which("npm") or ""}


@app.post("/api/workers/{key}/pasang")
async def worker_pasang(key: str, request: Request):
    """Pasang satu CLI pekerja lewat npm di latar belakang."""
    # Memasang program ke mesin pemilik: hanya admin.
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh memasang pekerja", 403)
    if key not in adapters.PAKET:
        return JSONResponse({"ok": False, "error": "pekerja tidak dikenal"}, status_code=404)
    if not shutil.which("npm"):
        return JSONResponse({"ok": False, "error": "npm tidak ada di PATH, pasang Node.js dulu"}, status_code=400)
    jid = await asyncio.to_thread(adapters.pasang_latar, key)
    return {"ok": True, "job": jid}


# ------------------------------------------------------------------ plugin MCP
@app.get("/api/mcp")
async def mcp_list(request: Request):
    srv = plugins.mcp_daftar()
    # `detail` memuat perintah yang dijalankan mesin ini beserta argumennya
    # (sering berisi jalur dan variabel lingkungan). Nama dan pekerja mana yang
    # memakainya tetap ditampilkan supaya halaman Plugin tidak kosong.
    if not _admin_saja(request):
        srv = [{"nama": s.get("nama"), "pekerja": s.get("pekerja"), "transport": s.get("transport")} for s in srv]
    return {"ok": True, "servers": srv, "siap": plugins.MCP_SIAP}


@app.post("/api/mcp")
async def mcp_add(payload: dict, request: Request):
    # Server MCP ditulis ke konfigurasi KEEMPAT pekerja, dan perintahnya
    # dijalankan mesin ini saat pekerja memakainya. Menambah atau melepasnya
    # karena itu mengubah keadaan bersama, bukan milik satu pengguna.
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh memasang plugin MCP", 403)
    body = payload or {}
    nama = (body.get("nama") or "").strip()
    target = (body.get("target") or body.get("command") or "").strip()
    if not nama or not target:
        return JSONResponse({"ok": False, "error": "nama dan command/url wajib diisi"}, status_code=400)
    transport = (body.get("transport") or ("http" if target.startswith("http") else "stdio")).strip()
    args = body.get("args") or []
    if isinstance(args, str):
        args = args.split()
    env = body.get("env") or {}
    header = body.get("header") or {}
    if isinstance(env, str):
        env = dict(x.split("=", 1) for x in env.split() if "=" in x)
    if isinstance(header, str):
        header = dict(x.split("=", 1) for x in header.split() if "=" in x)
    d = plugins.mcp_definisi(nama, transport, target, args, env, header)
    pekerja = body.get("pekerja") or None
    jid = plugins.mcp_pasang_latar(d, pekerja)
    return {"ok": True, "job": jid}


@app.delete("/api/mcp/{nama}")
async def mcp_remove(nama: str, request: Request):
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh melepas plugin MCP", 403)
    res = await asyncio.to_thread(plugins.mcp_hapus, nama)
    hub.emit("system", f"Plugin MCP {nama} dilepas dari pekerja")
    return {"ok": True, "hasil": res}


# ------------------------------------------------------------------ skill
# Hasil pemindaian skill disimpan sebentar: halaman Skill terpasang memanggil
# endpoint ini setiap kali dibuka, dan menghitung ukuran 93 paket setiap kali
# membuat halaman terasa menggantung. Isinya hanya berubah kalau ada paket baru.
_SKILL_CACHE: dict[str, object] = {"t": 0.0}
_SKILL_CACHE_DETIK = 30


@app.get("/api/skills")
async def skills_list(request: Request):
    admin = _admin_saja(request)
    sekarang = time.time()
    t_lama = _SKILL_CACHE["t"]
    kunci = "admin" if admin else "umum"
    simpan = _SKILL_CACHE.get(kunci)
    if isinstance(simpan, dict) and simpan.get("isi") is not None and isinstance(t_lama, float) and sekarang - t_lama < _SKILL_CACHE_DETIK:
        return simpan["isi"]
    daftar = await asyncio.to_thread(plugins.skill_terpasang)
    isi = {
        "ok": True,
        "paket": await asyncio.to_thread(plugins.skill_daftar),
        "siap": plugins.skill_ringkas_untuk_pekerja(),
        "daftar": daftar,
        "bawaan": plugins.skill_bawaan_siap(),
        "path": str(plugins.SKILL_DIR),
        "akar": str(plugins.HOME),
    }
    # `path` menunjuk folder mesin pemilik; `tautan` menyebut folder konfigurasi
    # tiap CLI. Keduanya hanya untuk admin. Isi lain (nama, paket, keterangan)
    # tetap tampil supaya halaman Skill tidak kosong bagi pengguna biasa.
    if not admin:
        isi["paket"] = [{k: v for k, v in p.items() if k != "path"} for p in isi["paket"]]
        isi["daftar"] = [{k: v for k, v in d.items() if k not in ("path", "tautan")} for d in isi["daftar"]]
        isi["bawaan"] = [{k: v for k, v in b.items() if k != "path"} for b in (isi["bawaan"] or [])]
    _SKILL_CACHE["t"] = sekarang
    _SKILL_CACHE[kunci] = {"isi": isi}
    return isi


@app.post("/api/skills/bawaan")
async def skills_bawaan(request: Request):
    """Tautkan semua skill bawaan repo ke folder yang dibaca pekerja."""
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh memasang skill bawaan", 403)
    res = await asyncio.to_thread(plugins.skill_pasang_bawaan)
    _SKILL_CACHE.pop("admin", None)
    _SKILL_CACHE.pop("umum", None)
    await asyncio.to_thread(plugins.skill_terpasang, True)
    return JSONResponse(res, status_code=200 if res.get("ok") else 400)


@app.post("/api/skills")
async def skills_add(payload: dict, request: Request):
    # Skill ditautkan ke folder yang dibaca KEEMPAT pekerja, jadi memasangnya
    # mengubah keadaan bersama mesin ini, bukan milik satu pengguna.
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh memasang skill", 403)
    body = payload or {}
    url = (body.get("url") or body.get("repo") or "").strip()
    if not url:
        return JSONResponse({"ok": False, "error": "url repo wajib diisi"}, status_code=400)
    try:
        jid = plugins.skill_pasang(url, (body.get("nama") or "").strip())
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return {"ok": True, "job": jid}


@app.delete("/api/skills/{nama}")
async def skills_remove(nama: str, request: Request):
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh melepas skill", 403)
    res = await asyncio.to_thread(plugins.skill_hapus, nama)
    return JSONResponse({"ok": res["ok"], **res}, status_code=200 if res["ok"] else 404)


# ------------------------------------------------------------------ adapter plugin universal
# Satu pintu untuk capability dari ekosistem mana pun (Claude Plugin, Codex
# Skill/Plugin, Hermes Skill/Plugin, server MCP). Alur yang dipakai UI:
#   POST /api/capability/pratinjau  -> unduh dan baca, belum memasang apa pun
#   POST /api/capability/pasang     -> pasang ke pekerja yang kompatibel
#   GET  /api/capability            -> daftar paket yang pernah dipasang
#   DELETE /api/capability/{nama}   -> lepas tautan dan catatannya
@app.get("/api/capability")
async def capability_list(request: Request):
    paket = adapters_plugin.terpasang()
    # `akar` adalah jalur folder di mesin pemilik. Pengguna biasa tetap melihat
    # daftar paketnya, tanpa jalurnya.
    if not _admin_saja(request):
        paket = [{k: v for k, v in p.items() if k != "akar"} for p in paket]
    return {
        "ok": True,
        "terpasang": paket,
        "jenis": list(adapters_plugin.JENIS),
        "pekerja": list(adapters_plugin.PEKERJA),
    }


@app.post("/api/capability/pratinjau")
async def capability_preview(payload: dict, request: Request):
    """Unduh dan baca sumber tanpa memasang. Ini yang membuat pratinjau jujur.

    Unduhan ini menjalankan git di mesin pemilik dan menulis ke folder data,
    jadi hanya admin. Tanpa penjagaan ini, satu permintaan pengguna biasa cukup
    untuk mengisi disk pemilik dengan klon repo sembarang.
    """
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh mempratinjau paket", 403)
    body = payload or {}
    url = (body.get("url") or "").strip()
    if not url:
        return JSONResponse({"ok": False, "error": "url atau jalur paket wajib diisi"}, status_code=400)
    sub = (body.get("sub") or "").strip()
    try:
        if sub:
            akar = await asyncio.to_thread(adapters_plugin.unduh, url)
            akar = (akar / sub).resolve()
            if not akar.exists():
                return JSONResponse({"ok": False, "error": f"folder {sub} tidak ada"}, status_code=404)
            man = await asyncio.to_thread(adapters_plugin.baca, akar, url)
            d = adapters_plugin.deteksi(akar)
            out = man.ringkas()
            out["deteksi"] = {"jenis": d["jenis"], "penanda": d["penanda"]}
            out["plugin_dalam"] = adapters_plugin.daftar_plugin_dalam(akar)
            out["ok"] = True
        else:
            out = await asyncio.to_thread(adapters_plugin.pratinjau, url)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status_code=500)
    return out


@app.post("/api/capability/pasang")
async def capability_install(payload: dict, request: Request):
    # Capability berakhir di folder yang dibaca keempat pekerja: keadaan bersama.
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh memasang capability", 403)
    body = payload or {}
    url = (body.get("url") or "").strip()
    if not url:
        return JSONResponse({"ok": False, "error": "url atau jalur paket wajib diisi"}, status_code=400)
    pilih = body.get("pilih") or None
    if isinstance(pilih, str):
        pilih = [x.strip() for x in pilih.split(",") if x.strip()]
    if pilih:
        tak_dikenal = [x for x in pilih if x not in adapters_plugin.JENIS]
        if tak_dikenal:
            return JSONResponse({"ok": False, "error": f"jenis tidak dikenal: {', '.join(tak_dikenal)}"}, status_code=400)
    pekerja = body.get("pekerja") or None
    sub = (body.get("sub") or "").strip()
    try:
        jid = adapters_plugin.pasang_latar(url, pilih=pilih, pekerja=pekerja, sub=sub)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return {"ok": True, "job": jid}


@app.delete("/api/capability/{nama}")
async def capability_remove(nama: str, request: Request):
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh melepas capability", 403)
    res = await asyncio.to_thread(adapters_plugin.lupa, nama)
    return JSONResponse({"ok": res["ok"], **res}, status_code=200 if res["ok"] else 404)


@app.get("/api/marketplace")
async def marketplace():
    return {"ok": True, "daftar": plugins.MARKETPLACE}


@app.get("/api/jobs")
async def jobs_list(request: Request):
    # Pekerjaan latar milik mesin: pemasangan CLI, kloning paket. Antreannya
    # menyebut paket dan perintah yang dijalankan pemilik mesin.
    if not _admin_saja(request):
        return _tolak("hanya admin yang boleh melihat pekerjaan latar", 403)
    return {"ok": True, "jobs": plugins.job_daftar(20)}


@app.get("/api/jobs/{jid}")
async def jobs_get(jid: str, request: Request):
    j = plugins.job_lihat(jid)
    if not j:
        return JSONResponse({"ok": False, "error": "job tidak ditemukan"}, status_code=404)
    # Job yang dimulai pengguna sendiri tetap boleh dilihatnya; yang lain tidak.
    u = _pengguna(request) or {}
    if u.get("peran") != "admin" and (j.get("owner") or "") != (u.get("nama") or ""):
        return JSONResponse({"ok": False, "error": "job tidak ditemukan"}, status_code=404)
    return {"ok": True, "job": j}


# ------------------------------------------------------------------ static
@app.get("/api/terminal")
async def terminal_info(request: Request):
    """Keadaan terminal: prefix mana yang dipakai dan alat apa saja yang ada."""
    u = _pengguna(request)
    if not u:
        return _tolak("belum masuk")
    d = terminal.info()
    d["ok"] = True
    d["cwd"] = str(terminal.folder_kerja(u["nama"]))
    d["sesi"] = [{"owner": k, "id": s.id, "hidup": bool(s.proc and s.proc.poll() is None)}
                 for k, s in terminal.semua_sesi().items()] if u.get("peran") == "admin" else []
    return d


@app.post("/api/terminal")
async def terminal_jalankan(request: Request):
    """Menjalankan satu perintah di terminal. Ini shell sungguhan, bukan tiruan.

    Batas waktu dibatasi 30 menit supaya perintah berat (clone besar, npm
    install) tetap bisa jalan tanpa menggantung permintaan selamanya.
    """
    u = _pengguna(request)
    if not u:
        return _tolak("belum masuk")
    try:
        data = await request.json()
    except Exception:
        data = {}
    perintah = (data.get("perintah") or data.get("cmd") or "").strip()
    if not perintah:
        return _tolak("perintah kosong", 400)
    if len(perintah) > 8000:
        return _tolak("perintah terlalu panjang", 400)
    s = terminal.sesi(u["nama"])
    hasil = s.jalankan(perintah, timeout=int(data.get("timeout") or 120))
    hasil["ok"] = bool(hasil.get("ok"))
    return hasil


@app.get("/api/terminal/alir")
async def terminal_alir(request: Request):
    """Keluaran terminal yang mengalir (SSE), untuk perintah panjang."""
    u = _pengguna(request)
    if not u:
        return _tolak("belum masuk")
    s = terminal.sesi(u["nama"])
    s.nyalakan()
    kid = s.pelanggan_tambah()
    mulai = int(request.query_params.get("posisi") or 0)
    if mulai <= 0:
        # Kirim isi buffer sekarang supaya layar tidak kosong saat dibuka.
        mulai = max(0, len(s.buffer()) - 4000)

    async def aliran():
        posisi = mulai
        try:
            while True:
                if await request.is_disconnected():
                    break
                teks, posisi = await asyncio.to_thread(s.tunggu_baru, kid, posisi, 20.0)
                if teks:
                    for baris in teks.split("\n"):
                        yield f"data: {json.dumps({'baris': baris})}\n\n"
                else:
                    yield ": tetap hidup\n\n"
        finally:
            s.pelanggan_buang(kid)

    return StreamingResponse(aliran(), media_type="text/event-stream")


@app.post("/api/terminal/bersihkan")
async def terminal_bersihkan(request: Request):
    u = _pengguna(request)
    if not u:
        return _tolak("belum masuk")
    terminal.sesi(u["nama"]).bersihkan()
    return {"ok": True}


@app.post("/api/terminal/hentikan")
async def terminal_hentikan(request: Request):
    """Mematikan shell pengguna. Shell akan dibuat lagi saat perintah berikutnya."""
    u = _pengguna(request)
    if not u:
        return _tolak("belum masuk")
    terminal.matikan_sesi(u["nama"])
    return {"ok": True}


@app.post("/api/terminal/astroz")
async def terminal_astroz(request: Request):
    """Jembatan AstroZ <-> Terminal.

    Dipakai oleh perintah `astroz` di dalam shell, supaya terminal dan AstroZ
    bukan dua dunia terpisah. Semua aksi di sini benar-benar memanggil sistem
    AstroZ yang sama dengan yang dipakai UI -- bukan jawaban tiruan:

        astroz status           keadaan runtime, pekerja, dan model
        astroz task "..."       membuat tugas baru (masuk ke orchestrator)
        astroz tugas [n]        daftar tugas terakhir
        astroz project [nama]   daftar project atau pindah project
        astroz berkas [jalur]   daftar berkas di folder kerja
        astroz worker [nama]    daftar pekerja atau mengaktifkan satu
        astroz model [nama]     melihat atau mengganti model gateway
        astroz review "..."     meminta pekerja meninjau folder kerja
        astroz terminal "..."   menjalankan perintah shell
    """
    u = _pengguna(request)
    if not u:
        return _tolak("belum masuk")
    try:
        data = await request.json()
    except Exception:
        data = {}
    aksi = (data.get("aksi") or "").strip().lower()
    arg = (data.get("arg") or "").strip()
    nama = u["nama"]
    admin = u.get("peran") == "admin"

    if aksi in ("status", ""):
        cfg = config.load()
        return {"ok": True, "aksi": "status", "pengguna": nama,
                "peran": u.get("peran"), "kerja": str(terminal.folder_kerja(nama)),
                "model": cfg["gateway"].get("model", ""),
                "pekerja": _status_pekerja(request),
                "terminal": terminal.info(),
                "tugas_berjalan": len([t for t in orchestrator.list_tasks(50, owner=None if admin else nama)
                                       if t.get("status") == "running"])}

    if aksi in ("task", "tugas"):
        if not arg:
            daftar = orchestrator.list_tasks(int(data.get("maks") or 10),
                                             owner=None if admin else nama)
            return {"ok": True, "aksi": "tugas", "daftar": [
                {"id": t.get("id"), "status": t.get("status"),
                 "prompt": (t.get("prompt") or "")[:120]} for t in daftar]}
        orch = orchestrator.Orchestrator()
        tid = orch.submit(arg, workflow=(data.get("workflow") or "auto"),
                          workers=data.get("workers") or None,
                          model=data.get("model") or None, owner=nama)
        return {"ok": True, "aksi": "task", "id": tid,
                "pesan": f"tugas dibuat: {tid}. Pantau lewat `astroz tugas` atau UI AstroZ."}

    if aksi in ("project", "proyek"):
        kerja = terminal.folder_kerja(nama)
        if not arg:
            anak = sorted([d.name for d in kerja.iterdir() if d.is_dir() and not d.name.startswith(".")])
            return {"ok": True, "aksi": "project", "kerja": str(kerja), "daftar": anak}
        target = (kerja / arg).resolve()
        if target != kerja and kerja not in target.parents:
            return _tolak("project harus di dalam folder kerja Anda", 400)
        if not target.is_dir():
            return {"ok": False, "error": f"project tidak ada: {arg}",
                    "petunjuk": f"buat dengan: mkdir {arg} && cd {arg}"}
        return {"ok": True, "aksi": "project", "kerja": str(target),
                "pesan": f"project {arg} ada. Masuk dengan: cd {arg}"}

    if aksi in ("berkas", "file", "ls"):
        kerja = terminal.cwd_sah(nama, arg)
        anak = []
        for p in sorted(kerja.iterdir()):
            if p.name.startswith("."):
                continue
            anak.append({"nama": p.name, "jenis": "dir" if p.is_dir() else "file",
                         "ukuran": p.stat().st_size if p.is_file() else 0})
        return {"ok": True, "aksi": "berkas", "kerja": str(kerja), "daftar": anak[:200]}

    if aksi in ("worker", "pekerja"):
        if not arg:
            return {"ok": True, "aksi": "worker", "daftar": _status_pekerja(request)}
        if not admin:
            return _tolak("hanya admin yang boleh mengubah setelan pekerja", 403)
        if arg not in adapters.ADAPTERS:
            return _tolak(f"pekerja tidak dikenal: {arg}. Yang ada: "
                          + ", ".join(adapters.ADAPTERS), 404)
        cfg = config.load()
        w = cfg["workers"].setdefault(arg, {"enabled": True, "model": ""})
        w["enabled"] = True
        config.save(cfg)
        hub.emit("system", f"Pekerja {arg} diaktifkan dari terminal oleh {nama}")
        return {"ok": True, "aksi": "worker", "pesan": f"pekerja {arg} diaktifkan"}

    if aksi == "model":
        cfg = config.load()
        if not arg:
            return {"ok": True, "aksi": "model", "model": cfg["gateway"].get("model", "")}
        if not admin:
            return _tolak("hanya admin yang boleh mengganti model", 403)
        gw = Gateway()
        hasil = await asyncio.to_thread(gw.apply, arg, True, True)
        return {"ok": True, "aksi": "model", "model": arg, "hasil": hasil}

    if aksi in ("review", "tinjau"):
        prompt = arg or "Tinjau isi folder kerja ini: cari masalah nyata, lalu laporkan temuan dan perbaikannya."
        orch = orchestrator.Orchestrator()
        tid = orch.submit(prompt, workflow="review", workers=None, model=None, owner=nama)
        return {"ok": True, "aksi": "review", "id": tid,
                "pesan": f"tugas review dibuat: {tid}"}

    if aksi == "terminal":
        if not arg:
            return _tolak("perintah kosong", 400)
        return terminal.jalankan(arg, owner=nama, timeout=int(data.get("timeout") or 120))

    return {"ok": False, "error": f"aksi tidak dikenal: {aksi or '(kosong)'}",
            "bantuan": "status | task | tugas | project | berkas | worker | model | review | terminal"}


@app.get("/{path:path}")
async def static_files(path: str):
    """Serve the UI's own assets (one HTML file, one stylesheet, one script)."""
    if path.startswith("api/"):
        return JSONResponse({"ok": False, "error": "unknown endpoint"}, status_code=404)
    if not path or path == "/":
        return FileResponse(WEB / "index.html")
    target = (WEB / path).resolve()
    if WEB.resolve() in target.parents and target.is_file():
        return FileResponse(target)
    return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

