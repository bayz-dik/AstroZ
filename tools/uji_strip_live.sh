#!/usr/bin/env bash
# Verifikasi nyata: kirim tugas lewat UI, pantau /api/tasks/running (yang dipakai
# strip kerja), lalu baca jawaban di sesi dan berkas hasil di workspace.
#
# Kunci sesi dan tugas dibaca dari jawaban /api/chat, bukan dari nilai tetap:
# UI yang sudah jalan memakai sesi yang sedang dibuka, jadi menebak namanya
# membuat skrip ini memeriksa percakapan yang salah dan melaporkan kosong.
set -uo pipefail
UI="http://127.0.0.1:8799"
PY=/root/AstroZ/.venv/bin/python
J() { "$PY" -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

echo "[1] kirim tugas lewat /api/chat"
CHAT=$(curl -s -m 30 -X POST "$UI/api/chat" -H 'Content-Type: application/json' \
  -d '{"text":"Tulis berkas uji_strip_live.txt berisi tepat satu baris: strip kerja hidup. Lalu laporkan isinya.","baru":true}')
echo "    $CHAT"
SID=$(echo "$CHAT" | J "d.get('session') or ''")
TID=$(echo "$CHAT" | J "d.get('task_id') or ''")
echo "    sid=$SID tid=$TID"

echo "[2] pantau /api/tasks/running (sumber data strip kerja)"
for i in $(seq 1 90); do
  sleep 5
  R=$(curl -s -m 15 "$UI/api/tasks/running")
  echo "    [$((i*5))s] $(echo "$R" | J "'running=%d pekerja=%s'%(len(d.get('running') or []), [ (p.get('key'),p.get('aktif')) for p in ((d.get('running') or [{}])[0].get('pekerja') or []) ])")"
  N=$(echo "$R" | J "len(d.get('running') or [])")
  [ "$N" = "0" ] && break
done

echo "[3] status akhir tugas"
curl -s -m 20 "$UI/api/tasks/$TID" | J "'status=%s size=%s workers=%s test=%s review=%s'%(d['task'].get('status'),d['task'].get('size'),d['task'].get('workers'),(d['task'].get('test') or {}).get('ok'),(d['task'].get('review') or {}).get('verdict'))"
echo "[4] jawaban di sesi (yang tampil di gelembung chat)"
curl -s -m 20 "$UI/api/sessions/$SID" | J "'%s'%[(m.get('role'),str(m.get('text'))[:300]) for m in d.get('messages',[])]"
echo "[5] berkas hasil"
ls -la /root/AstroZ/workspace/uji_strip_live.txt 2>/dev/null && cat /root/AstroZ/workspace/uji_strip_live.txt || echo "    MISSING"
