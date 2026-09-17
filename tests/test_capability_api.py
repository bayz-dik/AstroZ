"""API adapter plugin universal di server.

Yang diuji di sini adalah bentuk rute dan penanganan masukannya, bukan
unduhan sungguhan: rute yang salah bentuk membuat UI menampilkan pesan
kesalahan yang tidak menjelaskan apa pun, dan itu yang paling sering terjadi
saat endpoint baru ditambahkan.
"""
from __future__ import annotations

import pytest

server = pytest.importorskip("server", reason="butuh fastapi (venv repo)")
adapters_plugin = pytest.importorskip("adapters_plugin")


def _rute() -> list[str]:
    return [getattr(r, "path", "") for r in server.app.routes]


def test_rute_capability_terdaftar():
    r = _rute()
    assert "/api/capability" in r
    assert "/api/capability/pratinjau" in r
    assert "/api/capability/pasang" in r
    assert "/api/capability/{nama}" in r


def test_rute_tetap_capability_sebelum_yang_dinamis():
    """Rute tetap harus mendahului rute dinamis supaya tidak tertelan.

    Ini pola yang sudah pernah menggigit di proyek ini: `/api/tasks/running`
    terbaca sebagai `/api/tasks/{tid}` dan menjawab 404.
    """
    r = _rute()
    i_pasang = r.index("/api/capability/pasang")
    i_pratinjau = r.index("/api/capability/pratinjau")
    i_dinamis = r.index("/api/capability/{nama}")
    assert i_pasang < i_dinamis
    assert i_pratinjau < i_dinamis


def test_marketplace_lama_masih_ada():
    """Sistem skill dan marketplace yang lama tidak boleh hilang."""
    r = _rute()
    assert "/api/marketplace" in r
    assert "/api/skills" in r
    assert "/api/mcp" in r


def test_jenis_capability_selaras_dengan_adapter():
    assert set(adapters_plugin.JENIS) == {"skill", "agent", "command", "hook", "mcp", "rule"}
    assert set(adapters_plugin.PEKERJA) == {"claude", "codex", "opencode", "omp"}


def test_status_yang_dikenal():
    """Empat status yang dipakai manifest, dan tidak ada yang lain."""
    m = adapters_plugin.Manifest(nama="x", jenis_paket="skill", akar="/tmp")
    m.capabilities = [
        adapters_plugin.Capability(jenis="skill", nama="a", sumber="skill", status="supported"),
        adapters_plugin.Capability(jenis="command", nama="b", sumber="claude", status="converted"),
        adapters_plugin.Capability(jenis="hook", nama="c", sumber="claude", status="skipped"),
        adapters_plugin.Capability(jenis="mcp", nama="d", sumber="hermes", status="requires"),
    ]
    h = m.hitung()
    assert h == {"supported": 1, "converted": 1, "skipped": 1, "requires": 1, "total": 4}


def test_ringkas_manifest_tidak_membawa_data_mentah():
    """Ringkasan untuk UI tidak boleh membocorkan isi berkas paket."""
    c = adapters_plugin.Capability(
        jenis="skill", nama="a", sumber="skill", status="supported",
        data={"path": "/rahasia/jalur"},
    )
    m = adapters_plugin.Manifest(nama="x", jenis_paket="skill", akar="/tmp", capabilities=[c])
    r = m.ringkas()
    assert "data" not in r["capabilities"][0]
    assert "/rahasia" not in str(r)
