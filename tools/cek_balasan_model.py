#!/usr/bin/env python3
"""Periksa bentuk balasan model penalar lewat gateway.

Dipakai untuk memastikan jawaban yang sampai ke pengguna bukan jalan pikir
mentah. Jalankan: .venv/bin/python tools/cek_balasan_model.py "pertanyaan"
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/root/AstroZ")

import config  # noqa: E402
from gateway import Gateway  # noqa: E402

PERTANYAAN = sys.argv[1] if len(sys.argv) > 1 else "Halo, kamu bisa apa?"
SISTEM = (
    "Kamu AstroZ, asisten kerja. Jawab singkat dan ramah dalam bahasa Indonesia, "
    "satu sampai tiga kalimat. Jangan menyebut alat, berkas, atau pekerja."
)

cfg = config.load()
model = cfg["gateway"]["model"]
gw = Gateway(cfg)
out = gw.chat(model, [{"role": "system", "content": SISTEM}, {"role": "user", "content": PERTANYAAN}],
              timeout=180, max_tokens=400)
print("model:", model)
print("ok:", out.get("ok"))
teks = out.get("text") or ""
print("panjang:", len(teks))
print("--- jawaban yang akan tampil di gelembung chat ---")
print(teks)
print("--- selesai ---")
