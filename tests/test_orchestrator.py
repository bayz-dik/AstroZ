"""Orkestrator: penerjemah stream-json dan pemeriksaan pintu gateway.

Dua hal ini pernah membuat tugas gagal padahal pekerjanya sehat, jadi keduanya
diuji langsung, bukan lewat tugas penuh (yang butuh CLI dan model hidup).
"""
from __future__ import annotations

import json

import orchestrator


# --------------------------------------------------------------- stream-json
def test_baris_bukan_json_dibiarkan():
    """Baris biasa harus lewat apa adanya, bukan dianggap stream-json.

    Penerjemah yang menelan baris biasa akan menghapus seluruh keluaran CLI
    selain Claude, dan gejalanya cuma \"jawaban kosong\".
    """
    assert orchestrator._teks_dari_stream_json("selesai, berkas dibuat") is None
    assert orchestrator._teks_dari_stream_json("") is None


def test_teks_assistant_diambil():
    baris = json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "text", "text": "Berkas uji.txt sudah dibuat."},
            {"type": "tool_use", "name": "Write"},
        ]},
    })
    hasil = orchestrator._teks_dari_stream_json(baris)
    assert hasil is not None
    assert "Berkas uji.txt sudah dibuat." in hasil
    assert "Write" in hasil


def test_hasil_akhir_diambil_dari_result():
    baris = json.dumps({"type": "result", "result": "ringkasan akhir"})
    assert orchestrator._teks_dari_stream_json(baris) == "ringkasan akhir"


def test_penanda_sesi_tidak_ikut_tampil():
    """Baris system/user panjang dan tidak berguna untuk dibaca manusia."""
    for tipe in ("system", "user"):
        assert orchestrator._teks_dari_stream_json(json.dumps({"type": tipe, "x": 1})) == ""


def test_clean_output_menerjemahkan_dan_membuang_noise():
    """Log mentah pekerja tidak boleh sampai ke panel aktivitas atau jawaban."""
    raw = "\n".join([
        json.dumps({"type": "system", "subtype": "init", "tools": ["x"] * 50}),
        "\x1b[32m> build · kenari-id/deepseek-v4-1-flash\x1b[0m",
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Halo dari pekerja."}]}}),
        json.dumps({"type": "result", "result": "Selesai."}),
    ])
    bersih = orchestrator.clean_output(raw)
    assert "Halo dari pekerja." in bersih
    assert "Selesai." in bersih
    assert "\x1b" not in bersih
    assert '"type"' not in bersih


# ------------------------------------------------------------ pintu gateway
def test_pintu_gateway_menyebut_port_yang_mati(monkeypatch, cfg_sementara):
    """Port mati harus disebut namanya, bukan cuma \"gateway online\".

    Insiden aslinya: penyaring SSE di :20129 mati sementara :20128 sehat, UI
    melaporkan gateway online, lalu setiap pekerja menunggu jawaban yang tidak
    akan datang sampai batas waktunya habis.
    """
    import socket

    def hanya_upstream(alamat, timeout=None):
        host, port = alamat
        if int(port) != 20128:
            raise OSError("connection refused")
        return socket.socket()

    monkeypatch.setattr(socket, "create_connection", hanya_upstream)
    hasil = orchestrator.pintu_gateway_hidup(cfg_sementara)
    assert hasil["ok"] is False
    assert any("20129" in m for m in hasil["mati"])
    assert "20129" in hasil["pesan"]


def test_pintu_gateway_hijau_menyebut_keduanya(monkeypatch, cfg_sementara):
    import socket

    dipanggil: list[int] = []

    def semua_up(alamat, timeout=None):
        dipanggil.append(int(alamat[1]))
        return socket.socket()

    monkeypatch.setattr(socket, "create_connection", semua_up)
    hasil = orchestrator.pintu_gateway_hidup(cfg_sementara)
    assert hasil["ok"] is True
    assert sorted(dipanggil) == [20128, 20129]


def test_pintu_gateway_cek_port_api_base_bukan_tebakan(cfg_sementara):
    """Alamat diperiksa dari setelan, jadi port yang diubah di team.yaml ikut.

    Pernah terjadi api_base menunjuk :20130 yang tidak ada yang mendengarkan,
    dan tidak ada pemeriksaan mana pun yang menyebutnya.
    """
    import socket

    dilihat: list[int] = []

    def catat(alamat, timeout=None):
        dilihat.append(int(alamat[1]))
        return socket.socket()

    cfg_sementara["gateway"]["api_base"] = "http://127.0.0.1:20999/v1"
    import socket as s
    asli = s.create_connection
    s.create_connection = catat
    try:
        orchestrator.pintu_gateway_hidup(cfg_sementara)
    finally:
        s.create_connection = asli
    assert 20999 in dilihat


# ------------------------------------------------------------ pohon proses
def test_pohon_proses_selalu_memuat_pid_itu_sendiri():
    import os

    assert os.getpid() in orchestrator._pohon_proses(os.getpid())
