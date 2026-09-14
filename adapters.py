"""Worker adapters: Claude Code, Codex, OpenCode, OMP.

Each worker is a separate CLI with its own config format, so each adapter owns
its own detection + config-write + invocation shape. Nothing here assumes a
shared API.

Verified shapes (inspected on this machine):
  claude    v2.1.270  ~/.claude/settings.json  env.ANTHROPIC_BASE_URL /
            ANTHROPIC_AUTH_TOKEN / ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU}_MODEL
            non-interactive: claude -p "<task>" --output-format json
  codex     v0.154.0  ~/.codex/config.toml [model_providers.9router] +
            model / model_provider, auth via env OPENAI_API_KEY
            non-interactive: codex exec "<task>"
  opencode  v1.18.30  ~/.config/opencode/opencode.json
            provider.9router = {npm, options:{baseURL,apiKey}, models:{}} + model
            non-interactive: opencode run "<task>"
  omp       oh-my-pi  ~/.config/omp (CLI is provider/env driven)
            non-interactive: omp -p "<task>" (falls back to `omp run`)
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
from typing import Any

import yaml

import config
import hub

HOME = pathlib.Path.home()


def _run(cmd: list[str], timeout: int = 20, env: dict | None = None, cwd: str | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, **(env or {})},
            cwd=cwd,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:  # pragma: no cover
        return 1, str(e)


class Worker:
    key = "base"
    label = "Base"
    binary = "base"

    def __init__(self) -> None:
        self.version = ""
        self.path = ""
        self.error = ""

    # ---- capability probe ------------------------------------------------
    def probe(self) -> dict:
        self.path = shutil.which(self.binary) or ""
        if not self.path:
            self.error = "binary not found on PATH"
            return self.status()
        rc, out = _run([self.path, "--version"], timeout=25)
        self.version = (out.strip().splitlines() or [""])[0][:80]
        self.error = "" if rc == 0 else out.strip()[:200]
        return self.status()

    def status(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "installed": bool(self.path),
            "path": self.path,
            "version": self.version,
            "error": self.error,
            "config_path": str(self.config_path()) if self.config_path() else "",
        }

    # ---- config ----------------------------------------------------------
    def config_path(self) -> pathlib.Path | None:
        return None

    def current_model(self) -> str:
        return ""

    def apply(self, gateway: dict) -> dict:
        raise NotImplementedError

    def env(self, gateway: dict, model: str) -> dict:
        return {}

    def command(self, task: str, model: str, cwd: str) -> list[str]:
        raise NotImplementedError

    def parse(self, raw: str) -> dict:
        return {"text": raw[-8000:], "raw_len": len(raw)}


# --------------------------------------------------------------------------
class ClaudeAdapter(Worker):
    key = "claude"
    label = "Claude Code"
    binary = "claude"

    def config_path(self) -> pathlib.Path:
        return HOME / ".claude" / "settings.json"

    def _read(self) -> dict:
        try:
            return json.loads(self.config_path().read_text())
        except Exception:
            return {}

    def current_model(self) -> str:
        return self._read().get("env", {}).get("ANTHROPIC_DEFAULT_SONNET_MODEL", "")

    def apply(self, gateway: dict) -> dict:
        p = self.config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        cfg = self._read()
        model = gateway["model"]
        env = cfg.setdefault("env", {})
        env["ANTHROPIC_BASE_URL"] = gateway["base_url"]
        env["ANTHROPIC_AUTH_TOKEN"] = gateway["api_key"]
        for slot in ("SONNET", "OPUS", "HAIKU"):
            env[f"ANTHROPIC_DEFAULT_{slot}_MODEL"] = model
        cfg.setdefault("permissions", {"allow": ["Bash", "Edit", "Write", "Read"]})
        p.write_text(json.dumps(cfg, indent=2))
        return {"config_path": str(p), "model": model}

    def env(self, gateway: dict, model: str) -> dict:
        # Claude Code refuses --dangerously-skip-permissions as root unless it is
        # told it is running inside a sandbox (IS_SANDBOX=1). This is a container.
        return {
            "ANTHROPIC_BASE_URL": gateway["base_url"],
            "ANTHROPIC_AUTH_TOKEN": gateway["api_key"],
            "ANTHROPIC_API_KEY": gateway["api_key"],
            "IS_SANDBOX": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }

    def command(self, task: str, model: str, cwd: str) -> list[str]:
        # --model is passed explicitly: without it Claude Code reads the model
        # from settings.json and appends a "[1m]" context suffix that gateways
        # do not recognise.
        return [
            self.path or "claude",
            "-p",
            task,
            "--model",
            model,
            "--output-format",
            "json",
            "--dangerously-skip-permissions",
            "--max-turns",
            "40",
        ]

    def parse(self, raw: str) -> dict:
        out: dict[str, Any] = {"text": raw[-8000:], "raw_len": len(raw)}
        for line in reversed(raw.strip().splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if isinstance(d, dict) and ("result" in d or "session_id" in d):
                out["text"] = str(d.get("result", ""))[:8000]
                out["session_id"] = d.get("session_id")
                out["cost_usd"] = d.get("total_cost_usd")
                out["turns"] = d.get("num_turns")
                break
        return out


# --------------------------------------------------------------------------
class CodexAdapter(Worker):
    key = "codex"
    label = "Codex"
    binary = "codex"

    def config_path(self) -> pathlib.Path:
        return HOME / ".codex" / "config.toml"

    def current_model(self) -> str:
        p = self.config_path()
        if not p.exists():
            return ""
        for line in p.read_text().splitlines():
            if line.strip().startswith("model ="):
                return line.split("=", 1)[1].strip().strip('"')
        return ""

    def apply(self, gateway: dict) -> dict:
        p = self.config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        model = gateway["model"]
        base = gateway["api_base"]
        block = (
            f'model = "{model}"\n'
            'model_provider = "9router"\n'
            'approval_policy = "never"\n'
            'sandbox_mode = "danger-full-access"\n'
            "\n"
            "[model_providers.9router]\n"
            'name = "9Router"\n'
            f'base_url = "{base}"\n'
            'env_key = "OPENAI_API_KEY"\n'
            'wire_api = "responses"\n'
            'requires_openai_auth = false\n'
        )
        old = p.read_text() if p.exists() else ""
        # keep unrelated sections (mcp_servers, projects...) minus the keys we own
        keep: list[str] = []
        skip_section = False
        for line in old.splitlines():
            s = line.strip()
            if s.startswith("["):
                skip_section = s == "[model_providers.9router]"
                if not skip_section:
                    keep.append(line)
                continue
            if skip_section:
                continue
            if s.startswith(("model =", "model_provider =", "approval_policy =", "sandbox_mode =")):
                continue
            keep.append(line)
        body = "\n".join(keep).strip()
        p.write_text(block + ("\n" + body if body else "") + "\n")
        return {"config_path": str(p), "model": model}

    def env(self, gateway: dict, model: str) -> dict:
        return {"OPENAI_API_KEY": gateway["api_key"], "OPENAI_BASE_URL": gateway["api_base"]}

    def command(self, task: str, model: str, cwd: str) -> list[str]:
        # --dangerously-bypass-approvals-and-sandbox: codex's own sandbox helper
        # (bwrap) cannot create its synthetic mounts inside this proot container,
        # so every sandboxed read/write fails; the team already runs each worker
        # in its own project directory.
        return [
            self.path or "codex",
            "exec",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
            "-m",
            model,
            "-c",
            'model_provider="9router"',
            "-c",
            'approval_policy="never"',
            task,
        ]


# --------------------------------------------------------------------------
class OpenCodeAdapter(Worker):
    key = "opencode"
    label = "OpenCode"
    binary = "opencode"

    def config_path(self) -> pathlib.Path:
        return HOME / ".config" / "opencode" / "opencode.json"

    def _read(self) -> dict:
        try:
            return json.loads(self.config_path().read_text())
        except Exception:
            return {}

    def current_model(self) -> str:
        m = self._read().get("model", "")
        return m.split("/", 1)[1] if m.startswith("9router/") else m

    def apply(self, gateway: dict) -> dict:
        p = self.config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        cfg = self._read()
        model = gateway["model"]
        prov = cfg.setdefault("provider", {}).setdefault(
            "9router", {"npm": "@ai-sdk/openai-compatible", "options": {}, "models": {}}
        )
        prov.setdefault("options", {})
        prov["options"]["baseURL"] = gateway["api_base"]
        prov["options"]["apiKey"] = gateway["api_key"]
        prov.setdefault("models", {})[model] = {"name": model}
        cfg["model"] = f"9router/{model}"
        p.write_text(json.dumps(cfg, indent=2))
        return {"config_path": str(p), "model": model}

    def env(self, gateway: dict, model: str) -> dict:
        return {}

    def command(self, task: str, model: str, cwd: str) -> list[str]:
        # --auto: opencode asks for permission before edits otherwise, and this
        # worker runs unattended. It never touches the user's own directories,
        # only the team project dir.
        return [self.path or "opencode", "run", "--auto", "--model", f"9router/{model}", task]

    def parse(self, raw: str) -> dict:
        return {"text": raw[-8000:], "raw_len": len(raw)}


# --------------------------------------------------------------------------
class OMPAdapter(Worker):
    key = "omp"
    label = "OMP (oh-my-pi)"
    binary = "omp"
    PROVIDER = "9router"

    def __init__(self) -> None:
        super().__init__()
        self._help = ""

    def probe(self) -> dict:
        st = super().probe()
        if self.path:
            rc, out = _run([self.path, "--help"], timeout=25)
            self._help = out[:4000]
            st["help"] = self._help[:1200]
            st["flags"] = [
                f
                for f in ("-p", "--print", "run", "--model", "--provider", "--base-url", "--json")
                if f in self._help
            ]
        return st

    def config_path(self) -> pathlib.Path:
        # omp reads custom OpenAI-compatible providers from the model registry
        # file (~/.omp/agent/models.yml), not from a config.json. `omp config
        # path` confirms the agent dir; there is no global config.json.
        return HOME / ".omp" / "agent" / "models.yml"

    def current_model(self) -> str:
        try:
            doc = yaml.safe_load(self.config_path().read_text()) or {}
            models = doc["providers"][self.PROVIDER]["models"]
            return models[0]["id"] if models else ""
        except Exception:
            return ""

    def apply(self, gateway: dict) -> dict:
        """Register 9Router as a custom provider and select the active model.

        Without a models.yml entry omp answers `Model "<x>" not found` for any
        gateway model id, it only knows its bundled catalog.
        """
        p = self.config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except Exception:
            doc = {}
        doc.setdefault("providers", {})
        chain = [gateway["model"]] + [
            m for m in (gateway.get("fallback_models") or []) if m != gateway["model"]
        ]
        doc["providers"][self.PROVIDER] = {
            "baseUrl": gateway["api_base"],
            "apiKey": gateway["api_key"],
            "api": "openai-completions",
            "models": [
                {
                    "id": m,
                    "name": m,
                    "contextWindow": 131072,
                    "maxTokens": 32768,
                    "supportsTools": True,
                    "input": ["text"],
                }
                for m in chain
            ],
        }
        p.write_text(yaml.safe_dump(doc, sort_keys=False))
        return {"config_path": str(p), "model": f"{self.PROVIDER}/{gateway['model']}"}

    def env(self, gateway: dict, model: str) -> dict:
        # omp resolves the provider (and its key) from models.yml, so no base
        # URL env is needed; OPENAI_* would only hijack the built-in openai
        # provider and break its other models.
        return {}

    def command(self, task: str, model: str, cwd: str) -> list[str]:
        exe = self.path or "omp"
        cmd = [exe, "-p", task]
        if "--model" in self._help:
            cmd += ["--model", f"{self.PROVIDER}/{model}"]
        # --auto-approve: this worker runs unattended; without it omp stops at
        # the first write/edit approval prompt and the task hangs.
        if "--auto-approve" in self._help:
            cmd.append("--auto-approve")
        if "--no-session" in self._help:
            cmd.append("--no-session")
        return cmd


ADAPTERS: dict[str, Worker] = {
    "claude": ClaudeAdapter(),
    "codex": CodexAdapter(),
    "opencode": OpenCodeAdapter(),
    "omp": OMPAdapter(),
}


def status_all(refresh: bool = False) -> list[dict]:
    out = []
    for w in ADAPTERS.values():
        if refresh or not w.version and not w.error:
            try:
                w.probe()
            except Exception as e:
                w.error = str(e)
        out.append(w.status())
    return out


def apply_all(gateway: dict, only: list[str] | None = None) -> dict:
    """Push one gateway config to every worker config file. Never raises."""
    results: dict[str, Any] = {}
    for key, w in ADAPTERS.items():
        if only and key not in only:
            continue
        if not w.path:
            results[key] = {"ok": False, "error": "binary not installed"}
            continue
        try:
            results[key] = {"ok": True, **w.apply(gateway)}
        except Exception as e:
            results[key] = {"ok": False, "error": str(e)}
    hub.emit(
        "gateway",
        "Model diterapkan ke pekerja: "
        + ", ".join(f"{k}{'✓' if v.get('ok') else '✗'}" for k, v in results.items()),
        model=gateway.get("model"),
        results=results,
    )
    return results


# Paket npm tiap pekerja. Dipakai untuk menawarkan pemasangan otomatis dari UI,
# supaya satu clone bisa langsung jalan tanpa terminal.
PAKET: dict[str, str] = {
    "claude": "@anthropic-ai/claude-code",
    "codex": "@openai/codex",
    "opencode": "opencode-ai",
    "omp": "@oh-my-pi/pi-coding-agent",
}

SUMBER: dict[str, str] = {
    "claude": "https://docs.claude.com/en/docs/claude-code",
    "codex": "https://github.com/openai/codex",
    "opencode": "https://opencode.ai/docs",
    "omp": "https://github.com/oh-my-pi/pi-coding-agent",
}


def pasang_latar(key: str) -> str:
    """Pasang satu CLI pekerja lewat npm, di latar belakang.

    Dijalankan sebagai job supaya permintaan HTTP tidak menunggu unduhan.
    Sesudah selesai, probe diulang supaya UI langsung melihat versinya.
    """
    import plugins as _plugins

    paket = PAKET.get(key)

    def kerja(jid: str) -> dict:
        if not paket:
            return {"ok": False, "pesan": f"paket untuk {key} tidak diketahui"}
        npm = shutil.which("npm")
        if not npm:
            return {"ok": False, "pesan": "npm tidak ada di PATH, pasang Node.js 20 atau lebih baru"}
        # npm global bisa punya prefix sendiri dan meninggalkan file binernya di
        # tempat yang tidak ikut dijalankan sebagai postinstall. Menyalakan
        # script tetap benar untuk paket ini (npm 11 mematikannya dengan
        # default, dan tanpa ini paket seperti codex terpasang tanpa binernya).
        env = dict(os.environ)
        env.setdefault("npm_config_ignore_scripts", "false")
        # Jangan berjalan di folder kerja: npm bisa menganggapnya proyek lokal.
        env["PWD"] = "/tmp"
        _plugins.job_baris(jid, f"memasang {paket} lewat npm, perlu beberapa menit")
        rc, out = _run([npm, "install", "-g", paket, "--no-fund", "--no-audit"], timeout=900, env=env, cwd="/tmp")
        if rc != 0:
            return {"ok": False, "pesan": f"npm gagal: {out[-300:]}"}
        # Cache adapter menyimpan path lama; kosongkan supaya probe benar-benar
        # mencari biner yang baru dipasang, bukan mengulang hasil lama.
        ADAPTERS[key].path = ""
        ADAPTERS[key].version = ""
        ADAPTERS[key].error = ""
        st = ADAPTERS[key].probe()
        _plugins.job_baris(jid, f"{key}: {st.get('version') or st.get('error')}")
        if not st.get("installed"):
            # Kegagalan yang paling membingungkan: npm melaporkan sukses tapi
            # binernya tidak ada di PATH. Cari di prefix global dan, kalau
            # ketemu, pasang tautan supaya bisa dipanggil pekerja.
            alt = _cari_di_prefix(npm, key)
            if alt:
                ADAPTERS[key].path = alt
                st = ADAPTERS[key].probe()
                _plugins.job_baris(jid, f"{key}: dipakai dari {alt}")
            else:
                return {"ok": False, "pesan": f"{paket} terpasang tapi {key} tidak ada di PATH. Cek `npm prefix -g`."}
        return {"ok": bool(st.get("installed")), "pesan": f"{key} {st.get('version') or 'terpasang'}"}

    return _plugins.jalankan_latar(f"Pasang pekerja {key}", kerja)


def _cari_di_prefix(npm: str, key: str) -> str:
    """Cari biner pekerja di folder bin global npm, lalu tautkan ke /usr/local/bin.

    Dipakai hanya kalau probe gagal sesudah pemasangan. Dua sebab yang pernah
    terjadi di sini: pemasangan mendarat di prefix yang tidak ada di PATH, dan
    npm mengganti tautan lamanya dengan nama sementara (`.omp-XXXX`) tanpa
    pernah menaruh nama akhirnya. Jadi nama akhir dicari dulu, baru pola
    sementara itu.
    """
    rc, out = _run([npm, "prefix", "-g"], timeout=30)
    if rc != 0:
        return ""
    prefix = out.strip().splitlines()[-1] if out.strip() else ""
    if not prefix:
        return ""
    nama = ADAPTERS[key].binary
    bindir = pathlib.Path(prefix) / "bin"
    kandidat = bindir / nama
    if not kandidat.exists():
        sementara = sorted(bindir.glob(f".{nama}-*"))
        if not sementara:
            return ""
        kandidat = sementara[0]
    tujuan = pathlib.Path("/usr/local/bin") / nama
    try:
        if tujuan.is_symlink() or tujuan.exists():
            tujuan.unlink()
        tujuan.symlink_to(kandidat)
    except Exception:
        return str(kandidat)
    return str(tujuan)


def build_command(worker: str, task: str, model: str, cwd: str) -> tuple[list[str], dict]:
    w = ADAPTERS[worker]
    return w.command(task, model, cwd), w.env({"base_url": config.load()["gateway"]["base_url"], "api_base": config.load()["gateway"]["api_base"], "api_key": config.load()["gateway"]["api_key"], "model": model}, model)
