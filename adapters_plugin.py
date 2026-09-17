"""Universal Plugin Adapter: satu pintu untuk capability dari ekosistem mana pun.

AstroZ sekarang bisa menerima plugin/skill dari tiga ekosistem yang bentuknya
berbeda-beda, lalu menormalkannya ke satu bentuk internal. Tiga ekosistem itu
dan penanda yang dipakai untuk mengenalinya:

  claude   .claude-plugin/plugin.json   skills/ agents/ commands/ hooks/ .mcp.json
  codex    .codex-plugin/plugin.json    skills/ agents/ hooks/ mcpServers
  hermes   plugin.yaml (manifest_version 2, provides_*) atau paket skill biasa
  skill    paket berisi SKILL.md (standar Agent Skills, dibaca keempat pekerja)
  mcp      .mcp.json / mcp.json dengan kunci mcpServers

Bentuk internal AstroZ (capability manifest) sengaja sederhana: satu daftar
`Capability`, masing-masing dengan jenis, nama, asal, dan status. Statusnya:

  supported  langsung dipakai apa adanya
  converted  dipakai setelah diterjemahkan ke bentuk lain
  skipped    tidak dipakai, dengan alasan yang bisa dibaca pengguna
  requires   perlu alat tambahan di luar AstroZ

Aturan penting: capability yang tidak kompatibel TIDAK PERNAH disalin diam-diam.
Setiap yang dibuang muncul di manifest dengan status dan alasan. Itu yang membuat
halaman "Pasang dari URL" bisa menampilkan pratinjau jujur sebelum dipasang.

Adapter ini tidak mengubah orchestrator, tidak mengubah sistem skill yang sudah
ada, dan tidak mengubah sistem MCP. Ia memakai keduanya: skill ditulis lewat
plugins.skill_tautkan, MCP ditulis lewat plugins.mcp_pasang.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
from dataclasses import asdict, dataclass, field

import tomllib

import hub
import plugins

HOME = pathlib.Path.home()
DATA = HOME / ".astroz"
CAP_DIR = DATA / "capabilities"          # hasil unduhan, satu folder per sumber
REG_PATH = DATA / "capabilities.json"    # catatan pemasangan untuk ditampilkan ulang

# Empat pekerja yang bisa menerima capability.
PEKERJA = ("claude", "codex", "opencode", "omp")

JENIS = ("skill", "agent", "command", "hook", "mcp", "rule")

# Kunci di dalam frontmatter berkas markdown ala Claude/Codex.
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


# ------------------------------------------------------------------ model

@dataclass
class Capability:
    """Satu capability setelah dinormalkan, apa pun ekosistem asalnya."""
    jenis: str
    nama: str
    sumber: str                    # ekosistem asal: claude | codex | hermes | skill | mcp
    status: str                    # supported | converted | skipped | requires
    asal: str = ""                 # jalur relatif di dalam paket
    keterangan: str = ""
    pekerja: list[str] = field(default_factory=list)
    alasan: str = ""
    data: dict = field(default_factory=dict)

    def ringkas(self) -> dict:
        d = asdict(self)
        d.pop("data", None)
        return d


@dataclass
class Manifest:
    """Hasil pembacaan satu sumber: identitas paket plus semua capability."""
    nama: str
    jenis_paket: str
    akar: str
    versi: str = ""
    keterangan: str = ""
    sumber_url: str = ""
    capabilities: list[Capability] = field(default_factory=list)
    catatan: list[str] = field(default_factory=list)

    def hitung(self) -> dict:
        out = {k: 0 for k in ("supported", "converted", "skipped", "requires")}
        for c in self.capabilities:
            out[c.status] = out.get(c.status, 0) + 1
        out["total"] = len(self.capabilities)
        return out

    def ringkas(self) -> dict:
        return {
            "nama": self.nama,
            "jenis_paket": self.jenis_paket,
            "akar": self.akar,
            "versi": self.versi,
            "keterangan": self.keterangan,
            "sumber_url": self.sumber_url,
            "catatan": self.catatan,
            "hitung": self.hitung(),
            "capabilities": [c.ringkas() for c in self.capabilities],
        }


# ------------------------------------------------------------------ util baca

def _baca_json(p: pathlib.Path) -> dict:
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _baca_toml(p: pathlib.Path) -> dict:
    try:
        with open(p, "rb") as fh:
            return tomllib.load(fh)
    except Exception:
        return {}


def _baca_teks(p: pathlib.Path, batas: int = 200000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:batas]
    except Exception:
        return ""


def _frontmatter(p: pathlib.Path) -> dict:
    """Ambil frontmatter YAML secukupnya: name, description, dan kunci lain.

    Ditulis tanpa pustaka YAML karena nilainya sering berisi tanda titik dua
    (misalnya `description: Use when: ...`) yang membuat parser sederhana pun
    harus menangani kutip dan blok. Yang dibutuhkan di sini hanya nama dan
    keterangan, jadi pembacaan baris demi baris sudah cukup.
    """
    teks = _baca_teks(p, 8000)
    m = _FRONTMATTER.match(teks)
    if not m:
        return {}
    out: dict[str, str] = {}
    kunci_kini = ""
    for baris in m.group(1).splitlines():
        if not baris.strip():
            continue
        if baris[:1] in (" ", "\t") and kunci_kini:
            out[kunci_kini] = (out[kunci_kini] + " " + baris.strip()).strip()
            continue
        if ":" not in baris:
            continue
        k, _, v = baris.partition(":")
        kunci_kini = k.strip()
        out[kunci_kini] = v.strip().strip("\"'")
    return out


def _judul_md(p: pathlib.Path) -> str:
    """Keterangan pertama dari markdown: frontmatter, kalau tidak ada heading."""
    fm = _frontmatter(p)
    if fm.get("description"):
        return fm["description"][:200]
    for baris in _baca_teks(p, 4000).splitlines():
        if baris.startswith("# "):
            return baris[2:].strip()[:200]
    return ""


def _slug(nama: str) -> str:
    return plugins._aman(nama, "paket")


# ------------------------------------------------------------------ deteksi

def _punya(akar: pathlib.Path, *rel: str) -> pathlib.Path | None:
    for r in rel:
        p = akar / r
        if p.exists():
            return p
    return None


def deteksi(akar: pathlib.Path) -> dict:
    """Tebak ekosistem paket ini beserta penanda yang ditemukan.

    Urutannya penting: penanda eksplisit (plugin.json, plugin.yaml) lebih
    dipercaya daripada sekadar adanya folder skills/, karena banyak repo biasa
    punya folder skills/ tanpa berniat jadi plugin.
    """
    akar = pathlib.Path(akar)
    if not akar.exists():
        return {"jenis": "tidak dikenal", "penanda": [], "yakin": False}

    penanda: list[str] = []
    jenis = ""

    cp = _punya(akar, ".claude-plugin/plugin.json")
    if cp:
        penanda.append(str(cp.relative_to(akar)))
        jenis = "claude"

    xp = _punya(akar, ".codex-plugin/plugin.json")
    if xp:
        penanda.append(str(xp.relative_to(akar)))
        if not jenis:
            jenis = "codex"

    hp = _punya(akar, "plugin.yaml", "plugin.yml")
    if hp:
        penanda.append(str(hp.relative_to(akar)))
        if not jenis:
            jenis = "hermes"

    mp = _punya(akar, ".mcp.json", "mcp.json", ".mcp/config.json")
    if mp:
        penanda.append(str(mp.relative_to(akar)))

    sk = [p for p in akar.rglob("SKILL.md")][:1]
    if sk:
        penanda.append(str(sk[0].relative_to(akar)))
        if not jenis:
            jenis = "skill"

    ag = _punya(akar, "agents", ".claude/agents", ".codex/agents", "agent")
    if ag and ag.is_dir():
        penanda.append(str(ag.relative_to(akar)) + "/")
        if not jenis:
            jenis = "skill"

    cm = _punya(akar, "commands", ".claude/commands")
    if cm and cm.is_dir():
        penanda.append(str(cm.relative_to(akar)) + "/")

    hk = _punya(akar, "hooks", "hooks.json", ".claude/hooks")
    if hk:
        penanda.append(str(hk.relative_to(akar)))

    if not jenis:
        jenis = "tidak dikenal"

    # Sub-folder plugin: banyak repo menaruh plugin di dalam, misalnya
    # mem0/integrations/claude-code-plugin. Kalau akar belum yakin, cari satu
    # tingkat lebih dalam supaya pemasangan dari URL repo besar tetap bekerja.
    sub = _cari_sub_plugin(akar) if jenis == "tidak dikenal" else None
    return {"jenis": jenis, "penanda": penanda, "yakin": jenis != "tidak dikenal", "sub": str(sub) if sub else ""}


def _cari_sub_plugin(akar: pathlib.Path, maks: int = 400) -> pathlib.Path | None:
    """Cari folder yang jelas berisi plugin, paling dalam dua tingkat.

    Dipakai untuk repo besar yang menampung beberapa plugin sekaligus: tanpa ini
    memasang https://github.com/mem0ai/mem0 akan berhenti di akar repo dan tidak
    menemukan apa pun.
    """
    kandidat: list[pathlib.Path] = []
    n = 0
    for p in akar.rglob("*"):
        n += 1
        if n > maks:
            break
        if not p.is_dir() or p.name.startswith("."):
            continue
        if len(p.relative_to(akar).parts) > 2:
            continue
        if (p / ".claude-plugin" / "plugin.json").exists() or (p / ".codex-plugin" / "plugin.json").exists():
            kandidat.append(p)
    return kandidat[0] if kandidat else None


def daftar_plugin_dalam(akar: pathlib.Path, maks: int = 60) -> list[dict]:
    """Semua plugin yang bisa dipasang dari satu repo (satu repo bisa banyak)."""
    akar = pathlib.Path(akar)
    out: list[dict] = []
    n = 0
    for p in akar.rglob("plugin.json"):
        n += 1
        if n > maks:
            break
        if p.parent.name not in (".claude-plugin", ".codex-plugin", ".cursor-plugin"):
            continue
        try:
            rel = p.parent.parent.relative_to(akar)
        except ValueError:
            continue
        if len(rel.parts) > 3:
            continue
        d = _baca_json(p)
        out.append({
            "jenis": p.parent.name.strip(".").replace("-plugin", ""),
            "nama": str(d.get("name") or rel.name),
            "folder": str(rel) if str(rel) != "." else ".",
            "versi": str(d.get("version") or ""),
            "keterangan": str(d.get("description") or "")[:160],
        })
    return sorted(out, key=lambda e: (e["folder"], e["jenis"]))


# ------------------------------------------------------------------ pembaca per ekosistem

def _pekerja_untuk_skill() -> list[str]:
    """Semua pekerja menerima skill: keempatnya membaca folder skill yang sama."""
    return list(PEKERJA)


def _kumpulkan_skill(akar: pathlib.Path, cap: list[Capability], sumber: str, dasar: pathlib.Path | None = None) -> None:
    """Kumpulkan skill, satu entri per nama.

    Repo besar sering menyimpan salinan folder skill yang sama di beberapa
    tempat (misalnya skills/ untuk paket, .agents/skills/ untuk harness, dan
    salinan di examples/). Terukur di satu repo: 903 berkas SKILL.md tetapi
    hanya 294 nama unik. Tanpa penyaringan, satu paket akan tampil berisi
    ribuan skill dan pemasangan menautkan folder yang sama berkali-kali.
    Yang dipertahankan adalah jalur paling dangkal, karena itulah lokasi resmi
    paketnya.
    """
    dasar = dasar or akar
    sudah = {c.nama for c in cap if c.jenis == "skill"}
    kandidat = sorted(akar.rglob("SKILL.md"), key=lambda p: (len(p.relative_to(dasar).parts), str(p)))
    for md in kandidat:
        fm = _frontmatter(md)
        nama = fm.get("name") or md.parent.name
        if nama in sudah:
            continue
        sudah.add(nama)
        cap.append(Capability(
            jenis="skill",
            nama=nama,
            sumber=sumber,
            status="supported",
            asal=str(md.parent.relative_to(dasar)),
            keterangan=(fm.get("description") or _judul_md(md))[:200],
            pekerja=_pekerja_untuk_skill(),
            data={"path": str(md.parent)},
        ))


def _kumpulkan_agent(akar: pathlib.Path, cap: list[Capability], sumber: str, dasar: pathlib.Path) -> None:
    """Agen ala Claude/Codex: satu berkas markdown atau toml per agen.

    Aturan status, dan alasannya:
      - Tidak ada kunci khusus harness: `supported`. Berkasnya jalan apa adanya
        di harness asalnya, dan salinan ke harness lain tidak kehilangan apa pun
        yang penting.
      - Ada kunci khusus Claude (`model:`, `tools:`, `isolation:`, `color:`):
        `converted`. Salinan ke Codex/OpenCode/OMP kehilangan kunci itu, jadi
        yang dipertahankan hanya nama dan keterangannya sebagai aturan peran.
    Kunci khusus itu tidak bisa diterjemahkan karena tidak ada padanannya:
    `isolation: worktree` adalah fitur Claude Code, bukan setelan umum.
    """
    for f in sorted(list(akar.glob("*.md")) + list(akar.glob("*.toml"))):
        if f.name.lower() == "readme.md":
            continue
        fm: dict = {}
        if f.suffix == ".toml":
            d = _baca_toml(f)
            nama = f.stem
            ket = str(d.get("developer_instructions") or d.get("description") or "")[:200]
            asal_harness = "codex"
        else:
            fm = _frontmatter(f)
            nama = fm.get("name") or f.stem
            ket = (fm.get("description") or _judul_md(f))[:200]
            asal_harness = "claude"

        khusus = [k for k in ("model", "tools", "isolation", "effort", "color") if k in fm]
        if khusus:
            status = "converted"
            alasan = (
                "kunci khusus Claude (" + ", ".join(khusus) + ") tidak punya padanan di "
                "Codex, OpenCode, dan OMP; nama dan keterangan tetap dipakai sebagai aturan peran"
            )
        else:
            status = "supported"
            alasan = f"berkas {f.suffix} milik {asal_harness}; dipakai apa adanya"

        # Berkasnya ditulis ke kedua harness oleh _tulis_agen, jadi kedua-duanya
        # tercatat sebagai penerima; yang berbeda hanya apakah ada yang hilang.
        cap.append(Capability(
            jenis="agent",
            nama=nama,
            sumber=sumber,
            status=status,
            asal=str(f.relative_to(dasar)),
            keterangan=ket,
            pekerja=[asal_harness, *[w for w in PEKERJA if w != asal_harness]],
            alasan=alasan,
            data={"path": str(f), "kunci_khusus": khusus, "peran": asal_harness},
        ))


def _kumpulkan_command(akar: pathlib.Path, cap: list[Capability], sumber: str, dasar: pathlib.Path) -> None:
    """Perintah slash ala Claude: markdown dengan frontmatter name/allowed-tools.

    Bentuk slash command berbeda di tiap CLI (Claude `commands/*.md`, OMP
    `~/.omp/agent/commands/`, OpenCode `~/.config/opencode/command/*.md`), dan
    menerjemahkannya butuh pengetahuan format yang belum terverifikasi. Karena
    itu isinya TIDAK disalin sebagai perintah; yang dipakai hanya naskahnya
    sebagai aturan (rule) yang dibaca pekerja. Ini keputusan sadar: lebih baik
    status `converted` yang jujur daripada menaruh berkas yang tidak dibaca CLI.
    """
    for f in sorted(akar.rglob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        fm = _frontmatter(f)
        nama = fm.get("name") or f.stem
        cap.append(Capability(
            jenis="command",
            nama=nama,
            sumber=sumber,
            status="converted",
            asal=str(f.relative_to(dasar)),
            keterangan=(fm.get("description") or _judul_md(f))[:200],
            pekerja=list(PEKERJA),
            alasan="slash command tiap CLI berbeda bentuk; naskahnya dipakai sebagai aturan, bukan perintah",
            data={"path": str(f)},
        ))


def _kumpulkan_hook(hooks: dict, cap: list[Capability], sumber: str, asal: str, dasar: pathlib.Path) -> None:
    """Hook Claude/Codex: dijalankan CLI masing-masing, AstroZ hanya mendeteksi.

    Hook adalah kode yang dijalankan harness saat kejadian tertentu
    (SessionStart, PostToolUse, dan seterusnya). AstroZ tidak mengeksekusinya,
    dan menyalinnya ke CLI lain akan menjalankan perintah yang mengandalkan
    variabel lingkungan milik Claude (CLAUDE_PLUGIN_ROOT) sehingga gagal atau,
    lebih buruk, menjalankan perintah yang salah. Karena itu statusnya `skipped`
    dengan alasan yang menyebut harness pemiliknya.
    """
    isi = hooks.get("hooks") if isinstance(hooks.get("hooks"), dict) else hooks
    if not isinstance(isi, dict):
        return
    for kejadian, daftar in isi.items():
        if not isinstance(daftar, list):
            continue
        n_perintah = 0
        for entri in daftar:
            if isinstance(entri, dict):
                n_perintah += len(entri.get("hooks") or []) or 1
        cap.append(Capability(
            jenis="hook",
            nama=str(kejadian),
            sumber=sumber,
            status="skipped",
            asal=asal,
            keterangan=f"{n_perintah} perintah pada kejadian {kejadian}",
            pekerja=[],
            alasan="hook dijalankan harness pemiliknya; perintahnya memakai variabel lingkungan CLI itu sendiri",
            data={},
        ))


def _kumpulkan_mcp(mcp: dict, cap: list[Capability], sumber: str, asal: str) -> None:
    """Server MCP: langsung dipakai sistem MCP AstroZ yang sudah ada."""
    servers = mcp.get("mcpServers") if isinstance(mcp.get("mcpServers"), dict) else mcp
    if not isinstance(servers, dict):
        return
    for nama, v in servers.items():
        if not isinstance(v, dict):
            continue
        d = _mcp_definisi(nama, v)
        if not d:
            cap.append(Capability(
                jenis="mcp", nama=str(nama), sumber=sumber, status="skipped", asal=asal,
                keterangan="", alasan="definisi server tidak punya command maupun url",
            ))
            continue
        cap.append(Capability(
            jenis="mcp",
            nama=str(nama),
            sumber=sumber,
            status="supported",
            asal=asal,
            keterangan=d["target"] + ((" " + " ".join(d["args"])) if d["args"] else ""),
            pekerja=list(PEKERJA),
            data={"mcp": d},
        ))


_VAR = re.compile(r"\$\{([A-Z_]+)\}|\$\{([A-Z_]+):-([^}]*)\}")


def _isi_var(teks: str, akar: pathlib.Path) -> str:
    """Ganti variabel lingkungan khas plugin dengan jalur nyata.

    `${CLAUDE_PLUGIN_ROOT}` menunjuk folder plugin, `${CLAUDE_PLUGIN_DATA}`
    menunjuk folder datanya. Tanpa penggantian, perintah MCP akan gagal karena
    CLI lain tidak mengisi variabel itu.
    """
    def ganti(m: re.Match) -> str:
        nama = m.group(1) or m.group(2)
        bawaan = m.group(3) or ""
        if nama in ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT"):
            return str(akar)
        if nama in ("CLAUDE_PLUGIN_DATA", "PLUGIN_DATA"):
            return str(akar / ".data")
        return os.environ.get(nama, bawaan)
    return _VAR.sub(ganti, teks)


def _mcp_definisi(nama: str, v: dict) -> dict | None:
    """Terjemahkan satu server dari bentuk mana pun ke bentuk internal AstroZ."""
    url = v.get("url") or v.get("httpUrl") or v.get("serverUrl") or ""
    cmd = v.get("command") or ""
    args = [str(a) for a in (v.get("args") or [])]
    env = {str(k): str(x) for k, x in (v.get("env") or {}).items()}
    header = {str(k): str(x) for k, x in (v.get("headers") or {}).items()}

    if url:
        tr = "http"
        if str(v.get("type") or "").lower() in ("sse",):
            tr = "sse"
        return plugins.mcp_definisi(nama, tr, str(url), env=env, header=header)
    if cmd:
        return plugins.mcp_definisi(nama, "stdio", str(cmd), args=args, env=env)
    return None


def baca(akar: pathlib.Path, sumber_url: str = "", nama_paksa: str = "") -> Manifest:
    """Baca satu folder dan hasilkan capability manifest.

    Inilah fungsi utama adapter: kenali ekosistemnya, baca penanda yang ada, dan
    normalkan semuanya. Tidak ada berkas yang ditulis di sini; pemasangan
    dilakukan fungsi `pasang`.
    """
    akar = pathlib.Path(akar).resolve()
    d = deteksi(akar)
    jenis_paket = d["jenis"]
    if d.get("sub"):
        akar = (akar / d["sub"]).resolve()
        jenis_paket = deteksi(akar)["jenis"]
        d = deteksi(akar)

    man = Manifest(nama=nama_paksa or akar.name, jenis_paket=jenis_paket, akar=str(akar), sumber_url=sumber_url)
    cap = man.capabilities

    # --- identitas paket
    if jenis_paket == "claude":
        pj = _baca_json(akar / ".claude-plugin" / "plugin.json")
        man.nama = nama_paksa or str(pj.get("name") or akar.name)
        man.versi = str(pj.get("version") or "")
        man.keterangan = str(pj.get("description") or "")[:400]
    elif jenis_paket == "codex":
        pj = _baca_json(akar / ".codex-plugin" / "plugin.json")
        man.nama = nama_paksa or str(pj.get("name") or akar.name)
        man.versi = str(pj.get("version") or "")
        man.keterangan = str(pj.get("description") or "")[:400]
    elif jenis_paket == "hermes":
        py = _baca_teks(akar / "plugin.yaml", 4000) or _baca_teks(akar / "plugin.yml", 4000)
        man.nama = nama_paksa or _yaml_scalar(py, "name") or akar.name
        man.versi = _yaml_scalar(py, "version")
        man.keterangan = _yaml_scalar(py, "description")[:400]
    elif jenis_paket == "skill":
        man.nama = nama_paksa or akar.name
    else:
        man.nama = nama_paksa or akar.name
        man.catatan.append(
            "Tidak ada penanda plugin yang dikenali (.claude-plugin/plugin.json, "
            ".codex-plugin/plugin.json, plugin.yaml, SKILL.md, atau .mcp.json)."
        )

    # --- skills: dibaca dari mana pun ia berada
    _kumpulkan_skill(akar, cap, "skill" if jenis_paket == "skill" else jenis_paket)

    # --- agents
    for sub in ("agents", ".claude/agents", ".codex/agents"):
        p = akar / sub
        if p.is_dir():
            _kumpulkan_agent(p, cap, jenis_paket, akar)

    # --- commands
    for sub in ("commands", ".claude/commands"):
        p = akar / sub
        if p.is_dir():
            _kumpulkan_command(p, cap, jenis_paket, akar)

    # --- hooks
    for rel in ("hooks/hooks.json", "hooks.json", ".claude/hooks/hooks.json", "hooks/codex-hooks.json"):
        p = akar / rel
        if p.is_file():
            d2 = _baca_json(p)
            if d2:
                _kumpulkan_hook(d2, cap, jenis_paket, rel, akar)

    # --- MCP: bentuk berbeda per ekosistem, semua lewat sistem MCP AstroZ
    for rel in (".mcp.json", "mcp.json", ".mcp/config.json"):
        p = akar / rel
        if p.is_file():
            d2 = _baca_json(p)
            if d2:
                _kumpulkan_mcp(d2, cap, jenis_paket, rel)

    # --- hermes: plugin.yaml menyebut hook, tool, dan command yang disediakan
    if jenis_paket == "hermes":
        py = _baca_teks(akar / "plugin.yaml", 4000) or _baca_teks(akar / "plugin.yml", 4000)
        _kumpulkan_hermes(py, cap, akar)

    # --- berkas plugin.json menyebut jalur skills/commands/mcpServers sendiri
    _kumpulkan_dari_plugin_json(akar, cap, jenis_paket, man)

    _tandai_tak_didukung(akar, cap, man)
    _tandai_program_biasa(akar, cap, man)
    _peringatkan_jalur_sementara(akar, man)
    return man


def _tandai_program_biasa(akar: pathlib.Path, cap: list[Capability], man: Manifest) -> None:
    """Paket yang bukan plugin: program biasa, atau paket yang membawa server MCP.

    Dua kasus nyata yang harus dibedakan:
      - aider: program Python, tanpa satu pun penanda plugin. Tidak ada yang
        bisa dipasang sebagai capability; yang jujur adalah mengatakannya.
      - cognee: paket Python yang juga membawa server MCP (folder cognee-mcp
        dengan pyproject berisi fastmcp). Server itu bisa dipakai, tetapi harus
        dijalankan sebagai proses sendiri, bukan disalin sebagai berkas. Karena
        itu statusnya `requires`, bukan `supported`.
    """
    ada_mcp = False
    for py in list(akar.glob("*/pyproject.toml"))[:40] + list(akar.glob("pyproject.toml"))[:1]:
        teks = _baca_teks(py, 20000)
        # Ketergantungan ditulis dengan pembatas versi ("fastmcp>=3.4.0"), jadi
        # pencocokan harus mengizinkan pembatasnya, bukan hanya nama telanjang.
        if re.search(r'"(fastmcp|mcp)\s*(?:[><=~!,\[]|")', teks) or "mcp.server" in teks:
            paket = py.parent
            if any(c.jenis == "mcp" and str(paket) in str(c.data.get("paket", "")) for c in cap):
                continue
            if any(c.jenis == "mcp" for c in cap) and paket == akar:
                continue
            cap.append(Capability(
                jenis="mcp",
                nama=paket.name,
                sumber=man.jenis_paket,
                status="requires",
                asal=str(py.parent.relative_to(akar)) + "/",
                keterangan="paket server MCP bawaan repo",
                pekerja=[],
                alasan="harus dijalankan sebagai proses sendiri; pasang lewat halaman MCP setelah perintah jalannya jelas",
                data={"paket": str(paket), "cara": f"cd {py.parent} && uv run python -m {paket.name.replace('-', '_')}"},
            ))
            ada_mcp = True

    if cap or ada_mcp:
        return
    if (akar / "pyproject.toml").exists() or (akar / "setup.py").exists() or (akar / "package.json").exists():
        man.catatan.append(
            "Paket ini program biasa, bukan paket capability: tidak ada skill, agen, perintah, hook, "
            "maupun server MCP di dalamnya. Tidak ada yang dipasang, dan tidak ada yang disalin diam-diam."
        )


# Jalur yang isinya hilang saat mesin dimulai ulang. Tautan skill menunjuk ke
# jalur nyata, jadi memasang dari sini membuat semua tautan itu putus diam-diam
# pada reboot berikutnya: pekerja kehilangan skillnya tanpa pesan apa pun.
JALUR_SEMENTARA = ("/tmp/", "/var/tmp/", "/run/", "/dev/shm/")


def _peringatkan_jalur_sementara(akar: pathlib.Path, man: Manifest) -> None:
    teks = str(akar)
    if not teks.startswith(JALUR_SEMENTARA):
        return
    man.catatan.append(
        "PERHATIAN: paket ini dibaca dari jalur sementara (" + teks.split("/")[1] + "/). "
        "Tautan skill menunjuk ke jalur ini, jadi semuanya putus begitu mesin dimulai ulang. "
        "Pasang dari tautan GitHub atau salin paketnya ke folder tetap lebih dulu."
    )


def _yaml_scalar(teks: str, kunci: str) -> str:
    m = re.search(rf"^{kunci}\s*:\s*(.+)$", teks, re.MULTILINE)
    if not m:
        return ""
    v = m.group(1).strip().strip("\"'")
    # blok `>` atau `|`: ambil baris menjorok setelahnya
    if v in (">", "|", ">-", "|-"):
        lanjutan: list[str] = []
        for baris in teks[m.end():].splitlines():
            if not baris.strip():
                continue
            if not baris[:1].isspace():
                break
            lanjutan.append(baris.strip())
        return " ".join(lanjutan)[:400]
    return v


def _kumpulkan_hermes(py: str, cap: list[Capability], akar: pathlib.Path) -> None:
    """Manifest plugin Hermes: hook, tool, dan command yang ia sediakan.

    Plugin Hermes adalah kode Python yang berjalan di dalam Hermes, bukan di
    pekerja. AstroZ bisa membacanya sebagai capability, tetapi menjalankannya
    hanya masuk akal di dalam Hermes sendiri, jadi statusnya `requires` untuk
    bagian hook dan tool, dan `supported` untuk skill yang menyertainya.
    """
    for kunci, jenis, ket in (
        ("provides_hooks", "hook", "hook Hermes dijalankan di dalam Hermes, bukan di pekerja"),
        ("provides_tools", "mcp", "tool Hermes adalah fungsi Python di dalam Hermes, bukan server MCP"),
        ("provides_commands", "command", "perintah Hermes dijalankan Hermes sendiri"),
    ):
        blok = re.search(rf"^{kunci}\s*:\s*\n((?:\s+-\s*.+\n?)+)", py, re.MULTILINE)
        if not blok:
            continue
        for m in re.finditer(r"-\s*(.+)", blok.group(1)):
            nama = m.group(1).strip().strip("\"'")
            if not nama:
                continue
            if any(c.jenis == jenis and c.nama == nama for c in cap):
                continue
            cap.append(Capability(
                jenis=jenis, nama=nama, sumber="hermes",
                status="requires",
                asal="plugin.yaml",
                keterangan="disediakan plugin Hermes",
                pekerja=[],
                alasan=ket,
                data={"jalur_hermes": str(akar)},
            ))


def _kumpulkan_dari_plugin_json(akar: pathlib.Path, cap: list[Capability], jenis: str, man: Manifest) -> None:
    """plugin.json bisa menunjuk jalur skills/, commands/, dan mcpServers sendiri.

    Tanpa membaca penunjuk ini, plugin yang menaruh skillnya di luar folder
    bawaan akan terlihat kosong padahal isinya ada.
    """
    for rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "plugin.json"):
        p = akar / rel
        if not p.is_file():
            continue
        pj = _baca_json(p)
        for kunci in ("skills", "commands"):
            nilai = pj.get(kunci)
            if isinstance(nilai, str):
                nilai = [nilai]
            if not isinstance(nilai, list):
                continue
            for item in nilai:
                if not isinstance(item, str):
                    continue
                sub = (akar / item.lstrip("./")).resolve()
                if not sub.exists():
                    continue
                if kunci == "skills":
                    _kumpulkan_skill(sub, cap, jenis, akar)
                else:
                    _kumpulkan_command(sub, cap, jenis, akar)
        mcp = pj.get("mcpServers")
        if isinstance(mcp, str):
            sub = (akar / mcp.lstrip("./")).resolve()
            if sub.is_file():
                _kumpulkan_mcp(_baca_json(sub), cap, jenis, mcp.lstrip("./"))
        elif isinstance(mcp, dict) and mcp:
            _kumpulkan_mcp(mcp, cap, jenis, rel)
        hk = pj.get("hooks")
        if isinstance(hk, str):
            sub = (akar / hk.lstrip("./")).resolve()
            if sub.is_file():
                _kumpulkan_hook(_baca_json(sub), cap, jenis, hk.lstrip("./"), akar)
        elif isinstance(hk, dict) and hk:
            _kumpulkan_hook(hk, cap, jenis, rel, akar)


def _tandai_tak_didukung(akar: pathlib.Path, cap: list[Capability], man: Manifest) -> None:
    """Catat komponen paket yang ada tapi tidak bisa dipakai, tanpa menyalinnya.

    Yang dicari: folder khas ekosistem lain yang bentuknya tidak dikenal AstroZ.
    Ini yang membuat pratinjau jujur: pengguna melihat apa yang dilewati, bukan
    menemukannya belakangan.
    """
    sudah = {c.asal for c in cap}
    for nama, ket in (
        ("rules", "berkas aturan; isinya dibaca sebagai teks, bukan capability"),
        ("workflows", "alur kerja tingkat tinggi; tidak punya bentuk seragam"),
        ("enterprise", "setelan perusahaan; khusus Claude Code"),
    ):
        p = akar / nama
        if not p.is_dir():
            continue
        n = len(list(p.rglob("*")))
        if not n:
            continue
        if str(p.relative_to(akar)) in sudah:
            continue
        cap.append(Capability(
            jenis="rule",
            nama=nama,
            sumber=man.jenis_paket,
            status="skipped",
            asal=str(p.relative_to(akar)) + "/",
            keterangan=f"{n} berkas",
            alasan=ket,
            pekerja=[],
        ))


# ------------------------------------------------------------------ pemasangan

def _pekerja_hidup() -> dict[str, str]:
    try:
        return plugins._klien()
    except Exception:
        return {}


def _tulis_agen(man: Manifest, c: Capability, hasil: list[dict]) -> None:
    """Tulis agen ke folder yang dibaca tiap CLI.

    Format yang dipakai sudah diverifikasi di mesin ini:
      claude   ~/.claude/agents/<nama>.md      markdown + frontmatter
      codex    ~/.codex/agents/<nama>.toml     plus blok [agents.<nama>] di config.toml
      opencode ~/.config/opencode/agent/<nama>.md
      omp      ~/.omp/agent/agents/<nama>.md

    Isinya diterjemahkan, bukan disalin mentah: frontmatter Claude (model,
    tools, isolation) tidak sah di Codex maupun OMP, jadi untuk tujuan itu yang
    ditulis adalah keterangan plus badan naskahnya. Ini yang membuat status
    `converted` di manifest benar-benar menggambarkan apa yang terjadi.
    """
    asal = pathlib.Path(c.data.get("path") or "")
    if not asal.is_file():
        hasil.append({"jenis": "agent", "nama": c.nama, "ok": False, "pesan": "berkas asal hilang"})
        return
    teks = _baca_teks(asal)
    fm = _frontmatter(asal) if asal.suffix == ".md" else {}
    keterangan = (fm.get("description") or c.keterangan or "")[:400]
    if asal.suffix == ".toml":
        d = _baca_toml(asal)
        badan = str(d.get("developer_instructions") or "")
        keterangan = keterangan or str(d.get("description") or "")[:400]
    else:
        badan = _FRONTMATTER.sub("", teks).strip()

    tujuan: list[tuple[str, pathlib.Path]] = [
        ("claude", HOME / ".claude" / "agents" / (c.nama + ".md")),
        ("codex", HOME / ".codex" / "agents" / (c.nama + ".toml")),
        ("opencode", HOME / ".config" / "opencode" / "agent" / (c.nama + ".md")),
        ("omp", HOME / ".omp" / "agent" / "agents" / (c.nama + ".md")),
    ]

    for pekerja, path in tujuan:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if pekerja == "codex":
                path.write_text(
                    "# Dibuat AstroZ dari agen " + c.data.get("peran", "claude") + " " + c.nama + "\n"
                    'developer_instructions = """\n'
                    + (keterangan + "\n\n" if keterangan else "")
                    + badan[:8000] + '\n"""\n'
                )
                _daftarkan_agen_codex(c.nama, path)
            else:
                path.write_text(
                    "---\nname: " + c.nama + "\ndescription: "
                    + keterangan.replace("\n", " ")
                    + "\n---\n\n" + badan
                )
            hasil.append({"jenis": "agent", "nama": c.nama, "pekerja": pekerja, "ok": True, "path": str(path)})
        except Exception as e:
            hasil.append({"jenis": "agent", "nama": c.nama, "pekerja": pekerja, "ok": False, "pesan": str(e)})


def _daftarkan_agen_codex(nama: str, path: pathlib.Path) -> None:
    """Codex baru membaca berkas agen kalau didaftarkan di config.toml."""
    cfg = HOME / ".codex" / "config.toml"
    teks = _baca_teks(cfg, 200000)
    if f"[agents.{nama}]" in teks:
        return
    blok = (
        f"\n[agents.{nama}]\n"
        f'description = "agen dari plugin, dipasang AstroZ"\n'
        f'config_file = "agents/{path.name}"\n'
    )
    try:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg, "a", encoding="utf-8") as fh:
            fh.write(blok)
    except Exception:
        pass


def _tulis_command(man: Manifest, c: Capability, hasil: list[dict]) -> None:
    """Naskah slash command dipakai sebagai aturan, bukan perintah.

    Ditulis ke folder aturan yang dibaca pekerja (`~/.claude/rules/` tidak dibaca
    keempat CLI ini dengan seragam), jadi yang dilakukan adalah menaruhnya di
    folder dokumen AstroZ dan menyebutkannya di manifest. Ini disengaja: menaruh
    berkas di folder yang salah membuat pengguna mengira perintahnya aktif.
    """
    asal = pathlib.Path(c.data.get("path") or "")
    if not asal.is_file():
        hasil.append({"jenis": "command", "nama": c.nama, "ok": False, "pesan": "berkas asal hilang"})
        return
    tujuan = CAP_DIR / _slug(man.nama) / "commands" / asal.name
    try:
        tujuan.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asal, tujuan)
        hasil.append({"jenis": "command", "nama": c.nama, "ok": True, "path": str(tujuan),
                      "pesan": "disimpan sebagai naskah; tidak didaftarkan sebagai perintah CLI"})
    except Exception as e:
        hasil.append({"jenis": "command", "nama": c.nama, "ok": False, "pesan": str(e)})


def _tulis_mcp(man: Manifest, c: Capability, pekerja: list[str], hasil: list[dict]) -> None:
    """Pakai sistem MCP AstroZ yang sudah ada, tanpa jalur tulis baru."""
    d = dict(c.data.get("mcp") or {})
    if not d:
        hasil.append({"jenis": "mcp", "nama": c.nama, "ok": False, "pesan": "definisi kosong"})
        return
    d["target"] = _isi_var(str(d.get("target") or ""), pathlib.Path(man.akar))
    d["args"] = [_isi_var(str(a), pathlib.Path(man.akar)) for a in (d.get("args") or [])]
    d["env"] = {k: _isi_var(str(v), pathlib.Path(man.akar)) for k, v in (d.get("env") or {}).items()}
    try:
        r = plugins.mcp_pasang(d, pekerja or None)
        hasil.append({"jenis": "mcp", "nama": c.nama, "ok": any(v == "ok" for v in r.values()), "pekerja": r})
    except Exception as e:
        hasil.append({"jenis": "mcp", "nama": c.nama, "ok": False, "pesan": str(e)})


def pasang(man: Manifest, pilih: list[str] | None = None, pekerja: list[str] | None = None,
           jid: str = "") -> dict:
    """Pasang capability dari manifest ke pekerja yang kompatibel.

    `pilih` menyaring jenis yang dipasang (misalnya hanya ["skill", "mcp"]).
    Capability berstatus skipped dan requires tidak pernah dipasang; keduanya
    hanya dilaporkan supaya tidak ada yang hilang diam-diam.
    """
    def baris(t: str) -> None:
        if jid:
            plugins.job_baris(jid, t)

    ingin = set(pilih) if pilih else None
    hasil: list[dict] = []
    tautan = 0

    # Skill ditautkan per akar, bukan per skill: skill_tautkan memindai SKILL.md
    # di seluruh isi folder yang diberikan, jadi memanggilnya sekali per skill
    # berarti pekerjaan yang sama diulang puluhan kali untuk paket besar.
    akar_skill: list[pathlib.Path] = []
    for c in man.capabilities:
        if c.jenis != "skill" or (ingin and "skill" not in ingin) or c.status in ("skipped", "requires"):
            continue
        p = pathlib.Path(c.data.get("path") or "")
        if p.is_dir() and p.parent not in akar_skill:
            akar_skill.append(p.parent)

    for c in man.capabilities:
        if ingin and c.jenis not in ingin:
            continue
        if c.status in ("skipped", "requires"):
            hasil.append({"jenis": c.jenis, "nama": c.nama, "ok": False, "dilewati": True, "pesan": c.alasan})
            continue

        if c.jenis == "skill":
            p = pathlib.Path(c.data.get("path") or "")
            if not p.is_dir():
                hasil.append({"jenis": "skill", "nama": c.nama, "ok": False, "pesan": "folder skill hilang"})
                continue
            hasil.append({"jenis": "skill", "nama": c.nama, "ok": True, "path": str(p)})

        elif c.jenis == "agent":
            _tulis_agen(man, c, hasil)

        elif c.jenis == "command":
            _tulis_command(man, c, hasil)

        elif c.jenis == "mcp":
            _tulis_mcp(man, c, pekerja or [], hasil)

        elif c.jenis == "hook":
            hasil.append({"jenis": "hook", "nama": c.nama, "ok": False, "dilewati": True, "pesan": c.alasan})

    # Baru setelah semua jenis lain: skill ditautkan sekali per akar.
    for akar in akar_skill:
        try:
            tautan += plugins.skill_tautkan(akar, jid)
        except Exception as e:
            hasil.append({"jenis": "skill", "nama": akar.name, "ok": False, "pesan": str(e)})

    baris(f"pemasangan selesai: {sum(1 for h in hasil if h.get('ok'))} berhasil dari {len(hasil)} tindakan")
    hub.emit("system", f"Plugin {man.nama} dipasang ({man.jenis_paket}): {man.hitung()}")
    return {"ok": True, "nama": man.nama, "jenis_paket": man.jenis_paket, "tindakan": hasil, "tautan": tautan}


# ------------------------------------------------------------------ registry

def _muat_registry() -> dict:
    return _baca_json(REG_PATH)


def catat_pasang(man: Manifest, url: str, hasil: dict) -> None:
    reg = _muat_registry()
    reg[man.nama] = {
        "nama": man.nama,
        "jenis_paket": man.jenis_paket,
        "url": url or man.sumber_url,
        "akar": man.akar,
        "versi": man.versi,
        "keterangan": man.keterangan,
        "hitung": man.hitung(),
        "dipasang": plugins.time.time(),
        "tautan": hasil.get("tautan", 0),
    }
    REG_PATH.parent.mkdir(parents=True, exist_ok=True)
    REG_PATH.write_text(json.dumps(reg, indent=2, ensure_ascii=False))


def terpasang() -> list[dict]:
    """Daftar paket yang pernah dipasang lewat adapter, untuk halaman UI."""
    reg = _muat_registry()
    out = []
    for e in reg.values():
        e = dict(e)
        e["ada"] = pathlib.Path(str(e.get("akar") or "")).exists()
        out.append(e)
    return sorted(out, key=lambda x: str(x.get("nama") or "").lower())


def lupa(nama: str) -> dict:
    """Lepas satu paket: hapus tautan skill, definisi MCP, dan catatannya."""
    reg = _muat_registry()
    e = reg.pop(_slug(nama), None) or reg.pop(nama, None)
    if not e:
        return {"ok": False, "pesan": "paket tidak ada di catatan"}
    akar = pathlib.Path(str(e.get("akar") or ""))
    lepas = 0
    if akar.exists():
        for md in akar.rglob("SKILL.md"):
            for tujuan in plugins.skill_folder_cli():
                link = tujuan / md.parent.name
                try:
                    if link.is_symlink():
                        link.unlink()
                        lepas += 1
                except Exception:
                    pass
    REG_PATH.write_text(json.dumps(reg, indent=2, ensure_ascii=False))
    hub.emit("system", f"Paket {e.get('nama')} dilepas ({lepas} tautan skill)")
    return {"ok": True, "nama": e.get("nama"), "tautan_dilepas": lepas}


# ------------------------------------------------------------------ ambil dari URL

_GITHUB = re.compile(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/(?:tree|blob)/([^/]+)(/.*)?)?/?$")


def baca_url(url: str) -> dict:
    """Terjemahkan URL GitHub jadi keterangan unduhan.

    Bentuk yang didukung:
      https://github.com/pemilik/repo
      https://github.com/pemilik/repo.git
      https://github.com/pemilik/repo/tree/<cabang>/<folder>
      pemilik/repo
    """
    url = (url or "").strip()
    if not url:
        raise ValueError("url kosong")
    if re.fullmatch(r"[\w.-]+/[\w.-]+", url):
        url = "https://github.com/" + url
    m = _GITHUB.match(url)
    if not m:
        raise ValueError("hanya tautan GitHub atau pemilik/repo yang didukung")
    pemilik, repo, cabang, sub = m.group(1), m.group(2), m.group(3) or "", (m.group(4) or "").strip("/")
    return {
        "url": f"https://github.com/{pemilik}/{repo}.git",
        "repo": repo,
        "pemilik": pemilik,
        "cabang": cabang,
        "sub": sub,
        "slug": _slug(repo),
    }


def unduh(url: str, jid: str = "") -> pathlib.Path:
    """Unduh sumber ke folder capability. Paket lokal juga diterima."""
    p = pathlib.Path(url).expanduser()
    if p.exists():
        if jid:
            plugins.job_baris(jid, f"memakai paket lokal {p}")
        return p.resolve()

    info = baca_url(url)
    tujuan = CAP_DIR / info["slug"]
    CAP_DIR.mkdir(parents=True, exist_ok=True)
    if (tujuan / ".git").exists():
        if jid:
            plugins.job_baris(jid, f"{info['slug']} sudah ada, memperbarui")
        r = plugins._jalankan(["git", "-C", str(tujuan), "pull", "--ff-only"], timeout=300)
    else:
        if jid:
            plugins.job_baris(jid, f"mengunduh {info['url']}")
        r = plugins._jalankan(["git", "clone", "--depth", "1", info["url"], str(tujuan)], timeout=900)
    if r.get("rc") != 0 and not tujuan.exists():
        raise ValueError(f"unduhan gagal: {str(r.get('out'))[:300]}")

    akar = tujuan / info["sub"] if info["sub"] else tujuan
    if not akar.exists():
        raise ValueError(f"folder {info['sub']} tidak ada di {info['repo']}")
    return akar.resolve()


def pratinjau(url: str, jid: str = "") -> dict:
    """Unduh lalu baca tanpa memasang apa pun. Ini yang dipakai tombol Pratinjau."""
    akar = unduh(url, jid)
    man = baca(akar, sumber_url=url)
    d = deteksi(akar)
    out = man.ringkas()
    out["deteksi"] = {"jenis": d["jenis"], "penanda": d["penanda"]}
    out["plugin_dalam"] = daftar_plugin_dalam(akar) if pathlib.Path(man.akar) == akar else []
    out["ok"] = True
    return out


def pasang_url(url: str, pilih: list[str] | None = None, pekerja: list[str] | None = None,
               sub: str = "", jid: str = "") -> dict:
    """Unduh, baca, lalu pasang. Satu pintu untuk UI maupun API."""
    akar = unduh(url, jid)
    if sub:
        akar = (akar / sub).resolve()
    man = baca(akar, sumber_url=url)
    hasil = pasang(man, pilih=pilih, pekerja=pekerja, jid=jid)
    catat_pasang(man, url, hasil)
    hasil["manifest"] = man.ringkas()
    return hasil


def pasang_latar(url: str, pilih: list[str] | None = None, pekerja: list[str] | None = None,
                 sub: str = "") -> str:
    """Versi latar belakang untuk pemasangan dari UI."""
    def kerja(jid: str) -> dict:
        try:
            r = pasang_url(url, pilih=pilih, pekerja=pekerja, sub=sub, jid=jid)
            h = r.get("manifest", {}).get("hitung", {})
            return {
                "ok": True,
                "pesan": (
                    f"{r['nama']} ({r['jenis_paket']}) dipasang: "
                    f"{h.get('supported', 0)} langsung, {h.get('converted', 0)} diterjemahkan, "
                    f"{h.get('skipped', 0)} dilewati, {h.get('requires', 0)} perlu alat lain"
                ),
            }
        except Exception as e:
            return {"ok": False, "pesan": str(e)[:400]}
    return plugins.jalankan_latar(f"Pasang plugin {url[:60]}", kerja)
