"""AstroZ web server: mobile-first dashboard + JSON API + SSE feed."""
from __future__ import annotations

import asyncio
import json
import pathlib
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

import adapters
import config
import hub
import orchestrator
import project
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
    hub.emit("system", f"AstroZ UI up ({n} events, {nt} tasks replayed)", phase="boot")
    asyncio.create_task(_bg_health())
    # mirror Hermes activity feeds into the hub: the astroz plugin feed and the
    # live-activity plugin feed (both are written by separate processes).
    home = pathlib.Path(config.hermes_home())
    for rel, tag in (("runtime/hermes_plugin.jsonl", "astroz"), ("runtime/live_activity.jsonl", "live-activity")):
        threading.Thread(target=hub.follow_file, args=(home / rel,), kwargs={"kind": "hermes", "tag": tag}, daemon=True).start()
    threading.Thread(target=_refresh_workers, daemon=True).start()


def _refresh_workers() -> None:
    try:
        adapters.status_all(refresh=True)
        hub.emit("system", "Worker probe: " + ", ".join(f"{w['key']}{'✓' if w['installed'] else '✗'}" for w in adapters.status_all()))
    except Exception as e:
        hub.emit("system", f"worker probe failed: {e}", ok=False)


async def _bg_health() -> None:
    while True:
        try:
            gw = Gateway()
            h = await asyncio.to_thread(gw.health)
            cfg = config.load()
            if cfg["gateway"].get("online") != h["online"]:
                hub.emit("gateway", f"9Router {'online' if h['online'] else 'offline'}", online=h["online"])
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
async def gateway_models(q: str = "", limit: int = 300, only_healthy: int = 0):
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
        ids = await asyncio.to_thread(lambda: [m.get("fullModel") for m in Gateway().models()])
    items = []
    for mid in ids:
        if q and q.lower() not in mid.lower():
            continue
        items.append({"id": mid, **{k: v for k, v in (meta.get(mid) or {}).items()}})
    items.sort(key=lambda m: (not (m.get("health") or {}).get("ok"), m["id"]))
    healthy = gw.get("healthy", [])
    if only_healthy:
        # disaring di server, bukan di UI: hasil probe tidak selalu ikut terkirim
        # kalau UI hanya memotong 300 baris pertama.
        items = [m for m in items if (m.get("health") or {}).get("ok")]
    return {"models": items[:limit], "total": len(items), "current": gw.get("model"), "healthy": healthy}


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
    hub.emit("gateway", f"Gateway API key {'set' if key else 'cleared'}", has_key=bool(key))
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
    config.save(cfg)
    ok = [r["model"] for r in res if r["ok"]]
    hub.emit("gateway", f"Model probe: {len(ok)}/{len(res)} answering, {', '.join(ok[:8])}", healthy=ok)
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
    hub.emit("system", f"worker {key}: enabled={w['enabled']} model={w['model'] or '(gateway default)'}")
    return {"ok": True, "cfg": cfg["workers"]}


@app.post("/api/workers/{key}/probe")
async def worker_probe(key: str):
    if key not in adapters.ADAPTERS:
        return JSONResponse({"ok": False, "error": "unknown worker"}, status_code=404)
    w = adapters.ADAPTERS[key]
    st = await asyncio.to_thread(w.probe)
    hub.emit("system", f"probe {key}: {st.get('version') or st.get('error')}")
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


@app.get("/api/tasks/{tid}")
async def task_detail(tid: str):
    t = orchestrator.get_task(tid)
    if not t:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return {"ok": True, "task": t, "events": [e for e in hub.recent(2000) if e.get("task") == tid][-300:]}


# ----------------------------------------------------------------- project
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
    hub.emit("system", f"config updated: {json.dumps(patch)[:300]}")
    return {"ok": True, "config": {"project_dir": cfg["project_dir"], "workflow": cfg["workflow"]}}
