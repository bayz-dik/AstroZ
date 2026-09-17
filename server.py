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
from gateway import Gateway

ROOT = pathlib.Path(__file__).resolve().parent
WEB = ROOT / "web"

app = FastAPI(title="AstroZ")
_started = time.time()


@app.on_event("startup")
async def _startup() -> None:
    hub.bind_loop(asyncio.get_running_loop())
    n = hub.load_from_disk(1500)
    nt = orchestrator.load_tasks()
    ns = sessions.load()
    hub.emit("system", f"UI AstroZ siap ({n} kejadian, {nt} tugas, {ns} percakapan tersimpan)", phase="boot")
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
async def state():
    cfg = config.load()
    gw = Gateway(cfg)
    gwcfg = dict(cfg["gateway"])
    gwcfg["has_key"] = bool(gw.api_key)
    # Kunci API tidak pernah dikirim ke peramban: server ini mendengarkan di
    # seluruh antarmuka jaringan (0.0.0.0), jadi apa pun yang ada di jawaban ini
    # bisa dibaca siapa saja di jaringan yang sama. UI hanya butuh tahu ada
    # atau tidak kuncinya.
    gwcfg.pop("api_key", None)
    return {
        "gateway": gwcfg,
        "workers": adapters.status_all(),
        "worker_cfg": cfg["workers"],
        "tasks": orchestrator.list_tasks(30),
        "project": {"dir": str(project.project_dir()), "test_command": project.detect_test_command()},
        "workflow": cfg["workflow"],
        "uptime": round(time.time() - _started, 1),
        "subscribers": hub.subscribers(),
    }


@app.get("/api/events")
async def events(request: Request, replay: int = 80):
    q = hub.subscribe()

    async def gen():
        try:
            for ev in hub.recent(replay):
                yield f"data: {json.dumps(ev)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
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
async def events_recent(limit: int = 300, kind: str = ""):
    return {"events": hub.recent(limit, kind or None)}


# ----------------------------------------------------------------- gateway
@app.post("/api/gateway/sync")
async def gateway_sync(apply: int = 0):
    gw = Gateway()
    res = await asyncio.to_thread(gw.sync, bool(apply))
    return {"ok": True, **res}


@app.get("/api/gateway/models")
async def gateway_models(q: str = "", limit: int = 300, only_healthy: int = 0, provider: str = "", callable_only: int = 0):
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
async def gateway_set_model(payload: dict):
    model = (payload or {}).get("model", "").strip()
    if not model:
        return JSONResponse({"ok": False, "error": "model required"}, status_code=400)
    apply_workers = bool(payload.get("apply_workers", True))
    gw = Gateway()
    res = await asyncio.to_thread(gw.apply, model, apply_workers, True)
    return {"ok": True, **res}


@app.post("/api/gateway/key")
async def gateway_set_key(payload: dict):
    key = (payload or {}).get("api_key", "").strip()
    cfg = config.load()
    cfg["gateway"]["api_key"] = key
    config.save(cfg)
    hub.emit("gateway", f"Kunci API gateway {'disimpan' if key else 'dikosongkan'}", has_key=bool(key))
    return {"ok": True, "has_key": bool(key)}


@app.post("/api/gateway/probe")
async def gateway_probe(payload: dict | None = None):
    """Ping models through 9Router and record which ones actually answer."""
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
async def apply_everything(payload: dict | None = None):
    """Re-apply the current model to every worker + Hermes in one call."""
    cfg = config.load()
    model = (payload or {}).get("model") or cfg["gateway"].get("model")
    gw = Gateway()
    res = await asyncio.to_thread(gw.apply, model, True, True)
    return {"ok": True, **res}


# ----------------------------------------------------------------- workers
@app.get("/api/workers")
async def workers(refresh: int = 0):
    if refresh:
        await asyncio.to_thread(adapters.status_all, True)
    return {"workers": adapters.status_all(), "cfg": config.load()["workers"]}


@app.post("/api/workers/{key}")
async def worker_update(key: str, payload: dict):
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
async def submit_task(payload: dict):
    prompt = (payload or {}).get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"ok": False, "error": "prompt required"}, status_code=400)
    orch = orchestrator.Orchestrator()
    tid = orch.submit(
        prompt,
        workflow=(payload.get("workflow") or "auto"),
        workers=payload.get("workers") or None,
        model=payload.get("model") or None,
    )
    return {"ok": True, "id": tid}


@app.get("/api/tasks")
async def tasks():
    return {"tasks": orchestrator.list_tasks(50)}


# Rute tetap harus didaftarkan sebelum /api/tasks/{tid}: rute dinamis itu
# menelan "running" sebagai id tugas dan menjawab 404.
@app.get("/api/tasks/running")
async def tasks_running():
    """Tugas yang sedang berjalan, ringkas, untuk strip kerja di UI.

    Satu permintaan saja: daftar tugas berjalan, pekerja yang sedang aktif
    (dihitung dari kejadian terakhir tiap pekerja, bukan dari daftar penugasan),
    dan beberapa langkah terakhir. UI memanggil ini berkala selama ada pekerjaan,
    jadi isinya dijaga kecil.
    """
    evs = hub.recent(800)
    out: list[dict] = []
    for t in orchestrator.list_tasks(50):
        if t.get("status") != "running":
            continue
        milik = [e for e in evs if e.get("task") == t["id"]]
        if not milik:
            # Ring di memori bisa sudah terisi kejadian lain (aktivitas plugin
            # Hermes deras). Ambil dari feed di disk supaya strip kerja tetap
            # tahu pekerja mana yang sedang aktif.
            milik = await asyncio.to_thread(hub.untuk_tugas, t["id"], 40)
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
async def task_hentikan(tid: str):
    """Hentikan tugas yang sedang berjalan dari UI.

    Pekerja CLI yang sedang bekerja dimatikan prosesnya, tahap berikutnya pada
    tugas itu dilewati, dan statusnya jadi `cancelled` supaya chat tidak terus
    menampilkan "sedang jalan" untuk pekerjaan yang sudah dibatalkan.
    """
    hasil = orchestrator.hentikan(tid)
    if not hasil.get("ok"):
        return JSONResponse(hasil, status_code=404)
    return hasil


@app.get("/api/tasks/{tid}")
async def task_detail(tid: str):
    t = orchestrator.get_task(tid)
    if not t:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    evs = await asyncio.to_thread(hub.untuk_tugas, tid, 300)
    return {"ok": True, "task": t, "events": evs}


@app.get("/api/tasks/{tid}/berkas")
async def task_berkas(tid: str):
    """Berkas yang diubah satu tugas, dihitung dari mtime sesudah tugas mulai.

    Dipakai panel samping untuk menampilkan perubahan tanpa perlu git diff
    seluruh folder kerja.
    """
    t = orchestrator.get_task(tid)
    if not t:
        return JSONResponse({"ok": False, "error": "tidak ditemukan"}, status_code=404)
    mulai = float(t.get("created") or 0)
    d = pathlib.Path(t.get("workspace") or project.project_dir())
    out = await asyncio.to_thread(project.berkas_sejak, mulai)
    return {"ok": True, **out}


@app.get("/api/project/tree")
async def project_tree():
    return {"dir": str(project.project_dir()), "entries": project.tree()}


@app.get("/api/project/file")
async def project_file(path: str):
    return project.read_file(path)


@app.get("/api/git")
async def git_status():
    return project.git_status()


@app.get("/api/git/diff")
async def git_diff(path: str = ""):
    return {"diff": project.git_diff(path)}


@app.post("/api/git/commit")
async def git_commit(payload: dict | None = None):
    """Commit the workspace so a finished task is a commit, not a dirty tree."""
    msg = ((payload or {}).get("message") or "").strip()
    if not msg:
        return JSONResponse({"ok": False, "error": "message required"}, status_code=400)
    res = await asyncio.to_thread(project.git_commit_all, msg)
    ok = res.get("rc") == 0
    if not ok and "nothing to commit" in (res.get("out") or ""):
        return {"ok": True, "noop": True, **res}
    return JSONResponse({"ok": ok, **res}, status_code=200 if ok else 500)


@app.post("/api/test")
async def run_test(payload: dict | None = None):
    cmd = (payload or {}).get("command") or None
    res = await asyncio.to_thread(project.run_tests, cmd)
    return {"ok": True, "result": res}


@app.post("/api/config")
async def set_config(payload: dict):
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
async def sessions_list():
    items = sessions.list_sessions()
    tasks = {t["id"]: t for t in orchestrator.list_tasks(200)}
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
    return {"sessions": items}


@app.post("/api/sessions")
async def sessions_create(payload: dict | None = None):
    """Percakapan baru yang kosong.

    Sampai ada pesan pertama, judulnya masih kosong. UI menampilkannya sebagai
    "Percakapan baru" dan hanya menyimpan yang benar-benar dipakai, jadi daftar
    tidak penuh percakapan kosong setiap kali tombolnya ditekan.
    """
    s = sessions.create(((payload or {}).get("title") or "").strip())
    return {"ok": True, "session": s}


@app.delete("/api/sessions/kosong")
async def sessions_hapus_kosong():
    """Buang percakapan yang belum pernah dipakai (tanpa satu pun tugas)."""
    dihapus = 0
    for s in sessions.list_sessions():
        if not (s.get("tasks") or []):
            if sessions.delete(s["id"]):
                dihapus += 1
    if dihapus:
        hub.emit("system", f"{dihapus} percakapan kosong dibuang dari daftar")
    return {"ok": True, "dihapus": dihapus}


@app.get("/api/sessions/{sid}")
async def sessions_get(sid: str, events: int = 120):
    s = sessions.get(sid)
    if not s:
        return JSONResponse({"ok": False, "error": "percakapan tidak ditemukan"}, status_code=404)
    ids = list(s.get("tasks") or [])
    messages: list[dict] = []
    for tid in ids:
        messages.extend(_task_messages(tid))
    activity: dict[str, list[dict]] = {}
    if events:
        for tid in ids:
            evs = await asyncio.to_thread(hub.untuk_tugas, tid, events)
            if evs:
                activity[tid] = evs
    return {"ok": True, "session": {**s, "tasks": ids}, "messages": messages, "activity": activity}


@app.post("/api/sessions/{sid}")
@app.patch("/api/sessions/{sid}")
async def sessions_update(sid: str, payload: dict):
    s = sessions.rename(sid, (payload or {}).get("title") or "")
    if not s:
        return JSONResponse({"ok": False, "error": "percakapan tidak ditemukan"}, status_code=404)
    return {"ok": True, "session": s}


@app.delete("/api/sessions/{sid}")
async def sessions_delete(sid: str):
    ok = sessions.delete(sid)
    return {"ok": ok}


@app.post("/api/sessions/{sid}/sematkan")
async def sessions_sematkan(sid: str, payload: dict | None = None):
    """Sematkan atau lepas sematan percakapan ini.

    Yang disematkan naik ke atas daftar riwayat, jadi percakapan yang sering
    dibuka tidak tenggelam oleh percakapan baru.
    """
    isi = payload or {}
    nilai = isi.get("pinned")
    s = sessions.toggle_pin(sid, None if nilai is None else bool(nilai))
    if not s:
        return JSONResponse({"ok": False, "error": "percakapan tidak ditemukan"}, status_code=404)
    return {"ok": True, "session": s, "pinned": bool(s.get("pinned"))}


@app.post("/api/chat")
async def chat_send(payload: dict):
    """One user message: it becomes a task, and its answer lands in this thread."""
    text = ((payload or {}).get("text") or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "tulis dulu pesannya"}, status_code=400)
    # Satu percakapan baru per kiriman kalau UI tidak menyebut sesi. Tanpa ini
    # semua pesan masuk ke percakapan pertama dan daftarnya menumpuk jadi satu.
    sid = (payload or {}).get("session") or None
    if not sid and (payload or {}).get("baru"):
        sid = sessions.create("")["id"]
    s = sessions.ensure(sid, text)
    orch = orchestrator.Orchestrator()
    tid = orch.submit(
        text,
        workflow=(payload or {}).get("workflow") or "auto",
        workers=(payload or {}).get("workers") or None,
        model=(payload or {}).get("model") or None,
        session_id=s["id"],
    )
    sessions.attach(s["id"], tid, text)
    hub.emit("task", f"Percakapan {s['id']}: pesan baru", task=tid, session=s["id"], phase="created")
    return {"ok": True, "session": s["id"], "task_id": tid, "title": s["title"]}


@app.post("/api/upload")
async def upload(payload: dict):
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
    tujuan = project.project_dir() / "lampiran"
    tujuan.mkdir(parents=True, exist_ok=True)
    path = tujuan / f"{int(time.time())}_{aman}"
    path.write_bytes(mentah)
    hub.emit("system", f"Lampiran disimpan: {path}")
    return {"ok": True, "path": str(path), "size": len(mentah)}


# ------------------------------------------------------------------ alat
@app.get("/api/tools/status")
async def tools_status():
    """Ringkas: gateway, pekerja, plugin MCP, dan paket skill."""
    cfg = config.load()
    mcp = plugins.mcp_daftar()
    skills = plugins.skill_daftar()
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
async def workers_paket():
    """Paket npm tiap pekerja, plus status terpasang. Dipakai UI untuk menawarkan
    pemasangan otomatis supaya satu clone bisa langsung jalan."""
    st = {w["key"]: w for w in adapters.status_all()}
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
async def worker_pasang(key: str):
    """Pasang satu CLI pekerja lewat npm di latar belakang."""
    if key not in adapters.PAKET:
        return JSONResponse({"ok": False, "error": "pekerja tidak dikenal"}, status_code=404)
    if not shutil.which("npm"):
        return JSONResponse({"ok": False, "error": "npm tidak ada di PATH, pasang Node.js dulu"}, status_code=400)
    jid = await asyncio.to_thread(adapters.pasang_latar, key)
    return {"ok": True, "job": jid}


# ------------------------------------------------------------------ plugin MCP
@app.get("/api/mcp")
async def mcp_list():
    return {"ok": True, "servers": plugins.mcp_daftar(), "siap": plugins.MCP_SIAP}


@app.post("/api/mcp")
async def mcp_add(payload: dict):
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
async def mcp_remove(nama: str):
    res = await asyncio.to_thread(plugins.mcp_hapus, nama)
    hub.emit("system", f"Plugin MCP {nama} dilepas dari pekerja")
    return {"ok": True, "hasil": res}


# ------------------------------------------------------------------ skill
# Hasil pemindaian skill disimpan sebentar: halaman Skill terpasang memanggil
# endpoint ini setiap kali dibuka, dan menghitung ukuran 93 paket setiap kali
# membuat halaman terasa menggantung. Isinya hanya berubah kalau ada paket baru.
_SKILL_CACHE: dict[str, object] = {"t": 0.0, "isi": None}
_SKILL_CACHE_DETIK = 30


@app.get("/api/skills")
async def skills_list():
    sekarang = time.time()
    t_lama = _SKILL_CACHE["t"]
    if _SKILL_CACHE["isi"] is not None and isinstance(t_lama, float) and sekarang - t_lama < _SKILL_CACHE_DETIK:
        return _SKILL_CACHE["isi"]
    daftar = await asyncio.to_thread(plugins.skill_terpasang)
    isi = {
        "ok": True,
        "paket": await asyncio.to_thread(plugins.skill_daftar),
        "siap": plugins.skill_ringkas_untuk_pekerja(),
        "daftar": daftar,
        "bawaan": plugins.skill_bawaan_siap(),
    }
    _SKILL_CACHE["t"] = sekarang
    _SKILL_CACHE["isi"] = isi
    return isi


@app.post("/api/skills/bawaan")
async def skills_bawaan():
    """Tautkan semua skill bawaan repo ke folder yang dibaca pekerja."""
    res = await asyncio.to_thread(plugins.skill_pasang_bawaan)
    _SKILL_CACHE["isi"] = None
    await asyncio.to_thread(plugins.skill_terpasang, True)
    return JSONResponse(res, status_code=200 if res.get("ok") else 400)


@app.post("/api/skills")
async def skills_add(payload: dict):
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
async def skills_remove(nama: str):
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
async def capability_list():
    return {
        "ok": True,
        "terpasang": adapters_plugin.terpasang(),
        "jenis": list(adapters_plugin.JENIS),
        "pekerja": list(adapters_plugin.PEKERJA),
    }


@app.post("/api/capability/pratinjau")
async def capability_preview(payload: dict):
    """Unduh dan baca sumber tanpa memasang. Ini yang membuat pratinjau jujur."""
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
async def capability_install(payload: dict):
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
async def capability_remove(nama: str):
    res = await asyncio.to_thread(adapters_plugin.lupa, nama)
    return JSONResponse({"ok": res["ok"], **res}, status_code=200 if res["ok"] else 404)


@app.get("/api/marketplace")
async def marketplace():
    return {"ok": True, "daftar": plugins.MARKETPLACE}


@app.get("/api/jobs")
async def jobs_list():
    return {"ok": True, "jobs": plugins.job_daftar(20)}


@app.get("/api/jobs/{jid}")
async def jobs_get(jid: str):
    j = plugins.job_lihat(jid)
    if not j:
        return JSONResponse({"ok": False, "error": "job tidak ditemukan"}, status_code=404)
    return {"ok": True, "job": j}


# ------------------------------------------------------------------ static
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

