"""Adaptor pekerja: perintah yang benar-benar dijalankan CLI.

Perintah adaptor pernah salah dengan cara yang mahal: claude memakai
`--output-format json` sehingga tidak mencetak apa pun selama 77 detik (penjaga
macet membunuhnya di menit ke-4 walau ia bekerja), dan model harus dikirim lewat
`--model` eksplisit karena settings.json menambah suffix `[1m]` yang tidak
dikenali gateway.
"""
from __future__ import annotations

import adapters


def _perintah(key: str, prompt: str = "tulis berkas", model: str = "kenari-id/deepseek-v4-1-flash"):
    a = adapters.ADAPTERS[key]
    a.path = a.path or f"/usr/bin/{key}"
    return a.command(prompt, model, "/tmp")


def test_claude_mengalir_bukan_menunggu_selesai():
    """stream-json + --verbose, bukan json.

    Diukur: dengan `json` CLI ini mencetak nol byte selama 77 detik, jadi penjaga
    macet (240s) membunuh pekerja sehat pada tugas yang lebih lambat dari itu.
    """
    cmd = _perintah("claude")
    assert "stream-json" in cmd
    assert "--verbose" in cmd
    assert "json" not in [x for x in cmd if x == "json"]


def test_claude_mengirim_model_eksplisit():
    cmd = _perintah("claude", model="model-uji/x")
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "model-uji/x"


def test_claude_melewati_izin_di_dalam_container():
    cmd = _perintah("claude")
    assert "--dangerously-skip-permissions" in cmd


def test_semua_pekerja_mengirim_model_yang_diminta():
    """Model yang dipilih di UI harus sampai ke perintah CLI, bukan cuma ke env."""
    for key, a in adapters.ADAPTERS.items():
        a.path = a.path or f"/usr/bin/{key}"
        if isinstance(a, adapters.OMPAdapter) and not a._help:
            a._help = "Usage: omp -p --model --auto-approve --no-session"
        cmd = a.command("tulis berkas", "model-uji/x", "/tmp")
        assert "model-uji/x" in " ".join(cmd), f"{key} tidak membawa model"


def test_adaptor_tidak_dipaksa_ada_di_mesin_ini():
    """ADAPTERS harus bisa diimpor walau CLI-nya belum terpasang."""
    for key, a in adapters.ADAPTERS.items():
        assert a.key == key
        assert callable(a.command)
        assert callable(a.parse)


def test_parse_selalu_mengembalikan_teks():
    for key, a in adapters.ADAPTERS.items():
        hasil = a.parse("keluaran biasa\nbaris kedua\n")
        assert isinstance(hasil, dict)
        assert isinstance(hasil.get("text"), str)


def test_omp_tidak_kehilangan_flag_saat_probe_belum_jalan(monkeypatch):
    """omp menyusun flag dari `--help`; `_help` kosong = semua flag hilang.

    Tanpa probe, perintahnya jadi `omp -p <tugas>` saja: model pilihan UI tidak
    terkirim dan omp berhenti di prompt persetujuan pertama (tugas menggantung).
    """
    a = adapters.OMPAdapter()
    a.path = "/usr/bin/omp"
    a.error = ""
    a._help = ""
    dipanggil: list[str] = []

    def probe_palsu():
        dipanggil.append("probe")
        a._help = "Usage: omp -p --model --auto-approve --no-session"
        return {}

    monkeypatch.setattr(a, "probe", probe_palsu)
    cmd = a.command("tugas", "model-uji/x", "/tmp")
    assert dipanggil == ["probe"]
    assert "--model" in cmd and "9router/model-uji/x" in cmd
    assert "--auto-approve" in cmd
