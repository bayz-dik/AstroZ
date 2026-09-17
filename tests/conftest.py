"""Perkakas bersama untuk suite tes AstroZ.

Suite ini menguji modul AstroZ sebagai pustaka, bukan lewat jaringan: server
yang sedang jalan dan tes yang jalan bersamaan tidak boleh saling mengganggu.
Yang diuji di sini adalah perilaku yang sudah pernah salah di mesin ini
(penerjemah stream-json, perintah adaptor, garis dasar berkas, pintu gateway),
jadi setiap tes menyebut alasan aslinya.

Jalankan dari akar repo:

    .venv/bin/python -m pytest -q

`config.load()` membaca team.yaml asli, yang berisi API key. Tes tidak boleh
menyentuh berkas itu: fixture di bawah mengarahkan CONFIG_PATH ke salinan
sementara di tmp_path, jadi tidak ada tes yang menulis setelan pengguna.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402


@pytest.fixture()
def cfg_sementara(tmp_path, monkeypatch):
    """Setelan tiruan: team.yaml sementara, folder kerja sementara.

    Dipakai tes yang memanggil config.load()/config.save(). Tanpa ini, satu tes
    yang memanggil save() bisa menimpa team.yaml pengguna, termasuk API key.
    """
    cfg_path = tmp_path / "team.yaml"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(config, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(config, "META_PATH", tmp_path / "runtime" / "model_meta.json")
    monkeypatch.setattr(config, "MODELS_PATH", tmp_path / "runtime" / "models.json")
    cfg = config.load()
    cfg["project_dir"] = str(tmp_path / "kerja")
    cfg["gateway"]["api_key"] = "kunci-uji"
    cfg["gateway"]["api_base"] = "http://127.0.0.1:20129/v1"
    cfg["gateway"]["upstream_base_url"] = "http://127.0.0.1:20128"
    config.save(cfg)
    return cfg


@pytest.fixture()
def folder_kerja(tmp_path, monkeypatch):
    """Folder kerja git kosong, untuk tes garis dasar berkas dan commit."""
    import project

    d = tmp_path / "kerja"
    d.mkdir()
    monkeypatch.setattr(project, "project_dir", lambda: d)
    monkeypatch.setattr(project, "ensure_repo", lambda: d)
    monkeypatch.delenv("ASTROZ_PEKERJA", raising=False)
    return d
