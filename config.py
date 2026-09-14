"""Config store for AstroZ (team.yaml + 9Router discovery)."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import time
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "team.yaml"
RUNTIME = ROOT / "runtime"
RUNTIME.mkdir(parents=True, exist_ok=True)
EVENTS_FILE = RUNTIME / "events.jsonl"

DEFAULTS: dict[str, Any] = {
    "gateway": {
        "base_url": "http://127.0.0.1:20128",
        "api_base": "http://127.0.0.1:20129/v1",
        # 20129 is the local SSE-sanitising pass-through (proxy.py): it forwards
        # everything to 9Router on 20128 but drops the duplicate `data: [DONE]`
        # terminator that breaks strict SSE parsers (opencode). Clients that
        # tolerate the duplicate are unaffected.
        "upstream_base_url": "http://127.0.0.1:20128",
        # Hermes' own endpoint. Empty = base_url + "/v1", i.e. straight to
        # 9Router, bypassing the sanitiser. Keep it that way: Hermes is the
        # repair tool for this stack and must not depend on proxy.py.
        "hermes_api_base": "",
        "api_key": "",
        "model": "",
        "models": [],
        "model_count": 0,
        "last_sync": 0,
        "online": False,
        "fallback_models": [],
        "auto_fallback": True,
        "healthy": [],
        "model_meta": {},
        # Model yang pernah dijawab gateway dengan "unrecognized_model". Dipakai
        # supaya rantai cadangan tidak mencoba model mati berulang kali.
        "model_rejected": [],
        # Model yang dipakai alat `lihat` untuk membaca gambar. Kosong berarti
        # alat mencoba daftar bawaannya sendiri.
        "vision_model": "",
    },
    "project_dir": str(pathlib.Path.home() / "AstroZ" / "workspace"),
    "workers": {
        "claude": {"enabled": True, "model": ""},
        "codex": {"enabled": True, "model": ""},
        "opencode": {"enabled": True, "model": ""},
        "omp": {"enabled": True, "model": ""},
    },
    "workflow": {
        "max_parallel": 3,
        "auto_test": True,
        "discussion": True,
        "review": True,
        "test_command": "",
        "stall_seconds": 240,
        "escalate_tries": 2,
        "fix_on_fail": True,
        "fix_rounds": 1,
        "fix_review_rounds": 1,
        # Cheapest-first worker preference. The orchestrator follows this order
        # for subtasks and (by cost) for repair rounds; put the expensive CLI
        # last so a routine edit does not cost a Claude request.
        "worker_order": ["omp", "opencode", "codex", "claude"],
        "worker_cost": {"omp": 0.01, "opencode": 0.02, "codex": 0.05, "claude": 0.45},
        # Commit a finished task automatically, but only when its own
        # verification passed (tests ok + review PASS). See _task_is_green.
        "auto_commit": True,
    },
    "hermes": {
        "profile": "default",
        "enabled": True,
    },
}


def _deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    if CONFIG_PATH.exists():
        try:
            data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
        except Exception:
            data = {}
        cfg = _deep_merge(DEFAULTS, data)
    else:
        cfg = json.loads(json.dumps(DEFAULTS))
    cfg["gateway"]["model_meta"] = load_model_meta()
    if not cfg["gateway"].get("models"):
        cfg["gateway"]["models"] = load_model_ids()
    return cfg


def save(cfg: dict) -> None:
    """Write team.yaml (small, human-editable) + the model cache separately.

    The full model list and its metadata are thousands of entries; keeping them
    out of the YAML keeps the config readable and cheap to parse on every
    request (the YAML is re-read on each call).
    """
    out = json.loads(json.dumps(cfg))
    gw = out.get("gateway", {})
    meta = gw.pop("model_meta", None)
    models = gw.pop("models", None)
    if meta is not None:
        save_model_meta(meta)
    if models is not None:
        save_model_ids(models)
    tmp = CONFIG_PATH.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True))
    tmp.replace(CONFIG_PATH)


META_PATH = RUNTIME / "model_meta.json"
MODELS_PATH = RUNTIME / "models.json"


def load_model_meta() -> dict:
    try:
        return json.loads(META_PATH.read_text())
    except Exception:
        return {}


def save_model_meta(meta: dict) -> None:
    try:
        tmp = META_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta))
        tmp.replace(META_PATH)
    except Exception:
        pass


def load_model_ids() -> list:
    try:
        return json.loads(MODELS_PATH.read_text())
    except Exception:
        return []


def save_model_ids(ids: list) -> None:
    try:
        tmp = MODELS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(ids))
        tmp.replace(MODELS_PATH)
    except Exception:
        pass


def update(patch: dict) -> dict:
    cfg = load()
    cfg = _deep_merge(cfg, patch)
    save(cfg)
    return cfg


def nine_router_token(data_dir: str | None = None) -> str:
    """Derive the 9Router CLI token exactly like src/cli/api/client.js does."""
    data_dir = data_dir or str(pathlib.Path.home() / ".9router")
    d = pathlib.Path(data_dir)
    raw = ""
    try:
        raw = (d / "machine-id").read_text().strip()
    except Exception:
        raw = ""
    try:
        secret = (d / "auth" / "cli-secret").read_text().strip()
    except Exception:
        secret = ""
    if not raw or not secret:
        return ""
    return hashlib.sha256((raw + "9r-cli-auth" + secret).encode()).hexdigest()[:16]


def read_nine_router_key(data_dir: str | None = None) -> str:
    """First active API key straight from the 9Router sqlite db."""
    data_dir = data_dir or str(pathlib.Path.home() / ".9router")
    db = pathlib.Path(data_dir) / "db" / "data.sqlite"
    if not db.exists():
        return ""
    try:
        import sqlite3

        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        row = con.execute(
            "select key from apiKeys where isActive=1 order by createdAt asc limit 1"
        ).fetchone()
        con.close()
        return row[0] if row else ""
    except Exception:
        return ""


def hermes_home() -> str:
    return os.environ.get("HERMES_HOME", str(pathlib.Path.home() / ".hermes"))


def now() -> float:
    return time.time()
