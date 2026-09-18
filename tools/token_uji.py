"""Membuat token uji untuk akun admin, supaya endpoint bisa diuji dari skrip.

Token asli tidak pernah ditampilkan; skrip ini hanya menuliskan token barunya ke
/tmp/tok_uji (di luar repo) supaya skrip uji bisa memakainya. Dipakai saat
menguji API di mesin pengembangan, bukan di perangkat.
"""
import secrets
import sys
import pathlib

sys.path.insert(0, "/root/AstroZ")
import users  # noqa: E402

users.load()
print("akun yang ada:", list(users._U))

nama = "admin"
if nama not in users._U:
    print("akun admin tidak ada; dibuat baru")
    users.buat(nama, "admin")

tok = "uji-" + secrets.token_hex(16)
u = users._U[nama]
u["sidik"] = users._sidik(tok, u["garam"])
users._persist()
pathlib.Path("/tmp/tok_uji").write_text(tok)
print("token uji dibuat, panjang", len(tok), "-> /tmp/tok_uji")
