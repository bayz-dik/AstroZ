#!/usr/bin/env bash
# Pasang tiga alat luar yang diintegrasikan AstroZ, masing-masing di venv sendiri.
#
# Kenapa terpisah, bukan di venv server:
#   - aider mematok numpy<2, dan numpy 1.26 tidak punya wheel untuk Python 3.14
#     (harus dibangun dari sumber, dan itu gagal di container ini).
#   - memasangnya bersama server pernah membuat venv server kehilangan berkas
#     paket lain (requests, charset-normalizer), sampai `import requests` gagal.
#
# Dipakai: bash tools/pasang_alat.sh [mem0|cognee|aider|semua]
set -u

AKAR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PAKET="$AKAR/tools/paket"
UV="${UV:-uv}"
command -v "$UV" >/dev/null 2>&1 || UV="$(command -v uv || true)"
[ -n "$UV" ] || { echo "uv tidak ada di PATH. Pasang uv dulu."; exit 1; }

# Salin, jangan hardlink: di container proot ini hardlink ditolak uv dengan
# "Operation not permitted", dan kegagalan itu memotong pemasangan di tengah.
export UV_LINK_MODE=copy

mau="${1:-semua}"

pasang() {
  local nama="$1" py="$2" paket="$3"
  echo "=== $nama (python $py) ==="
  rm -rf "$PAKET/$nama"
  "$UV" venv --python "$py" "$PAKET/$nama" >/dev/null 2>&1 || {
    echo "  gagal membuat venv python $py"; return 1; }
  "$UV" pip install --python "$PAKET/$nama/bin/python" --link-mode=copy "$paket" >/dev/null 2>&1 || {
    echo "  gagal memasang $paket"; return 1; }
  # uv kadang tidak menyalin sebagian berkas sebuah paket, sehingga paketnya
  # terbaca sebagai namespace package dan impornya gagal dengan pesan yang
  # menyesatkan. Perbaikan ini membandingkan RECORD dengan isi folder.
  "$AKAR/.venv/bin/python" "$AKAR/tools/perbaiki_venv.py" "$PAKET/$nama" "$AKAR/.venv/bin/python" 2>/dev/null | tail -1
  # Dua paket berbeda memakai nama modul `jwt`; kalau perbaikan di atas mengambil
  # yang salah, isinya tercampur dan PyJWT perlu dipulihkan khusus.
  if [ "$nama" = "cognee" ]; then
    "$AKAR/.venv/bin/python" "$AKAR/tools/pulihkan_jwt.py" \
      "$PAKET/$nama/lib/python$py/site-packages" "$AKAR/.venv/bin/python" 2>/dev/null | tail -1
  fi
  # Diperiksa dengan penerjemah venv itu sendiri, bukan venv server.
  "$PAKET/$nama/bin/python" -c "import $nama" >/dev/null 2>&1 \
    && echo "  $nama siap di $PAKET/$nama" \
    || echo "  $nama terpasang, tetapi impornya belum bisa dipastikan"
}

case "$mau" in
  mem0)   pasang mem0 3.14 mem0ai ;;
  cognee) pasang cognee 3.12 cognee ;;
  aider)  pasang aider 3.12 aider-chat ;;
  semua)
    pasang mem0 3.14 mem0ai
    pasang cognee 3.12 cognee
    pasang aider 3.12 aider-chat
    ;;
  *) echo "pilihan tidak dikenal: $mau (pakai: mem0|cognee|aider|semua)"; exit 1 ;;
esac

echo
echo "Selesai. Jalankan langsung:"
echo "  $PAKET/aider/bin/aider --version"
echo "  $PAKET/cognee/bin/python -c 'import cognee; print(cognee.__version__)'"
echo "  $AKAR/.venv/bin/python -c 'import mem0; print(mem0.__version__)'"
