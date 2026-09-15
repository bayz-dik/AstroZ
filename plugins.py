"""Alat bantu untuk pekerja: plugin MCP, paket skill dari GitHub, dan daftar marketplace.

Semua fitur di sini jalan dari UI, tanpa terminal. Tiga hal yang dikelola:

1. MCP (plugin ala Claude/ChatGPT). Satu definisi ditulis ke konfigurasi setiap
   CLI pekerja dengan formatnya masing-masing. Format yang dipakai sudah
   diverifikasi dengan menambah satu server contoh lalu membacanya kembali:
     claude   -> ~/.claude.json, kunci mcpServers  (claude mcp add --scope user)
     codex    -> ~/.codex/config.toml, [mcp_servers.<nama>]  (codex mcp add)
     opencode -> ~/.config/opencode/opencode.json, kunci mcp  (opencode mcp add)
     omp      -> ~/.omp/agent/mcp.json, {"$schema": ..., "mcpServers": {...}}
2. Paket skill dari GitHub: git clone ke ~/.astroz/skills/<nama>, lalu tautkan
   ke folder yang dibaca tiap CLI. Isinya folder dengan SKILL.md, format yang
   dipakai claude, codex, opencode, dan omp.
3. Daftar marketplace plugin yang bisa dipasang dari UI.

Pekerjaan yang lama (clone, pemasangan) dijalankan sebagai job di latar belakang
supaya permintaan HTTP tidak menunggu, dan hasilnya masuk ke feed kejadian.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import threading
import time
import uuid

import config
import hub

HOME = pathlib.Path.home()
DATA = HOME / ".astroz"
SKILL_DIR = DATA / "skills"          # hasil clone, satu folder per paket
MCP_MARK = DATA / "mcp.json"         # salinan definisi supaya bisa dibaca ulang
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()

NAMA_AMAN = re.compile(r"[^A-Za-z0-9._-]+")


# ------------------------------------------------------------------ util

def _aman(nama: str, bawaan: str = "tanpa-nama") -> str:
    n = NAMA_AMAN.sub("-", (nama or "").strip()).strip("-.")
    return n[:60] or bawaan


def _env_git() -> dict:
    return {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/true",
        "GIT_CONFIG_NOSYSTEM": "1",
        # Di container proot ini uv gagal memasang paket dengan cara hardlink
        # ("Operation not permitted"), jadi salin saja. Terukur: tanpa ini
        # `uvx mcp-server-...` gagal sebelum server sempat jalan.
        "UV_LINK_MODE": "copy",
        "PATH": os.pathsep.join(
            [str(pathlib.Path.home() / ".hermes" / "bin"), os.environ.get("PATH", "")]
        ),
    }


def _jalankan(cmd: list[str], timeout: int = 300, cwd: str | None = None) -> dict:
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=_env_git()
        )
        return {"rc": p.returncode, "out": ((p.stdout or "") + (p.stderr or ""))[-4000:]}
    except FileNotFoundError:
        return {"rc": 127, "out": f"{cmd[0]} tidak ada di PATH"}
    except subprocess.TimeoutExpired:
        return {"rc": 124, "out": f"melebihi batas waktu {timeout}s"}
    except Exception as e:
        return {"rc": 1, "out": f"{type(e).__name__}: {e}"}


def _baca_json(path: pathlib.Path) -> dict:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _tulis_json(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(path)


# ------------------------------------------------------------------ job

def job_mulai(judul: str) -> str:
    jid = uuid.uuid4().hex[:10]
    with JOBS_LOCK:
        JOBS[jid] = {"id": jid, "judul": judul, "status": "jalan", "mulai": time.time(), "baris": [], "hasil": ""}
    hub.emit("system", f"Mulai: {judul}", job=jid, phase="start")
    return jid


def job_baris(jid: str, teks: str) -> None:
    with JOBS_LOCK:
        j = JOBS.get(jid)
        if not j:
            return
        j["baris"].append(teks)
        j["baris"] = j["baris"][-200:]
    hub.emit("system", teks, job=jid)


def job_selesai(jid: str, ok: bool, hasil: str = "") -> None:
    with JOBS_LOCK:
        j = JOBS.get(jid)
        if not j:
            return
        j["status"] = "selesai" if ok else "gagal"
        j["hasil"] = hasil
        j["akhir"] = time.time()
    hub.emit("system", hasil or ("selesai" if ok else "gagal"), job=jid, ok=ok, phase="end")


def job_lihat(jid: str) -> dict | None:
    with JOBS_LOCK:
        return JOBS.get(jid)


def job_daftar(limit: int = 20) -> list[dict]:
    with JOBS_LOCK:
        items = sorted(JOBS.values(), key=lambda j: j.get("mulai") or 0, reverse=True)
        return [{k: v for k, v in j.items() if k != "baris"} for j in items[:limit]]


def jalankan_latar(judul: str, fn) -> str:
    """Jalankan fn(jid) di thread terpisah, hasilnya jadi job yang bisa dipantau UI."""
    jid = job_mulai(judul)

    def bungkus() -> None:
        try:
            hasil = fn(jid)
            if isinstance(hasil, dict) and hasil.get("ok") is False:
                job_selesai(jid, False, hasil.get("pesan") or "gagal")
            else:
                job_selesai(jid, True, (hasil or {}).get("pesan") if isinstance(hasil, dict) else str(hasil or ""))
        except Exception as e:
            job_selesai(jid, False, f"{type(e).__name__}: {e}")

    threading.Thread(target=bungkus, daemon=True).start()
    return jid


# ------------------------------------------------------------------ MCP

def _klien() -> dict[str, str]:
    """CLI yang terpasang, dipakai untuk menulis definisi MCP."""
    import adapters

    out: dict[str, str] = {}
    for key, a in adapters.ADAPTERS.items():
        if not a.path:
            a.probe()
        if a.path:
            out[key] = a.path
    return out


def mcp_simpan_mark() -> None:
    """Simpan salinan definisi supaya daftar bisa dibaca walau CLI tidak ada."""
    data = _baca_json(MCP_MARK)
    _tulis_json(MCP_MARK, data)


def mcp_definisi(nama: str, transport: str, target: str, args: list[str] | None = None,
                 env: dict | None = None, header: dict | None = None) -> dict:
    """Bentuk seragam: satu definisi, empat format tulis."""
    return {
        "nama": nama,
        "transport": transport if transport in ("stdio", "http", "sse") else "stdio",
        "target": target,
        "args": args or [],
        "env": env or {},
        "header": header or {},
    }


def mcp_tulis_satu(worker: str, d: dict) -> dict:
    """Tulis satu definisi ke konfigurasi satu CLI, format asli masing-masing."""
    nama = d["nama"]
    if worker == "claude":
        cmd = ["claude", "mcp", "add", "--scope", "user", nama]
        if d["transport"] in ("http", "sse"):
            cmd += ["--transport", "http" if d["transport"] == "http" else "sse", d["target"]]
            for k, v in d["header"].items():
                cmd += ["-H", f"{k}: {v}"]
        else:
            for k, v in d["env"].items():
                cmd += ["-e", f"{k}={v}"]
            cmd += ["--", d["target"], *d["args"]]
        return _jalankan(cmd, timeout=90)

    if worker == "codex":
        # codex menyimpan di ~/.codex/config.toml: [mcp_servers.<nama>]
        p = HOME / ".codex" / "config.toml"
        blok = [f"[mcp_servers.{nama}]"]
        if d["transport"] in ("http", "sse"):
            blok.append(f'url = "{d["target"]}"')
        else:
            blok.append(f'command = "{d["target"]}"')
            if d["args"]:
                blok.append("args = [" + ", ".join(json.dumps(a) for a in d["args"]) + "]")
            if d["env"]:
                blok.append("[mcp_servers." + nama + ".env]")
                blok += [f'{k} = "{v}"' for k, v in d["env"].items()]
        _sisip_toml(p, nama, blok)
        return {"rc": 0, "out": f"ditulis ke {p}"}

    if worker == "opencode":
        p = HOME / ".config" / "opencode" / "opencode.json"
        cfg = _baca_json(p)
        mcp = cfg.setdefault("mcp", {})
        if d["transport"] in ("http", "sse"):
            mcp[nama] = {"type": "remote", "url": d["target"], "enabled": True}
            if d["header"]:
                mcp[nama]["headers"] = d["header"]
        else:
            mcp[nama] = {"type": "local", "command": [d["target"], *d["args"]], "enabled": True}
            if d["env"]:
                mcp[nama]["environment"] = d["env"]
        _tulis_json(p, cfg)
        return {"rc": 0, "out": f"ditulis ke {p}"}

    if worker == "omp":
        p = HOME / ".omp" / "agent" / "mcp.json"
        cfg = _baca_json(p)
        cfg.setdefault("$schema", "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json")
        servers = cfg.setdefault("mcpServers", {})
        if d["transport"] in ("http", "sse"):
            servers[nama] = {"type": "streamable-http" if d["transport"] == "http" else "sse",
                             "url": d["target"], **({"headers": d["header"]} if d["header"] else {})}
        else:
            servers[nama] = {"type": "stdio", "command": d["target"],
                             **({"args": d["args"]} if d["args"] else {}),
                             **({"env": d["env"]} if d["env"] else {})}
        _tulis_json(p, cfg)
        return {"rc": 0, "out": f"ditulis ke {p}"}

    return {"rc": 1, "out": f"pekerja {worker} tidak dikenal"}


def _sisip_toml(path: pathlib.Path, nama: str, blok: list[str]) -> None:
    """Ganti blok [mcp_servers.<nama>] kalau ada, sisipkan kalau belum."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lama = path.read_text() if path.exists() else ""
    baris = lama.splitlines()
    keluar: list[str] = []
    buang = False
    kepala = f"[mcp_servers.{nama}"
    for b in baris:
        s = b.strip()
        if s.startswith("["):
            buang = s.startswith(kepala)
            if buang:
                continue
        if not buang:
            keluar.append(b)
    isi = "\n".join(keluar).rstrip()
    path.write_text((isi + "\n\n" if isi else "") + "\n".join(blok) + "\n")


def mcp_hapus_satu(worker: str, nama: str) -> dict:
    if worker == "claude":
        return _jalankan(["claude", "mcp", "remove", "--scope", "user", nama], timeout=90)
    if worker == "codex":
        p = HOME / ".codex" / "config.toml"
        if not p.exists():
            return {"rc": 0, "out": "tidak ada berkas"}
        baris = p.read_text().splitlines()
        keluar: list[str] = []
        buang = False
        for b in baris:
            s = b.strip()
            if s.startswith("["):
                buang = s.startswith(f"[mcp_servers.{nama}") or s.startswith(f"[mcp_servers.{nama}.")
            if not buang:
                keluar.append(b)
        p.write_text("\n".join(keluar).rstrip() + "\n")
        return {"rc": 0, "out": f"dihapus dari {p}"}
    if worker == "opencode":
        p = HOME / ".config" / "opencode" / "opencode.json"
        cfg = _baca_json(p)
        (cfg.get("mcp") or {}).pop(nama, None)
        _tulis_json(p, cfg)
        return {"rc": 0, "out": f"dihapus dari {p}"}
    if worker == "omp":
        p = HOME / ".omp" / "agent" / "mcp.json"
        cfg = _baca_json(p)
        (cfg.get("mcpServers") or {}).pop(nama, None)
        _tulis_json(p, cfg)
        return {"rc": 0, "out": f"dihapus dari {p}"}
    return {"rc": 1, "out": f"pekerja {worker} tidak dikenal"}


def mcp_daftar() -> list[dict]:
    """Gabungan definisi dari keempat CLI, satu baris per nama."""
    out: dict[str, dict] = {}

    def tambah(nama: str, worker: str, bentuk: str, detail: str) -> None:
        if not nama:
            return
        e = out.setdefault(nama, {"nama": nama, "pekerja": [], "transport": bentuk, "detail": detail})
        if worker not in e["pekerja"]:
            e["pekerja"].append(worker)

    # claude: ~/.claude.json -> mcpServers (kunci global)
    d = _baca_json(HOME / ".claude.json")
    for nama, v in (d.get("mcpServers") or {}).items():
        tr = v.get("type") or ("stdio" if v.get("command") else "http")
        detail = v.get("command") or v.get("url") or ""
        if v.get("args"):
            detail += " " + " ".join(str(a) for a in v["args"])
        tambah(nama, "claude", tr, detail[:160])

    # codex: ~/.codex/config.toml
    p = HOME / ".codex" / "config.toml"
    if p.exists():
        teks = p.read_text()
        for m in re.finditer(r"^\[mcp_servers\.([A-Za-z0-9._-]+)\]\s*$(.*?)(?=^\[|\Z)", teks, re.M | re.S):
            nama, isi = m.group(1), m.group(2)
            cmd = re.search(r'command\s*=\s*"([^"]+)"', isi)
            url = re.search(r'url\s*=\s*"([^"]+)"', isi)
            args = re.findall(r'"([^"]+)"', (re.search(r"args\s*=\s*\[([^\]]*)\]", isi) or re.search(r"()", "")).group(1)) if "args" in isi else []
            tambah(nama, "codex", "http" if url else "stdio",
                   (url.group(1) if url else (cmd.group(1) if cmd else "")) + ((" " + " ".join(args)) if args else ""))

    # opencode: ~/.config/opencode/opencode.json -> mcp
    d = _baca_json(HOME / ".config" / "opencode" / "opencode.json")
    for nama, v in (d.get("mcp") or {}).items():
        if not isinstance(v, dict):
            continue
        tr = "http" if v.get("type") == "remote" else "stdio"
        detail = v.get("url") or " ".join(v.get("command") or [])
        tambah(nama, "opencode", tr, str(detail)[:160])

    # omp: ~/.omp/agent/mcp.json -> mcpServers
    d = _baca_json(HOME / ".omp" / "agent" / "mcp.json")
    for nama, v in (d.get("mcpServers") or {}).items():
        if not isinstance(v, dict):
            continue
        tr = "http" if v.get("type") in ("streamable-http", "http") else "stdio"
        detail = v.get("url") or " ".join([str(v.get("command") or ""), *[str(a) for a in (v.get("args") or [])]])
        tambah(nama, "omp", tr, detail[:160])

    return sorted(out.values(), key=lambda e: e["nama"].lower())


def mcp_pasang(d: dict, pekerja: list[str] | None = None) -> dict:
    klien = _klien()
    sasaran = [w for w in (pekerja or list(klien.keys())) if w in klien]
    hasil: dict[str, str] = {}
    for w in sasaran:
        # pasang ulang: hapus dulu supaya tidak menumpuk
        mcp_hapus_satu(w, d["nama"])
        r = mcp_tulis_satu(w, d)
        hasil[w] = "ok" if r.get("rc") == 0 else r.get("out", "gagal")
    mark = _baca_json(MCP_MARK)
    mark[d["nama"]] = d
    _tulis_json(MCP_MARK, mark)
    return hasil


def mcp_panaskan(d: dict, jid: str = "") -> None:
    """Unduh paket server lebih dulu.

    Terukur: sambungan pertama ke server npx/uvx gagal dengan pesan
    "connection closed" atau habis waktu 30 detik, karena paketnya baru diunduh
    saat itu. Mengunduh lebih dulu di sini membuat pemakaian pertama langsung
    tersambung. Dijalankan tanpa stdin supaya server langsung keluar setelah
    terpasang.
    """
    if d.get("transport") != "stdio":
        return
    target = d.get("target") or ""
    if pathlib.Path(target).name not in ("npx", "uvx", "uv", "bunx", "pnpm"):
        return
    cmd = [target, *d.get("args", [])]
    if jid:
        job_baris(jid, "mengunduh paket server lebih dulu: " + " ".join(cmd[:4]))
    try:
        subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=240,
            env=_env_git(),
        )
    except subprocess.TimeoutExpired:
        pass  # server memang menunggu di stdin, paketnya sudah terunduh
    except Exception as e:
        if jid:
            job_baris(jid, f"pemanasan gagal: {type(e).__name__}: {e}")


def mcp_pasang_latar(d: dict, pekerja: list[str] | None = None) -> str:
    """Pasang plugin MCP di latar belakang: tulis konfigurasi lalu unduh paketnya."""
    def kerja(jid: str) -> dict:
        job_baris(jid, f"menulis definisi {d['nama']} ke konfigurasi pekerja")
        hasil = mcp_pasang(d, pekerja)
        gagal = [k for k, v in hasil.items() if v != "ok"]
        mcp_panaskan(d, jid)
        if gagal and len(gagal) == len(hasil):
            return {"ok": False, "pesan": f"gagal ditulis ke: {', '.join(gagal)}"}
        pakai = ", ".join(k for k, v in hasil.items() if v == "ok")
        return {"ok": True, "pesan": f"{d['nama']} terpasang di: {pakai}"}

    return jalankan_latar(f"Pasang plugin {d['nama']}", kerja)


def mcp_hapus(nama: str) -> dict:
    hasil = {}
    for w in _klien():
        r = mcp_hapus_satu(w, nama)
        hasil[w] = "ok" if r.get("rc") == 0 else r.get("out", "gagal")
    mark = _baca_json(MCP_MARK)
    mark.pop(nama, None)
    _tulis_json(MCP_MARK, mark)
    return hasil


# ------------------------------------------------------------------ skill

def skill_daftar() -> list[dict]:
    """Paket skill yang sudah dikloning, plus berapa folder SKILL.md di dalamnya."""
    out: list[dict] = []
    if not SKILL_DIR.exists():
        return out
    for paket in sorted(SKILL_DIR.iterdir()):
        if not paket.is_dir():
            continue
        skills = [p.parent.name for p in paket.rglob("SKILL.md")][:80]
        out.append({
            "nama": paket.name,
            "jumlah": len(skills),
            "contoh": skills[:6],
            "path": str(paket),
            "ukuran": _ukuran(paket),
        })
    return out


def _ukuran(p: pathlib.Path) -> str:
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except Exception:
            pass
    if total > 1024 * 1024:
        return f"{total / 1024 / 1024:.1f} MB"
    return f"{max(1, total // 1024)} KB"


def _folder_tautan() -> dict[str, set[str]]:
    """Peta nama skill -> label CLI yang memilikinya, dibaca sekali.

    Menanyakan `(t / nama).exists()` untuk tiap skill kali tiap folder berarti
    ratusan panggilan stat setiap kali halaman dibuka, dan itu membuat halaman
    Skill terpasang terasa menggantung. Satu kali pemindaian folder jauh lebih
    cepat dan hasilnya sama.
    """
    # Nama folder terakhir semuanya "skills", jadi labelnya diambil dari induk
    # yang berbeda-beda: .claude, .agents, .codex, .omp. Tanpa ini semua baris
    # tertulis "skills" dan tidak memberi tahu CLI mana yang memakainya.
    label = {".claude": "claude", ".agents": "agents", ".codex": "codex", ".omp": "omp"}
    peta: dict[str, set[str]] = {}
    for tujuan in skill_folder_cli():
        if not tujuan.exists():
            continue
        nama_cli = next((v for k, v in label.items() if k in tujuan.parts), tujuan.name)
        try:
            for e in tujuan.iterdir():
                peta.setdefault(e.name, set()).add(nama_cli)
        except Exception:
            continue
    return peta


def skill_folder_cli() -> list[pathlib.Path]:
    """Folder yang dibaca tiap CLI untuk skill.

    claude   ~/.claude/skills        (terverifikasi dari daftar folder yang dipindai)
    opencode ~/.claude/skills, ~/.agents/skills  (terverifikasi dari bantuan CLI-nya)
    codex    $CODEX_HOME/skills      (terverifikasi dari teks bantuan di binari)
    omp      ~/.omp/agent/skills, ~/.omp/skills  (terverifikasi dari pesan di binari)
    """
    home = HOME
    return [
        home / ".claude" / "skills",
        home / ".agents" / "skills",
        home / ".codex" / "skills",
        home / ".omp" / "agent" / "skills",
        home / ".omp" / "skills",
    ]


def skill_tautkan(paket_dir: pathlib.Path, jid: str = "") -> int:
    """Tautkan setiap folder berisi SKILL.md ke folder yang dibaca CLI."""
    n = 0
    folders = [p.parent for p in paket_dir.rglob("SKILL.md")]
    for f in folders:
        nama = f.name
        for tujuan in skill_folder_cli():
            tujuan.mkdir(parents=True, exist_ok=True)
            link = tujuan / nama
            try:
                if link.is_symlink() or link.exists():
                    if link.is_symlink() and link.resolve() == f.resolve():
                        n += 1
                        continue
                    if link.is_symlink():
                        link.unlink()
                    else:
                        continue  # jangan timpa folder milik pengguna
                link.symlink_to(f.resolve(), target_is_directory=True)
                n += 1
            except Exception:
                continue
    if jid:
        job_baris(jid, f"{len(folders)} folder skill ditautkan ke {n} lokasi")
    return n


def skill_pasang(url: str, nama: str = "") -> str:
    """Clone repo skill dari GitHub lalu tautkan. Jalan di latar belakang."""
    url = (url or "").strip()
    if not url:
        raise ValueError("url repo kosong")
    if not (url.startswith("http") or url.startswith("git@") or re.fullmatch(r"[\w.-]+/[\w.-]+", url)):
        raise ValueError("url harus https://github.com/... atau pemilik/repo")
    if re.fullmatch(r"[\w.-]+/[\w.-]+", url):
        url = "https://github.com/" + url + ".git"
    if url.startswith("https://github.com/") and not url.endswith(".git"):
        url = url + ".git"
    slug = _aman(nama or url.rstrip("/").split("/")[-1].removesuffix(".git"), "skill-pack")
    tujuan = SKILL_DIR / slug

    def kerja(jid: str) -> dict:
        SKILL_DIR.mkdir(parents=True, exist_ok=True)
        if tujuan.exists():
            job_baris(jid, f"{slug} sudah ada, memperbarui")
            r = _jalankan(["git", "-C", str(tujuan), "pull", "--ff-only"], timeout=300)
        else:
            job_baris(jid, f"mengkloning {url}")
            r = _jalankan(["git", "clone", "--depth", "1", url, str(tujuan)], timeout=600)
        if r.get("rc") != 0 and not tujuan.exists():
            return {"ok": False, "pesan": f"clone gagal: {r.get('out', '')[:300]}"}
        n = skill_tautkan(tujuan, jid)
        ada = len(list(tujuan.rglob("SKILL.md")))
        if not ada:
            return {"ok": False, "pesan": f"{slug} tidak punya berkas SKILL.md, bukan paket skill"}
        return {"ok": True, "pesan": f"{slug}: {ada} skill siap dipakai pekerja ({n} tautan)"}

    return jalankan_latar(f"Pasang skill {slug}", kerja)


def skill_hapus(nama: str) -> dict:
    p = SKILL_DIR / _aman(nama)
    if not p.exists():
        return {"ok": False, "pesan": "paket tidak ada"}
    # lepaskan tautan dulu supaya tidak ada tautan rusak
    for f in [x.parent for x in p.rglob("SKILL.md")]:
        for tujuan in skill_folder_cli():
            link = tujuan / f.name
            try:
                if link.is_symlink():
                    link.unlink()
            except Exception:
                pass
    shutil.rmtree(p, ignore_errors=True)
    hub.emit("system", f"Paket skill {nama} dihapus")
    return {"ok": True, "pesan": f"{nama} dihapus"}


def skill_ringkas_untuk_pekerja(limit: int = 40) -> list[str]:
    """Nama skill yang siap dipakai, untuk diberitahukan ke pekerja."""
    nama: list[str] = []
    for folder in skill_folder_cli():
        if not folder.exists():
            continue
        try:
            for e in sorted(folder.iterdir()):
                if e.name.startswith("."):
                    continue
                if (e / "SKILL.md").exists() or (e.is_symlink() and e.is_dir()):
                    if e.name not in nama:
                        nama.append(e.name)
        except Exception:
            continue
    return nama[:limit]


def _akar_repo() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent


def skill_bawaan_siap() -> list[dict]:
    """Skill bawaan repo: folder `skills/` yang ikut ter-clone bersama AstroZ.

    Tiap paket ditautkan seperti paket hasil clone, jadi setelah pemasangan
    pekerja memakai skill yang sama tanpa perintah tambahan. Ini yang membuat
    clone baru langsung punya skill, tanpa memasangnya satu per satu dari UI.
    """
    akar = _akar_repo() / "skills"
    out: list[dict] = []
    if not akar.exists():
        return out
    peta = _folder_tautan()
    for paket in sorted(akar.iterdir()):
        if not paket.is_dir() or paket.name.startswith("."):
            continue
        jumlah_md = 0
        tertaut = 0
        for md in paket.rglob("SKILL.md"):
            jumlah_md += 1
            if md.parent.name in peta:
                tertaut += 1
        out.append({
            "nama": paket.name,
            "jumlah": jumlah_md,
            "tertaut": tertaut,
            "perlu": jumlah_md > 0 and tertaut < jumlah_md,
            "sumber": str(paket),
        })
    return out


def skill_pasang_bawaan() -> dict:
    """Tautkan semua paket skill bawaan ke folder yang dibaca pekerja."""
    akar = _akar_repo() / "skills"
    if not akar.exists():
        return {"ok": False, "pesan": "folder skills/ tidak ada di repo"}
    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    paket_dipasang: list[str] = []
    n_tautan = 0
    for paket in sorted(akar.iterdir()):
        if not paket.is_dir() or paket.name.startswith("."):
            continue
        jumlah = len(list(paket.rglob("SKILL.md")))
        if not jumlah:
            continue
        tujuan = SKILL_DIR / paket.name
        # Salinan isinya, bukan tautan ke repo: `~/.astroz/skills` yang dipindai
        # halaman Skill terpasang, dan tautan ke repo bisa putus kalau repo
        # dipindah. Isinya kecil (beberapa MB), jadi disalin sekali.
        try:
            if tujuan.exists():
                shutil.rmtree(tujuan, ignore_errors=True)
            shutil.copytree(paket, tujuan)
        except Exception as e:
            hub.emit("system", f"Skill bawaan {paket.name} gagal disalin: {e}", ok=False)
            continue
        n_tautan += skill_tautkan(tujuan)
        paket_dipasang.append(paket.name)
    hub.emit("system", f"Skill bawaan dipasang: {', '.join(paket_dipasang) or 'tidak ada'} ({n_tautan} tautan)")
    return {"ok": True, "paket": paket_dipasang, "tautan": n_tautan}


def pasang_bawaan_sekali() -> None:
    """Dipanggil sekali saat server mulai: pasang skill bawaan yang belum ada."""
    try:
        for s in skill_bawaan_siap():
            if s["perlu"]:
                skill_pasang_bawaan()
                return
    except Exception as e:
        hub.emit("system", f"Pemeriksaan skill bawaan gagal: {e}", ok=False)


def _keterangan_skill(md: pathlib.Path) -> str:
    """Ambil baris `description:` dari frontmatter SKILL.md, kalau ada."""
    try:
        # Hanya kepala berkasnya: SKILL.md bisa panjang, dan yang dicari selalu
        # ada di frontmatter.
        with open(md, encoding="utf-8", errors="replace") as fh:
            teks = fh.read(6000)
    except Exception:
        return ""
    m = re.search(r"^description:\s*(.+)$", teks, re.M)
    if not m:
        return ""
    ket = m.group(1).strip().strip("\"'")
    return ket[:200]


# Cache halaman "Skill terpasang": membaca 174 berkas SKILL.md setiap kali
# halaman dibuka membuatnya terasa menggantung, padahal isinya hanya berubah
# kalau ada paket dipasang atau dilepas.
_TERPASANG: dict[str, object] = {"t": 0.0, "isi": []}
_TERPASANG_DETIK = 30


def skill_terpasang(segarkan: bool = False) -> list[dict]:
    """Daftar datar semua skill yang sudah terpasang, bukan per paket.

    Halaman "Skill terpasang" menampilkan satu baris per skill: nama, paket
    asalnya, keterangan singkat, dan ke folder CLI mana saja ia tertaut. Daftar
    per paket tidak cukup di situ karena satu paket bisa berisi puluhan skill.
    """
    t_lama = _TERPASANG["t"]
    if not segarkan and _TERPASANG["isi"] and isinstance(t_lama, float) and time.time() - t_lama < _TERPASANG_DETIK:
        return _TERPASANG["isi"]  # type: ignore[return-value]
    out: list[dict] = []
    if not SKILL_DIR.exists():
        return out
    peta = _folder_tautan()
    for paket in sorted(SKILL_DIR.iterdir()):
        if not paket.is_dir():
            continue
        for md in sorted(paket.rglob("SKILL.md")):
            f = md.parent
            out.append({
                "nama": f.name,
                "paket": paket.name,
                "keterangan": _keterangan_skill(md),
                "tautan": sorted(peta.get(f.name, set())),
                "path": str(f),
            })
    out.sort(key=lambda x: (x["paket"], x["nama"]))
    _TERPASANG["t"] = time.time()
    _TERPASANG["isi"] = out
    return out


# ------------------------------------------------------------------ marketplace

MARKETPLACE = [
    {
        "nama": "anthropics/skills",
        "url": "https://github.com/anthropics/skills",
        "jenis": "skill",
        "keterangan": "Kumpulan skill resmi Anthropic (docx, pdf, xlsx, dan lain lain).",
    },
    {
        "nama": "ComposioHQ/awesome-claude-skills",
        "url": "https://github.com/ComposioHQ/awesome-claude-skills",
        "jenis": "skill",
        "keterangan": "Daftar panjang skill buatan komunitas, siap dikloning.",
    },
    {
        "nama": "hesreallyhim/awesome-claude-code",
        "url": "https://github.com/hesreallyhim/awesome-claude-code",
        "jenis": "skill",
        "keterangan": "Kumpulan sumber daya Claude Code, termasuk paket skill.",
    },
    {
        "nama": "openai/skills",
        "url": "https://github.com/openai/skills",
        "jenis": "skill",
        "keterangan": "Skill resmi untuk Codex CLI.",
    },
    {
        "nama": "modelcontextprotocol/servers",
        "url": "https://github.com/modelcontextprotocol/servers",
        "jenis": "mcp",
        "keterangan": "Daftar server MCP resmi (filesystem, git, fetch, memory, dan lain lain).",
    },
]

# Plugin MCP siap pasang: nama, transport, target, args, keterangan.
# Hanya yang paketnya sudah terbukti terpasang di mesin ini. Server lain bisa
# ditambah sendiri lewat isian di UI.
MCP_SIAP = [
    {
        "nama": "memory",
        "transport": "stdio",
        "target": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "keterangan": "Catatan jangka panjang antar sesi, disimpan sebagai graf. Terbukti tersambung.",
    },
    {
        "nama": "everything",
        "transport": "stdio",
        "target": "npx",
        "args": ["-y", "@modelcontextprotocol/server-everything"],
        "keterangan": "Contoh server resmi untuk menguji apakah MCP tersambung. Terbukti tersambung.",
    },
    {
        "nama": "filesystem",
        "transport": "stdio",
        "target": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", str(HOME / "AstroZ" / "workspace")],
        "keterangan": "Baca dan tulis berkas di folder kerja, tanpa keluar dari folder itu.",
    },
]
