"""Tes adapter plugin universal.

Lima kasus yang diuji, sesuai yang diminta:
  1. plugin Claude Code
  2. skill/plugin Codex
  3. skill/plugin Hermes
  4. server MCP
  5. plugin yang sebagian komponennya tidak kompatibel

Semua fixture dibuat di tmp_path, jadi tes ini tidak menyentuh jaringan dan
tidak menyentuh konfigurasi CLI yang sebenarnya. Folder rumah dialihkan ke
tmp_path supaya pemasangan tidak menulis ke ~/.claude atau ~/.codex milik mesin.
"""
from __future__ import annotations

import json
import pathlib

import pytest

import adapters_plugin as ap

# ------------------------------------------------------------------ fixture

@pytest.fixture
def rumah(tmp_path, monkeypatch):
    """Alihkan folder rumah supaya pemasangan tidak menyentuh konfigurasi nyata."""
    h = tmp_path / "home"
    (h / ".claude" / "agents").mkdir(parents=True)
    (h / ".codex").mkdir(parents=True)
    (h / ".config" / "opencode").mkdir(parents=True)
    (h / ".omp" / "agent").mkdir(parents=True)
    monkeypatch.setattr(ap, "HOME", h)
    monkeypatch.setattr(ap, "DATA", h / ".astroz")
    monkeypatch.setattr(ap, "CAP_DIR", h / ".astroz" / "capabilities")
    monkeypatch.setattr(ap, "REG_PATH", h / ".astroz" / "capabilities.json")
    return h


@pytest.fixture
def skill_claude(tmp_path):
    """Plugin Claude lengkap: plugin.json, skills/, agents/, commands/, hooks/, .mcp.json."""
    d = tmp_path / "plugin-claude"
    (d / ".claude-plugin").mkdir(parents=True)
    (d / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "memcontoh",
        "version": "1.2.3",
        "description": "Plugin contoh untuk tes.",
        "skills": ["./skills/"],
        "commands": ["./commands/"],
    }))
    (d / "skills" / "ingat").mkdir(parents=True)
    (d / "skills" / "ingat" / "SKILL.md").write_text(
        "---\nname: ingat\ndescription: Simpan sesuatu untuk sesi berikutnya.\n---\n\n# Ingat\n\nIsi.\n"
    )
    (d / "agents").mkdir()
    (d / "agents" / "penolong.md").write_text(
        "---\nname: penolong\ndescription: Agen penolong untuk meneliti.\n"
        "model: sonnet\ntools: Read, Grep, Bash\nisolation: worktree\n---\n\nKamu agen penolong.\n"
    )
    (d / "commands").mkdir()
    (d / "commands" / "rangkum.md").write_text(
        "---\nname: rangkum\ndescription: Rangkum perubahan terakhir.\n---\n\n# /rangkum\n\nLangkah.\n"
    )
    (d / "hooks").mkdir()
    (d / "hooks" / "hooks.json").write_text(json.dumps({
        "hooks": {
            "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "python3 hook.py"}]}],
            "PostToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "command": "python3 hook.py"}]}],
        }
    }))
    (d / ".mcp.json").write_text(json.dumps({
        "mcpServers": {
            "memcontoh": {
                "command": "python3",
                "args": ["${CLAUDE_PLUGIN_ROOT}/core/mcp_server.py"],
                "env": {"MEMCONTOH_DATA": "${CLAUDE_PLUGIN_DATA}"},
            }
        }
    }))
    return d


@pytest.fixture
def plugin_codex(tmp_path):
    d = tmp_path / "plugin-codex"
    (d / ".codex-plugin").mkdir(parents=True)
    (d / ".codex-plugin" / "plugin.json").write_text(json.dumps({
        "name": "codexcontoh",
        "version": "0.4.0",
        "description": "Plugin contoh Codex.",
        "skills": "./skills/",
        "mcpServers": "./.mcp.json",
    }))
    (d / "skills" / "tdd").mkdir(parents=True)
    (d / "skills" / "tdd" / "SKILL.md").write_text(
        "---\nname: tdd\ndescription: Tulis tes sebelum kode.\n---\n\n# TDD\n"
    )
    (d / ".mcp.json").write_text(json.dumps({
        "mcpServers": {
            "codexmcp": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@contoh/server"],
                "env_vars": ["KUNCI"],
            }
        }
    }))
    return d


@pytest.fixture
def plugin_hermes(tmp_path):
    d = tmp_path / "plugin-hermes"
    d.mkdir()
    (d / "plugin.yaml").write_text(
        "name: hermescontoh\n"
        "version: 2.0.0\n"
        "manifest_version: 2\n"
        "description: >\n"
        "  Plugin contoh Hermes.\n"
        "provides_hooks:\n"
        "  - on_session_start\n"
        "  - pre_tool_call\n"
        "provides_tools:\n"
        "  - alat_contoh\n"
        "provides_commands:\n"
        "  - contoh\n"
    )
    return d


@pytest.fixture
def skill_hermes(tmp_path):
    """Paket skill standar Agent Skills: folder berisi SKILL.md, tanpa plugin.json."""
    d = tmp_path / "paket-skill"
    for nama, ket in (("cognee-cli", "Pakai CLI cognee."), ("cognee-docker", "Jalankan cognee di Docker.")):
        (d / "skills" / nama).mkdir(parents=True)
        (d / "skills" / nama / "SKILL.md").write_text(
            f"---\nname: {nama}\ndescription: {ket}\n---\n\n# {nama}\n"
        )
    return d


@pytest.fixture
def plugin_sebagian(tmp_path):
    """Plugin yang sebagian isinya tidak kompatibel.

    Berisi: satu skill yang bisa dipakai, satu agen dengan kunci khusus Claude,
    satu perintah slash, satu hook, satu server MCP tanpa command/url, dan satu
    folder `enterprise/` yang khusus Claude Code.
    """
    d = tmp_path / "plugin-campuran"
    (d / ".claude-plugin").mkdir(parents=True)
    (d / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "campuran", "version": "1.0.0", "description": "Campuran."
    }))
    (d / "skills" / "berguna").mkdir(parents=True)
    (d / "skills" / "berguna" / "SKILL.md").write_text(
        "---\nname: berguna\ndescription: Skill yang bisa dipakai.\n---\n\n# Berguna\n"
    )
    (d / "agents").mkdir()
    (d / "agents" / "khusus.md").write_text(
        "---\nname: khusus\ndescription: Agen dengan kunci khusus Claude.\n"
        "model: opus\nisolation: worktree\ncolor: cyan\n---\n\nBadan.\n"
    )
    (d / "commands").mkdir()
    (d / "commands" / "kerja.md").write_text("---\nname: kerja\ndescription: Perintah kerja.\n---\n\n# kerja\n")
    (d / "hooks").mkdir()
    (d / "hooks" / "hooks.json").write_text(json.dumps(
        {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 x.py"}]}]}}
    ))
    (d / ".mcp.json").write_text(json.dumps({
        "mcpServers": {
            "rusak": {"keterangan": "tanpa command dan tanpa url"},
            "sehat": {"url": "https://contoh.invalid/mcp"},
        }
    }))
    (d / "enterprise").mkdir()
    (d / "enterprise" / "setelan.json").write_text("{}")
    return d


# ------------------------------------------------------------------ 1. Claude

def test_claude_plugin_dikenali(skill_claude):
    d = ap.deteksi(skill_claude)
    assert d["jenis"] == "claude"
    assert ".claude-plugin/plugin.json" in d["penanda"]
    assert ".mcp.json" in d["penanda"]


def test_claude_plugin_identitas(skill_claude):
    m = ap.baca(skill_claude)
    assert m.nama == "memcontoh"
    assert m.versi == "1.2.3"
    assert m.jenis_paket == "claude"


def test_claude_plugin_skill_dipakai_semua_pekerja(skill_claude):
    m = ap.baca(skill_claude)
    s = [c for c in m.capabilities if c.jenis == "skill"]
    assert len(s) == 1
    assert s[0].nama == "ingat"
    assert s[0].status == "supported"
    assert s[0].pekerja == list(ap.PEKERJA)
    assert "Simpan sesuatu" in s[0].keterangan


def test_claude_plugin_agen_berkunci_khusus_jadi_converted(skill_claude):
    """Agen dengan `tools:` dan `isolation:` tidak punya padanan di CLI lain."""
    m = ap.baca(skill_claude)
    a = [c for c in m.capabilities if c.jenis == "agent"][0]
    assert a.nama == "penolong"
    assert a.status == "converted"
    assert "claude" in a.pekerja
    assert "opencode" in a.pekerja
    assert "tidak punya padanan" in a.alasan
    assert set(a.data["kunci_khusus"]) == {"model", "tools", "isolation"}


def test_claude_plugin_command_tidak_dipasang_sebagai_perintah(skill_claude):
    m = ap.baca(skill_claude)
    c = [x for x in m.capabilities if x.jenis == "command"][0]
    assert c.nama == "rangkum"
    assert c.status == "converted"
    assert "bukan perintah" in c.alasan


def test_claude_plugin_hook_dilewati_dengan_alasan(skill_claude):
    m = ap.baca(skill_claude)
    h = [c for c in m.capabilities if c.jenis == "hook"]
    assert {x.nama for x in h} == {"SessionStart", "PostToolUse"}
    assert all(x.status == "skipped" for x in h)
    assert all("harness" in x.alasan for x in h)


# ------------------------------------------------------------------ 2. Codex

def test_codex_plugin_dikenali(plugin_codex):
    d = ap.deteksi(plugin_codex)
    assert d["jenis"] == "codex"
    assert ".codex-plugin/plugin.json" in d["penanda"]


def test_codex_skill_dibaca(plugin_codex):
    m = ap.baca(plugin_codex)
    assert m.nama == "codexcontoh"
    s = [c for c in m.capabilities if c.jenis == "skill"][0]
    assert s.nama == "tdd"
    assert s.status == "supported"


def test_codex_agen_toml_dipakai_apa_adanya(tmp_path):
    """Agen Codex berbentuk .toml: statusnya supported untuk codex."""
    d = tmp_path / "codex-agen"
    (d / ".codex-plugin").mkdir(parents=True)
    (d / ".codex-plugin" / "plugin.json").write_text(json.dumps({"name": "c", "version": "1"}))
    (d / "agents").mkdir()
    (d / "agents" / "penjelajah.toml").write_text(
        'model = "gpt-5.5"\nsandbox_mode = "read-only"\n'
        'developer_instructions = """\nJelajahi kode.\n"""\n'
    )
    m = ap.baca(d)
    a = [c for c in m.capabilities if c.jenis == "agent"][0]
    assert a.nama == "penjelajah"
    assert a.status == "supported"
    # tanpa kunci khusus, isinya diterjemahkan ke keempat harness tanpa kehilangan apa pun
    assert sorted(a.pekerja) == sorted(ap.PEKERJA)
    assert a.data["peran"] == "codex"
    assert "Jelajahi kode." in a.keterangan


# ------------------------------------------------------------------ 3. Hermes

def test_hermes_plugin_dikenali(plugin_hermes):
    d = ap.deteksi(plugin_hermes)
    assert d["jenis"] == "hermes"
    assert "plugin.yaml" in d["penanda"]


def test_hermes_plugin_identitas_dan_blok_bersambung(plugin_hermes):
    m = ap.baca(plugin_hermes)
    assert m.nama == "hermescontoh"
    assert m.versi == "2.0.0"
    assert "Plugin contoh Hermes." in m.keterangan


def test_hermes_plugin_hook_tool_command_butuh_hermes(plugin_hermes):
    m = ap.baca(plugin_hermes)
    nama = {(c.jenis, c.nama) for c in m.capabilities}
    assert ("hook", "on_session_start") in nama
    assert ("hook", "pre_tool_call") in nama
    assert ("mcp", "alat_contoh") in nama
    assert ("command", "contoh") in nama
    assert all(c.status == "requires" for c in m.capabilities)
    assert all(c.alasan for c in m.capabilities)


def test_hermes_skill_standar_dibaca(skill_hermes):
    d = ap.deteksi(skill_hermes)
    assert d["jenis"] == "skill"
    m = ap.baca(skill_hermes)
    assert {c.nama for c in m.capabilities} == {"cognee-cli", "cognee-docker"}
    assert all(c.status == "supported" for c in m.capabilities)


# ------------------------------------------------------------------ 4. MCP

def test_mcp_dari_claude_plugin(skill_claude):
    m = ap.baca(skill_claude)
    s = [c for c in m.capabilities if c.jenis == "mcp"][0]
    assert s.nama == "memcontoh"
    assert s.status == "supported"
    assert s.data["mcp"]["transport"] == "stdio"
    assert s.data["mcp"]["target"] == "python3"


def test_mcp_dari_codex_plugin(plugin_codex):
    m = ap.baca(plugin_codex)
    s = [c for c in m.capabilities if c.jenis == "mcp"][0]
    assert s.nama == "codexmcp"
    assert s.data["mcp"]["target"] == "npx"
    assert s.data["mcp"]["args"] == ["-y", "@contoh/server"]


def test_mcp_http_dibaca_sebagai_http(tmp_path):
    d = tmp_path / "mcp-http"
    d.mkdir()
    (d / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"jauh": {"url": "https://contoh.invalid/mcp", "headers": {"X-Kunci": "v"}}}
    }))
    m = ap.baca(d)
    s = [c for c in m.capabilities if c.jenis == "mcp"][0]
    assert s.data["mcp"]["transport"] == "http"
    assert s.data["mcp"]["target"] == "https://contoh.invalid/mcp"
    assert s.data["mcp"]["header"] == {"X-Kunci": "v"}


def test_variabel_plugin_diganti_jalur_nyata(tmp_path, rumah):
    """${CLAUDE_PLUGIN_ROOT} harus jadi jalur nyata, bukan dibiarkan apa adanya."""
    d = tmp_path / "plugin-var"
    (d / ".claude-plugin").mkdir(parents=True)
    (d / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "var", "version": "1"}))
    (d / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"v": {"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/s.py"]}}
    }))
    m = ap.baca(d)
    hasil = ap.pasang(m, pilih=["mcp"], pekerja=[])
    assert hasil["ok"]
    # target/args sudah diganti sebelum diteruskan ke sistem MCP AstroZ
    s = [c for c in m.capabilities if c.jenis == "mcp"][0]
    target = ap._isi_var(s.data["mcp"]["args"][0], pathlib.Path(m.akar))
    assert target == str(d / "s.py")
    assert "${" not in target


# ------------------------------------------------------------------ 5. sebagian tidak kompatibel

def test_sebagian_kompatibel_semua_tercatat(plugin_sebagian):
    m = ap.baca(plugin_sebagian)
    h = m.hitung()
    assert h["total"] >= 6
    # tidak ada capability yang hilang tanpa status
    for c in m.capabilities:
        assert c.status in ("supported", "converted", "skipped", "requires")
    assert h["supported"] >= 2   # skill berguna + mcp sehat
    assert h["converted"] >= 2   # agen khusus + command
    assert h["skipped"] >= 2     # hook + enterprise


def test_mcp_rusak_dilewati_bukan_disalin(plugin_sebagian):
    m = ap.baca(plugin_sebagian)
    rusak = [c for c in m.capabilities if c.jenis == "mcp" and c.nama == "rusak"][0]
    assert rusak.status == "skipped"
    assert "tidak punya command maupun url" in rusak.alasan
    assert rusak.data == {}


def test_folder_enterprise_ditandai_skipped(plugin_sebagian):
    m = ap.baca(plugin_sebagian)
    e = [c for c in m.capabilities if c.nama == "enterprise"][0]
    assert e.status == "skipped"
    assert "Claude Code" in e.alasan


def test_pemasangan_tidak_menyalin_yang_dilewati(plugin_sebagian, rumah):
    """Inti aturan: yang skipped tidak boleh muncul sebagai tindakan berhasil."""
    m = ap.baca(plugin_sebagian)
    hasil = ap.pasang(m, pekerja=[])
    ditulis = {t["nama"] for t in hasil["tindakan"] if t.get("ok")}
    assert "rusak" not in ditulis
    assert "Stop" not in ditulis
    assert "enterprise" not in ditulis


def test_ringkasan_manifest_untuk_ui(plugin_sebagian):
    m = ap.baca(plugin_sebagian)
    r = m.ringkas()
    assert set(r["hitung"]) == {"supported", "converted", "skipped", "requires", "total"}
    assert r["hitung"]["total"] == len(r["capabilities"])
    assert all("data" not in c for c in r["capabilities"])


# ------------------------------------------------------------------ program biasa

def test_program_biasa_dinyatakan_bukan_plugin(tmp_path):
    d = tmp_path / "program"
    d.mkdir()
    (d / "pyproject.toml").write_text('[project]\nname = "program"\nversion = "1.0"\n')
    (d / "program.py").write_text("print('halo')\n")
    m = ap.baca(d)
    assert m.capabilities == []
    assert any("program biasa" in c for c in m.catatan)


# ------------------------------------------------------------------ pemasangan nyata

def test_pasang_skill_menautkan_ke_folder_pekerja(skill_hermes, rumah, monkeypatch):
    """Skill harus muncul sebagai tautan di folder yang dibaca pekerja."""
    tujuan = rumah / ".claude" / "skills"
    tujuan.mkdir(parents=True)
    monkeypatch.setattr(ap.plugins, "skill_folder_cli", lambda: [tujuan])
    m = ap.baca(skill_hermes)
    hasil = ap.pasang(m, pekerja=[])
    assert hasil["ok"]
    assert hasil["tautan"] == 2
    assert (tujuan / "cognee-cli").is_symlink()
    assert (tujuan / "cognee-cli" / "SKILL.md").exists()


def test_pasang_agen_menulis_ke_claude_dan_codex(skill_claude, rumah):
    m = ap.baca(skill_claude)
    ap.pasang(m, pilih=["agent"], pekerja=[])
    md = rumah / ".claude" / "agents" / "penolong.md"
    toml = rumah / ".codex" / "agents" / "penolong.toml"
    assert md.exists() and toml.exists()
    assert "penolong" in md.read_text()
    # berkas TOML harus bisa dibaca parser TOML, bukan sekadar ditulis
    import tomllib
    d = tomllib.loads(toml.read_text())
    assert "developer_instructions" in d
    # dan harus terdaftar, karena Codex tidak membaca folder itu tanpa daftar
    assert "[agents.penolong]" in (rumah / ".codex" / "config.toml").read_text()
    # opencode dan omp juga menerimanya, sebagai markdown
    assert (rumah / ".config" / "opencode" / "agent" / "penolong.md").exists()
    assert (rumah / ".omp" / "agent" / "agents" / "penolong.md").exists()


def test_pasang_ulang_tidak_menumpuk(skill_claude, rumah):
    m = ap.baca(skill_claude)
    ap.pasang(m, pilih=["agent"], pekerja=[])
    ap.pasang(m, pilih=["agent"], pekerja=[])
    teks = (rumah / ".codex" / "config.toml").read_text()
    assert teks.count("[agents.penolong]") == 1


def test_pasang_command_disimpan_sebagai_naskah(plugin_sebagian, rumah):
    m = ap.baca(plugin_sebagian)
    hasil = ap.pasang(m, pilih=["command"], pekerja=[])
    t = [x for x in hasil["tindakan"] if x.get("ok")][0]
    assert "naskah" in t["pesan"]
    assert pathlib.Path(t["path"]).exists()


# ------------------------------------------------------------------ registry

def test_catat_dan_lepas_paket(skill_claude, rumah, monkeypatch):
    monkeypatch.setattr(ap.plugins, "skill_folder_cli", lambda: [rumah / ".claude" / "skills"])
    m = ap.baca(skill_claude, sumber_url="https://github.com/contoh/repo")
    ap.catat_pasang(m, "https://github.com/contoh/repo", {"tautan": 3})
    t = ap.terpasang()
    assert [x["nama"] for x in t] == ["memcontoh"]
    assert t[0]["url"] == "https://github.com/contoh/repo"
    assert t[0]["hitung"]["total"] == m.hitung()["total"]
    r = ap.lupa("memcontoh")
    assert r["ok"]
    assert ap.terpasang() == []


# ------------------------------------------------------------------ URL

def test_url_repo_diterjemahkan():
    d = ap.baca_url("https://github.com/mem0ai/mem0")
    assert d["url"] == "https://github.com/mem0ai/mem0.git"
    assert d["slug"] == "mem0"
    assert d["sub"] == ""


def test_url_dengan_dot_git():
    assert ap.baca_url("https://github.com/a/b.git")["url"] == "https://github.com/a/b.git"


def test_url_folder_di_dalam_repo():
    d = ap.baca_url("https://github.com/mem0ai/mem0/tree/main/integrations/claude-code-plugin")
    assert d["cabang"] == "main"
    assert d["sub"] == "integrations/claude-code-plugin"


def test_url_pemilik_repo_tanpa_skema():
    assert ap.baca_url("openai/skills")["url"] == "https://github.com/openai/skills.git"


def test_url_bukan_github_ditolak():
    with pytest.raises(ValueError):
        ap.baca_url("https://gitlab.com/a/b")


def test_paket_lokal_diterima(tmp_path, skill_hermes):
    """Folder lokal harus bisa dipasang tanpa unduhan."""
    hasil = ap.unduh(str(skill_hermes))
    assert hasil == skill_hermes.resolve()


# ------------------------------------------------------------------ deteksi sub-plugin

def test_repo_besar_ditemukan_sub_pluginnya(tmp_path):
    """Repo yang menampung plugin di dalam folder harus tetap terdeteksi."""
    d = tmp_path / "repo-besar"
    (d / "integrations" / "claude-plugin" / ".claude-plugin").mkdir(parents=True)
    (d / "integrations" / "claude-plugin" / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "dalam", "version": "1"})
    )
    (d / "README.md").write_text("# repo besar\n")
    det = ap.deteksi(d)
    assert det["jenis"] == "tidak dikenal"
    assert det["sub"].endswith("integrations/claude-plugin")
    m = ap.baca(d)
    assert m.nama == "dalam"
    assert m.jenis_paket == "claude"


def test_daftar_plugin_dalam_repo(tmp_path):
    d = tmp_path / "banyak"
    for sub, nama in (("integrations/a/.claude-plugin", "a"), ("integrations/b/.codex-plugin", "b")):
        (d / sub).mkdir(parents=True)
        (d / sub / "plugin.json").write_text(json.dumps({"name": nama, "version": "1"}))
    hasil = ap.daftar_plugin_dalam(d)
    assert {x["nama"] for x in hasil} == {"a", "b"}
    assert {x["jenis"] for x in hasil} == {"claude", "codex"}


# ------------------------------------------------------------------ skill ganda

def test_skill_ganda_dihitung_sekali(tmp_path):
    """Salinan folder skill yang sama tidak boleh jadi dua capability."""
    d = tmp_path / "paket"
    for sub in ("skills", ".agents/skills"):
        (d / sub / "satu").mkdir(parents=True)
        (d / sub / "satu" / "SKILL.md").write_text("---\nname: satu\ndescription: Satu.\n---\n")
    m = ap.baca(d)
    assert len([c for c in m.capabilities if c.jenis == "skill"]) == 1
