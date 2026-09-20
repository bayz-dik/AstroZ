"""Uji bulat fitur ganti sandi lewat HTTP, bukan lewat UI.

Yang dibuktikan: sandi BARU benar-benar dipakai untuk masuk, dan sandi LAMA
ditolak. Dijalankan atas server yang sedang hidup, lalu dikembalikan ke nilai
semula supaya pengguna tidak terkunci di luar.
"""
import json
import pathlib
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8799"
TOKEN = pathlib.Path("/root/AstroZ/app_token.txt").read_text().strip()
LAMA, BARU = "12345", "ujicoba99"


def minta(jalur, data=None, token_masuk=None, cookie=None, metode=None):
    """Kirim permintaan ke server.

    Catatan bentuk: `/api/masuk` menerima sandi lewat field `token`, BUKAN
    `sandi` -- begitu juga yang dikirim `web/app.js`. Field `sandi` hanya dipakai
    `/api/sandi` (ganti sandi). Salah field di sini membuat sandi yang benar
    dijawab 403 "token tidak dikenali", dan itu terlihat seperti bug server.
    """
    isi = data
    if token_masuk is not None:
        isi = {"token": token_masuk}
    body = json.dumps(isi).encode() if isi is not None else None
    req = urllib.request.Request(BASE + jalur, data=body,
                                 method=metode or ("POST" if body else "GET"))
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + TOKEN)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()[:200], r.headers.get("set-cookie", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200], ""


hasil = []

# 1. ganti sandi ke nilai baru
st, isi, _ = minta("/api/sandi", {"sandi": BARU})
hasil.append(("ganti sandi", st, isi))

# 2. masuk dengan sandi BARU harus berhasil
st, isi, ck = minta("/api/masuk", token_masuk=BARU)
hasil.append(("masuk sandi baru", st, isi))

# 3. masuk dengan sandi LAMA harus ditolak
st, isi, _ = minta("/api/masuk", token_masuk=LAMA)
hasil.append(("masuk sandi lama (harus 401/403)", st, isi))

# 4. kembalikan
st, isi, _ = minta("/api/sandi", {"sandi": LAMA})
hasil.append(("kembalikan sandi", st, isi))

# 5. masuk lagi dengan sandi semula
st, isi, _ = minta("/api/masuk", token_masuk=LAMA)
hasil.append(("masuk sandi semula", st, isi))

for nama, st, isi in hasil:
    print(f"{nama:34s} -> {st}  {isi}")

