#!/usr/bin/env bash
# AstroZ launcher: gateway -> UI -> URL untuk HP.
# Usage: ./run.sh [port] [--no-9router] [--foreground]
#
# Python yang dipakai dicari berurutan: $PY, lalu .venv di folder ini, lalu
# python3. Setelah terpilih, ketiga paket wajibnya diperiksa; kalau ada yang
# hilang, skrip berhenti dengan cara memperbaikinya, bukan gagal di tengah.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8799}"
shift || true
START_9R=1
FG=0
for a in "$@"; do
  case "$a" in
    --no-9router) START_9R=0 ;;
    --foreground) FG=1 ;;
  esac
done

cari_python() {
  if [ -n "${PY:-}" ] && [ -x "${PY}" ]; then echo "$PY"; return; fi
  for kandidat in "$DIR/.venv/bin/python" "$DIR/venv/bin/python"; do
    if [ -x "$kandidat" ]; then echo "$kandidat"; return; fi
  done
  command -v python3 || true
}

PY="$(cari_python)"
if [ -z "$PY" ]; then
  echo "[run] python3 tidak ditemukan. Pasang Python 3.10 atau lebih baru." >&2
  exit 1
fi

# Paket wajib. Tanpa pemeriksaan ini, kegagalan muncul sebagai stack trace
# uvicorn yang membingungkan orang yang baru memasang.
if ! "$PY" - <<'CEK' >/dev/null 2>&1
import fastapi, uvicorn, yaml
CEK
then
  echo "[run] python yang dipakai: $PY" >&2
  echo "[run] paket wajib belum lengkap (fastapi, uvicorn, PyYAML)." >&2
  echo "[run] jalankan:" >&2
  echo "[run]   python3 -m venv \"$DIR/.venv\"" >&2
  echo "[run]   \"$DIR/.venv/bin/pip\" install -r \"$DIR/requirements.txt\"" >&2
  echo "[run] lalu ulangi ./run.sh" >&2
  exit 1
fi

mkdir -p "$DIR/logs" "$DIR/runtime"

port_open() { (echo > "/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1; }

if [ "$START_9R" = "1" ] && ! port_open 20128; then
  if command -v 9router >/dev/null 2>&1; then
    echo "[run] starting 9Router on :20128"
    nohup 9router --no-browser --skip-update --port 20128 >> "$DIR/logs/9router.log" 2>&1 &
    for _ in $(seq 1 40); do port_open 20128 && break; sleep 0.5; done
  else
    echo "[run] 9Router tidak ada di PATH. Gateway harus jalan sendiri di :20128."
    echo "[run] Baca bagian \"Yang perlu ada dulu\" di README."
  fi
fi
if port_open 20128; then echo "[run] 9Router up: http://127.0.0.1:20128"; else echo "[run] WARN 9Router not reachable on :20128"; fi

# SSE sanitiser: 9Router sends `data: [DONE]` twice, which kills strict SSE
# parsers (opencode). Workers talk to :20129 instead of :20128.
if ! port_open 20129; then
  echo "[run] starting SSE sanitiser on :20129"
  nohup "$PY" "$DIR/proxy.py" --listen 20129 >> "$DIR/logs/proxy.log" 2>&1 &
  for _ in $(seq 1 20); do port_open 20129 && break; sleep 0.5; done
fi
if port_open 20129; then echo "[run] gateway (sanitised): http://127.0.0.1:20129/v1"; else echo "[run] WARN SSE sanitiser not reachable on :20129"; fi

if port_open "$PORT"; then
  echo "[run] port $PORT busy, reusing existing server"
else
  cd "$DIR"
  if [ "$FG" = "1" ]; then
    exec "$PY" -m uvicorn server:app --host 0.0.0.0 --port "$PORT"
  fi
  nohup "$PY" -m uvicorn server:app --host 0.0.0.0 --port "$PORT" >> "$DIR/logs/ui.log" 2>&1 &
  for _ in $(seq 1 40); do port_open "$PORT" && break; sleep 0.5; done
fi

IP="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' | head -1)"
[ -n "$IP" ] || IP="127.0.0.1"
echo "[run] UI (phone):  http://$IP:$PORT/"
echo "[run] UI (local):  http://127.0.0.1:$PORT/"
echo "[run] logs:        $DIR/logs/ui.log"
command -v termux-open-url >/dev/null 2>&1 && termux-open-url "http://127.0.0.1:$PORT/" || true
