#!/usr/bin/env python3
"""Uji model mana yang benar-benar menjawab lewat 9Router, lalu laporkan.

Alat ini menjawab pertanyaan "pekerja kelihatan rusak padahal cuma modelnya mati".
Jalankan: .venv/bin/python tools/uji_model.py [id_model ...]
Tanpa argumen: model yang sedang dipakai, ditambah beberapa kandidat populer.
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "/root/AstroZ")

import config  # noqa: E402
from gateway import Gateway  # noqa: E402

cfg = config.load()
gw = Gateway(cfg)
model_kini = cfg["gateway"]["model"]
kandidat = sys.argv[1:] or [
    model_kini,
    "kenari-id/deepseek-v4-1-flash",
    "alicode-intl/glm-5",
    "alicode-intl/kimi-k2.5",
    "alicode-intl/qwen3.5-plus",
]

for m in kandidat:
    out = gw.chat(m, [{"role": "user", "content": "Balas satu kata: siap"}], timeout=60, max_tokens=64, retries=1)
    if out.get("ok"):
        teks = (out.get("text") or "").strip().replace("\n", " ")[:60]
        print(f"HIDUP  {m} -> {teks!r}")
    else:
        print(f"MATI   {m} -> {(out.get('error') or '')[:160]}")
