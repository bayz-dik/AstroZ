"""9Router gateway client: model discovery/sync, health, worker config apply."""
from __future__ import annotations

import json
import pathlib
import re
import urllib.error
import urllib.request
from typing import Any

import adapters
import config
import hub


def _req(url: str, token: str = "", key: str = "", method: str = "GET", body: dict | None = None, timeout: int = 25):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("x-9r-cli-token", token)
    if key:
        r.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def _usable_id(mid: str | None) -> bool:
    """A model id a client can actually ask for: provider and model both named.

    The dashboard catalog also carries half-built entries whose id ends in "/"
    (no model name). They are not callable and only add noise to the picker.
    """
    if not mid or not isinstance(mid, str):
        return False
    mid = mid.strip()
    if mid.endswith("/") or mid.startswith("/"):
        return False
    tail = mid.split("/")[-1] if "/" in mid else mid
    return bool(tail) and tail not in ("*",)


def _buang_jalan_pikir(teks: str) -> str:
    """Jalan pikir model penalar dipotong sampai kalimat jawabannya saja.

    Model seperti deepseek mengisi `content` dengan null dan menaruh seluruh
    proses berpikirnya di `reasoning`. Kalau dipakai apa adanya, gelembung
    jawaban pengguna berisi renungan panjang berbahasa Inggris ("We need answer
    in Indonesian likely...") alih-alih jawaban.

    Dua bentuk yang benar-benar terlihat di sini:
    - kalimat pembuka renungan, sisanya baru jawaban;
    - jawaban ditulis di baris terakhir setelah deretan kalimat renungan.
    Kalau tidak ada penanda yang cocok, teks dipakai utuh: lebih baik menampilkan
    sesuatu daripada mengosongkan jawaban.
    """
    if not teks:
        return ""
    t = re.sub(r"(?s)```.*?```", " ", teks).strip()
    # Penanda yang paling andal: baris jawaban ditulis setelah kalimat penutup
    # renungan. Ambil blok terakhir sesudah penanda itu.
    for penanda in ("\n\nJawaban:", "\nJawaban:", "Final answer:", "\nAnswer:"):
        if penanda in t:
            sisa = t.split(penanda)[-1].strip()
            if sisa:
                return sisa
    baris = [b.strip() for b in t.splitlines() if b.strip()]
    # Baris yang masih berupa renungan dibuang dari depan.
    renungan = re.compile(
        r"^(we need|we must|i need|i should|i will|let me|the user|user asks|user wants|"
        r"task was|first,|first |okay,|alright,|hmm|so,|now,|maybe|perhaps|thinking|"
        r"current date|as of|note:|wait,|actually,|but )",
        re.I,
    )
    sisa = [b for b in baris if not renungan.match(b)]
    # Jawaban seringkali baris terakhir saja; kalau sisanya masih panjang dan
    # tidak ada penanda, pakai baris terakhir yang tidak terlihat seperti renungan.
    if sisa and len(sisa) >= 1:
        if len(baris) > 3 and len(sisa) > 2:
            return sisa[-1]
        return " ".join(sisa)
    return t


def _first_json(raw: str):
    """First JSON value in a body that may contain several concatenated objects."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw.lstrip())
        return obj
    except Exception:
        return None


class Gateway:
    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = cfg or config.load()

    # ---------------------------------------------------------------- config
    @property
    def base_url(self) -> str:
        return self.cfg["gateway"]["base_url"].rstrip("/")

    @property
    def api_base(self) -> str:
        return self.cfg["gateway"].get("api_base") or self.base_url + "/v1"

    @property
    def api_key(self) -> str:
        return self.cfg["gateway"].get("api_key") or config.read_nine_router_key()

    @property
    def token(self) -> str:
        return config.nine_router_token()

    # ---------------------------------------------------------------- health
    def health(self) -> dict:
        st, raw = _req(f"{self.base_url}/api/health", timeout=6)
        ok = st == 200 and '"ok":true' in raw.replace(" ", "")
        if not ok:
            st2, raw2 = _req(f"{self.base_url}/api/version", timeout=6)
            if st2 == 200:
                ok = True
                raw = raw2
        return {"online": ok, "status": st, "raw": raw[:200]}

    # ---------------------------------------------------------------- models
    def models(self) -> list[dict]:
        """Every model the gateway will actually accept, with metadata merged.

        Two sources, and both are needed:

        * ``/api/models`` (dashboard API, needs the CLI token) is the rich
          catalog: provider, alias, caps, pricing. It only lists models from
          providers whose credentials the dashboard knows about.
        * ``/v1/models`` (the OpenAI-compatible surface) is what a client can
          actually call. It is the authoritative id list, and it includes
          providers missing from the dashboard catalog.

        Reading only the first source is why a working provider (kenari-id and
        friends) never showed up in the UI: it was not in the dashboard catalog.
        Reading only the second loses caps and pricing. So: take the union,
        keyed by id, and backfill metadata by matching the model suffix.
        """
        rich: list[dict] = []
        st, raw = _req(f"{self.base_url}/api/models", token=self.token, timeout=30)
        if st == 200:
            try:
                rich = json.loads(raw).get("models", [])
            except Exception:
                rich = []

        live: list[str] = []
        st, raw = _req(f"{self.api_base}/models", key=self.api_key, timeout=30)
        if st == 200:
            try:
                live = [m["id"] for m in json.loads(raw).get("data", []) if m.get("id")]
            except Exception:
                live = []

        by_id: dict[str, dict] = {}
        for m in rich:
            mid = m.get("fullModel") or m.get("model")
            if not _usable_id(mid):
                continue
            by_id[mid] = {**m, "origin": "catalog"}
        if not by_id and not live:
            return []

        # suffix index: model name (and alias) -> the catalog entry describing it
        index: dict[str, dict] = {}
        for m in rich:
            for key in (m.get("model"), m.get("alias")):
                if key:
                    index.setdefault(key, m)

        for mid in live:
            if not _usable_id(mid):
                continue
            if mid in by_id:
                by_id[mid]["callable"] = True
                continue
            tail = mid.split("/", 1)[1] if "/" in mid else mid
            base = tail.split(":", 1)[0]
            meta = index.get(tail) or index.get(base) or {}
            by_id[mid] = {
                # The id already names its provider; the catalog is consulted for
                # caps and display name only. Taking the catalog's provider here
                # mislabels ids whose model name exists under another provider.
                "provider": mid.split("/", 1)[0] if "/" in mid else (meta.get("provider") or ""),
                "model": base,
                "name": meta.get("name") or base,
                "fullModel": mid,
                "caps": meta.get("caps", {}),
                "alias": meta.get("alias") or base,
                "origin": "gateway",
                "callable": True,
            }
        for mid, m in by_id.items():
            m.setdefault("callable", False)
            pid = m.get("fullModel") or m.get("model") or mid
            m["pricing"] = m.get("pricing") or None
            m["id"] = pid
        # Provider ids that are endpoint uuids are useless in a picker: show the
        # prefix the connection was configured with instead.
        pmap = self.provider_map()
        for m in by_id.values():
            raw_provider = m.get("provider") or ""
            if raw_provider in pmap:
                m["provider_id"] = raw_provider
                m["provider"] = pmap[raw_provider]
        # merge pricing from the provider price list (real prices, when published)
        pricing = self.pricing()
        for mid, m in by_id.items():
            if mid in pricing:
                m["pricing"] = pricing[mid]
            elif m.get("model") in pricing:
                m["pricing"] = pricing[m["model"]]
        return list(by_id.values())

    def combos(self) -> list[dict]:
        st, raw = _req(f"{self.base_url}/api/combos", token=self.token, timeout=15)
        if st != 200:
            return []
        try:
            return json.loads(raw).get("combos", [])
        except Exception:
            return []

    def provider_map(self) -> dict[str, str]:
        """Endpoint id to the prefix people recognise.

        Custom [OI]-compatible connections are listed under a synthetic id
        (``openai-compatible-chat-<uuid>``) while the model ids use the short
        prefix the connection was configured with (``kenari-id``, ``oc-prod``).
        The connections endpoint is the only place that pairs the two.
        """
        st, raw = _req(f"{self.base_url}/api/providers", token=self.token, timeout=20)
        if st != 200:
            return {}
        try:
            cons = json.loads(raw).get("connections", [])
        except Exception:
            return {}
        out: dict[str, str] = {}
        for c in cons:
            prefix = (c.get("providerSpecificData") or {}).get("prefix")
            pid = c.get("provider")
            if prefix and pid:
                out.setdefault(pid, prefix)
        return out

    def pricing(self) -> dict:
        st, raw = _req(f"{self.base_url}/api/pricing", token=self.token, timeout=20)
        if st != 200:
            return {}
        try:
            d = json.loads(raw)
        except Exception:
            return {}
        if isinstance(d, dict):
            for key in ("pricing", "models", "data"):
                if isinstance(d.get(key), (dict, list)):
                    d = d[key]
                    break
        if isinstance(d, list):
            return {(x.get("model") or x.get("id")): x for x in d if isinstance(x, dict)}
        if isinstance(d, dict):
            return {k: v for k, v in d.items() if isinstance(v, dict)}
        return {}

    def combos(self) -> list[dict]:
        st, raw = _req(f"{self.base_url}/api/combos", token=self.token, timeout=15)
        if st != 200:
            return []
        try:
            return json.loads(raw).get("combos", [])
        except Exception:
            return []

    def keys(self) -> list[dict]:
        st, raw = _req(f"{self.base_url}/api/keys", token=self.token, timeout=15)
        if st != 200:
            return []
        try:
            return json.loads(raw).get("keys", [])
        except Exception:
            return []

    def cli_tools(self) -> dict:
        st, raw = _req(f"{self.base_url}/api/cli-tools/all-statuses", token=self.token, timeout=25)
        if st != 200:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    # ------------------------------------------------------------------ sync
    def sync(self, apply_to_workers: bool = True) -> dict:
        """Read models from 9Router and mirror them into team.yaml (+ workers)."""
        cfg = config.load()
        gw = cfg["gateway"]
        gw["api_key"] = gw.get("api_key") or self.api_key
        gw["base_url"] = self.base_url
        gw["api_base"] = self.api_base
        h = self.health()
        gw["online"] = h["online"]
        models = self.models()
        ids = [m.get("fullModel") or m.get("model") for m in models]
        combos = self.combos()
        for c in combos:
            if c.get("name"):
                ids.insert(0, c["name"])
        gw["models"] = ids
        gw["model_count"] = len(ids)
        gw["last_sync"] = config.now()
        gw["model_meta"] = {
            (m.get("fullModel") or m.get("model")): {
                "provider": m.get("provider"),
                "provider_id": m.get("provider_id"),
                "name": m.get("name"),
                "caps": m.get("caps", {}),
                "pricing": m.get("pricing"),
                "origin": m.get("origin"),
                "callable": bool(m.get("callable")),
            }
            for m in models
            if (m.get("fullModel") or m.get("model"))
        }
        gw["provider_names"] = self.provider_map()
        if not gw.get("model") and ids:
            # prefer a concrete provider/model id over a bare combo alias
            concrete = [m for m in ids if "/" in m]
            gw["model"] = (concrete or ids)[0]
        config.update(cfg)
        hub.emit(
            "gateway",
            f"Sinkron 9Router: {len(ids)} model (gateway {'hidup' if h['online'] else 'mati'})",
            online=h["online"],
            model_count=len(ids),
            model=gw.get("model"),
        )
        res: dict[str, Any] = {"models": len(ids), "online": h["online"], "model": gw.get("model")}
        if apply_to_workers and gw.get("model") and h["online"]:
            res["workers"] = self.apply(gw["model"], apply_to_workers=True)
        return res

    # ----------------------------------------------------------------- apply
    def apply(self, model: str, apply_to_workers: bool = True, hot_reload: bool = True) -> dict:
        cfg = config.load()
        gw = cfg["gateway"]
        gw["model"] = model
        gw["api_key"] = gw.get("api_key") or self.api_key
        gw["base_url"] = self.base_url
        gw["api_base"] = self.api_base
        config.update(cfg)
        hub.emit("gateway", f"Model diganti ke {model}", model=model)
        out: dict[str, Any] = {"model": model}
        if apply_to_workers:
            out["workers"] = adapters.apply_all(gw)
        if hot_reload:
            out["hermes"] = self.apply_hermes(model)
        return out

    # ---------------------------------------------------------------- hermes
    def apply_hermes(self, model: str) -> dict:
        """Point the running Hermes profile at the 9Router gateway + model.

        Written through the hermes CLI so the config schema stays owned by
        Hermes; falls back to a direct YAML patch if the CLI is unavailable.
        """
        import shutil
        import subprocess

        profile = config.load()["hermes"].get("profile") or "default"
        gw = config.load()["gateway"]
        # Hermes stores custom OpenAI-compatible endpoints under a named provider
        # in custom_providers[]; model.provider must match that name.
        provider_name = gw.get("provider_name") or "9router"
        cfg = config.load()
        gwcfg = cfg["gateway"]
        gwcfg["provider_name"] = provider_name
        config.update(cfg)
        # Hermes talks to 9Router DIRECTLY (base_url), not through the SSE
        # sanitiser (api_base). Hermes' SSE parser tolerates the duplicate
        # `data: [DONE]`, and it is the tool used to repair this stack, if it
        # sat behind the sanitiser, a broken sanitiser would take away the tool
        # needed to fix the sanitiser. Override with gateway.hermes_api_base.
        hermes_base = gw.get("hermes_api_base") or (gw["base_url"].rstrip("/") + "/v1")
        try:
            p = subprocess.run(
                [
                    shutil.which("hermes") or "hermes",
                    "config",
                    "set",
                    f"custom_providers.{provider_name}.base_url",
                    hermes_base,
                    "--force",
                ],
                capture_output=True,
                text=True,
                timeout=90,
            )
            base_ok = p.returncode == 0
        except Exception as e:
            base_ok, p = False, None
        steps = []
        for key, val in (
            ("model.provider", provider_name),
            ("model.default", model),
            ("model.base_url", hermes_base),
            ("model.api_mode", "chat_completions"),
            ("model.api_key", gw.get("api_key") or self.api_key),
        ):
            try:
                q = subprocess.run(
                    [shutil.which("hermes") or "hermes", "config", "set", key, val, "--force"],
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
                steps.append({"key": key, "ok": q.returncode == 0})
            except Exception as e:
                steps.append({"key": key, "ok": False, "error": str(e)})
        # custom_providers is a LIST of {name, base_url, key_env, ...}: `config
        # set custom_providers.9router.base_url` silently misses it (the old
        # entry keeps pointing at :20128), so the entry is rewritten in place.
        try:
            import yaml as _yaml

            cfg_path = pathlib.Path(config.hermes_home()) / "config.yaml"
            doc = _yaml.safe_load(cfg_path.read_text()) or {}
            entries = doc.get("custom_providers") or []
            found = None
            for e in entries:
                if isinstance(e, dict) and e.get("name") == provider_name:
                    found = e
                    break
            if found is None:
                found = {"name": provider_name}
                entries.append(found)
                doc["custom_providers"] = entries
            found["base_url"] = hermes_base
            found["model"] = model
            if gw.get("api_key"):
                # Inline key: Hermes resolves a custom provider's credential as
                # inline api_key -> key_env -> key_cmd, and the key_env name has
                # to exist in the environment. model.api_key is already stored
                # inline in this same file, so this adds no new exposure and
                # cannot silently 401 on a missing env var.
                found["api_key"] = gw["api_key"]
                found.pop("key_env", None)
            cfg_path.write_text(_yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
            steps.append({"key": "custom_providers." + provider_name, "ok": True})
        except Exception as e:
            steps.append({"key": "custom_providers." + provider_name, "ok": False, "error": str(e)})
        ok = all(s["ok"] for s in steps)
        hub.emit("gateway", f"Setelan Hermes {'diperbarui' if ok else 'hanya sebagian'} -> {model}", ok=ok, steps=steps)
        return {"ok": ok, "steps": steps, "profile": profile, "provider": provider_name}

    # ------------------------------------------------------------ model health
    def probe_model(self, model: str, timeout: int = 40) -> dict:
        """One cheap call to see whether a model is actually servable right now.

        9Router can answer a non-streaming request with more than one JSON
        object in the body (retry/fallback concatenation), so the body is parsed
        with ``raw_decode`` and only the first object is inspected, a strict
        ``json.loads`` marks working models as broken.
        """
        import time as _t

        t0 = _t.time()
        st, raw = _req(
            f"{self.api_base}/chat/completions",
            key=self.api_key,
            method="POST",
            body={"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 4},
            timeout=timeout,
        )
        dur = round(_t.time() - t0, 1)
        obj = _first_json(raw)
        ok = st == 200 and isinstance(obj, dict) and bool(obj.get("choices"))
        err = ""
        if not ok:
            err = (raw or "")[:200]
        return {"model": model, "ok": ok, "status": st, "duration": dur, "error": err}

    def probe_models(self, models: list[str], workers: int = 6, timeout: int = 40) -> list[dict]:
        """Probe many models in parallel so a sync can flag the live ones."""
        import concurrent.futures as cf

        out: list[dict] = []
        if not models:
            return out
        with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futs = {ex.submit(self.probe_model, m, timeout): m for m in models}
            for f in cf.as_completed(futs):
                try:
                    out.append(f.result())
                except Exception as e:
                    out.append({"model": futs[f], "ok": False, "status": 0, "error": str(e)[:200]})
        out.sort(key=lambda r: (not r["ok"], r["model"]))
        return out

    def healthy_models(self) -> list[str]:
        cfg = config.load()
        meta = cfg["gateway"].get("model_meta", {})
        return [mid for mid, m in meta.items() if (m or {}).get("health", {}).get("ok")]

    # ------------------------------------------------------------------ chat
    def chat(self, model: str, messages: list[dict], timeout: int = 180, max_tokens: int = 2048, retries: int = 2) -> dict:
        last = ""
        for attempt in range(max(1, retries)):
            st, raw = _req(
                f"{self.api_base}/chat/completions",
                key=self.api_key,
                method="POST",
                body={"model": model, "messages": messages, "max_tokens": max_tokens},
                timeout=timeout,
            )
            if st == 200:
                d = _first_json(raw)
                try:
                    msg = d["choices"][0]["message"]
                    # Reasoning models answer with an empty `content` while the
                    # text sits in `reasoning` / `reasoning_content`. Treating
                    # that as a failure breaks planning and review on models that
                    # work perfectly well.
                    content = msg.get("content")
                    if isinstance(content, list):
                        # Some providers send content as parts.
                        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                    reason = msg.get("reasoning") or msg.get("reasoning_content") or ""
                    # Isi `reasoning` adalah jalan pikir, bukan jawaban. Dipakai
                    # hanya kalau `content` benar-benar kosong, dan hasilnya
                    # dibersihkan supaya jalan pikir mentah tidak pernah tampil
                    # sebagai jawaban pengguna.
                    if str(content or "").strip():
                        text = content
                    else:
                        text = _buang_jalan_pikir(str(reason))
                    if not str(text).strip():
                        last = f"empty reply: {(raw or '')[:200]}"
                        raise ValueError(last)
                    return {"ok": True, "text": text, "usage": d.get("usage", {}), "attempts": attempt + 1}
                except Exception as e:
                    last = f"parse: {e}: {(raw or '')[:200]}"
            else:
                last = f"HTTP {st}: {(raw or '')[:300]}"
                # 429/503 are worth one more try with a different route
                if st not in (429, 502, 503, 0):
                    break
            import time as _t

            _t.sleep(1.5 * (attempt + 1))
        return {"ok": False, "error": last}
