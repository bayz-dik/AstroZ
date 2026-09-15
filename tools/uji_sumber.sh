#!/usr/bin/env bash
# Uji nyata fitur sumber: kirim tugas mencari info sebuah layanan, lalu pastikan
# jawaban di sesi membawa daftar sumber (nama + url) yang dipakai UI untuk
# menampilkan lambang merek kecil di bawah gelembung jawaban.
#
# Pemakaian: tools/uji_sumber.sh ["pertanyaan"] [tunggu_detik]
set -uo pipefail
UI="http://127.0.0.1:8799"
PY=/root/AstroZ/.venv/bin/python
J() { "$PY" -c "import sys,json;d=json.load(sys.stdin);print($1)"; }
PERTANYAAN="${1:-Cari info terbaru tentang layanan OpenAI, lalu tulis ringkasannya ke berkas openai.md}"
TUNGGU="${2:-600}"

echo "[1] kirim tugas pencarian lewat /api/chat"
CHAT=$(curl -s -m 30 -X POST "$UI/api/chat" -H 'Content-Type: application/json' \
  -d "$("$PY" -c 'import json,sys;print(json.dumps({"text":sys.argv[1],"baru":True}))' "$PERTANYAAN")")
echo "    $CHAT"
SID=$(echo "$CHAT" | J "d.get('session') or ''")
TID=$(echo "$CHAT" | J "d.get('task_id') or ''")
echo "    sid=$SID tid=$TID"
[ -n "$TID" ] || { echo "GAGAL: tidak dapat task id"; exit 1; }

echo "[2] pantau sampai selesai (maks ${TUNGGU}s)"
i=0
while [ "$i" -lt "$TUNGGU" ]; do
  sleep 10; i=$((i+10))
  ST=$(curl -s -m 15 "$UI/api/tasks/$TID" | J "d['task'].get('status')")
  echo "    [${i}s] status=$ST"
  case "$ST" in done|failed|cancelled|interrupted) break;; esac
done

echo "[3] ringkasan tugas"
curl -s -m 20 "$UI/api/tasks/$TID" | J "'status=%s size=%s workers=%s'%(d['task'].get('status'),d['task'].get('size'),d['task'].get('workers'))"

echo "[4] sumber yang tersimpan di tugas (dipakai chip lambang)"
curl -s -m 20 "$UI/api/tasks/$TID" | "$PY" -c "
import sys,json
d=json.load(sys.stdin); t=d['task']
src=t.get('sources') or []
print('    jumlah sumber:', len(src))
for s in src: print('    -', s.get('nama'), '|', s.get('url'))
print('    jawaban:', (t.get('answer') or '')[:300].replace(chr(10),' '))
"

echo "[5] sumber yang sampai ke pesan sesi (yang dirender UI)"
curl -s -m 20 "$UI/api/sessions/$SID" | "$PY" -c "
import sys,json
d=json.load(sys.stdin)
for m in d.get('messages',[]):
    if m.get('role')!='astroz': continue
    print('    tugas=%s status=%s sumber=%s'%(m.get('task'),m.get('status'),m.get('sources')))
"

echo "[6] berkas hasil di workspace"
ls -la /root/AstroZ/workspace/openai.md 2>/dev/null || echo "    (openai.md tidak ada)"
