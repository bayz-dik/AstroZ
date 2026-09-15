#!/usr/bin/env bash
# Uji nyata tombol "hentikan": kirim tugas panjang, hentikan saat pekerja jalan,
# lalu pastikan proses pekerja mati dan statusnya jadi cancelled.
#
# Proses pekerja dicari lewat pohon proses server UI (anak dari pid uvicorn),
# bukan lewat cocok-cocokan nama: nama CLI bisa muncul juga di perintah lain.
set -uo pipefail
UI="http://127.0.0.1:8799"
PY=/root/AstroZ/.venv/bin/python
J() { "$PY" -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

pohon() {
  "$PY" - <<'PYEOF'
import os
def anak(pid):
    out=[]
    for p in os.listdir('/proc'):
        if not p.isdigit(): continue
        try:
            ppid=int(open(f'/proc/{p}/stat').read().split(') ',1)[1].split()[1])
        except Exception: continue
        if ppid==pid: out.append(int(p))
    return out

server=None
for pid in os.listdir('/proc'):
    if not pid.isdigit(): continue
    try:
        cmd=open(f'/proc/{pid}/cmdline','rb').read().decode(errors='replace').replace('\x00',' ')
        cwd=os.readlink(f'/proc/{pid}/cwd')
    except Exception: continue
    if 'uvicorn' in cmd and 'server:app' in cmd and cwd=='/root/AstroZ':
        server=int(pid)
print(f"    server pid={server}")
if not server:
    raise SystemExit
turunan=[]
stack=[server]
while stack:
    for c in anak(stack.pop()):
        turunan.append(c); stack.append(c)
n=0
for pid in turunan:
    try: cmd=open(f'/proc/{pid}/cmdline','rb').read().decode(errors='replace').replace('\x00',' ').strip()
    except Exception: continue
    if not cmd: continue
    n+=1
    print(f"    anak pid={pid} {cmd[:80]}")
print(f"    total proses turunan: {n}")
PYEOF
}

echo "[1] kirim tugas panjang lewat /api/chat"
CHAT=$(curl -s -m 30 -X POST "$UI/api/chat" -H 'Content-Type: application/json' \
  -d '{"text":"Tulis 200 baris penjelasan rinci tentang arsitektur perangkat lunak ke berkas uji_batal.txt, lalu periksa ulang isinya baris per baris.","baru":true}')
TID=$(echo "$CHAT" | J "d.get('task_id') or ''")
SID=$(echo "$CHAT" | J "d.get('session') or ''")
echo "    tid=$TID sid=$SID"

echo "[2] tunggu pekerja mulai"
for i in $(seq 1 40); do
  sleep 3
  R=$(curl -s -m 15 "$UI/api/tasks/running")
  N=$(echo "$R" | J "len(d.get('running') or [])")
  W=$(echo "$R" | J "[p.get('key') for p in ((d.get('running') or [{}])[0].get('pekerja') or [])]")
  echo "    [$((i*3))s] running=$N pekerja=$W"
  [ "$N" = "1" ] && [ "$W" != "[]" ] && break
done

echo "[3] pohon proses SEBELUM hentikan"
pohon

echo "[4] tekan hentikan"
curl -s -m 30 -X POST "$UI/api/tasks/$TID/hentikan" -H 'Content-Type: application/json' -d '{}'
echo

echo "[5] status sesudah hentikan (3 putaran)"
for i in 1 2 3; do
  sleep 4
  curl -s -m 15 "$UI/api/tasks/$TID" | J "'    status=%s finished=%s'%(d['task'].get('status'), bool(d['task'].get('finished')))"
  curl -s -m 15 "$UI/api/tasks/running" | J "'    masih berjalan: %d'%len(d.get('running') or [])"
done

echo "[6] pohon proses SESUDAH hentikan"
pohon

echo "[7] jawaban di chat"
curl -s -m 20 "$UI/api/sessions/$SID" | J "'%s'%[(m.get('role'), m.get('status'), str(m.get('text'))[:120]) for m in d.get('messages',[])]"
