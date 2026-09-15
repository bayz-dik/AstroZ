#!/usr/bin/env bash
# Launch a local Flask app together with a cloudflared public tunnel.
# Usage: ./jalan-tunnel.sh   (Ctrl+C stops both). Copy and adjust APP/port names.
set -e
cd "$(dirname "$0")" || exit 1

CF="${CLOUDFLARED_BIN:-$HOME/bin/cloudflared}"
PY=".venv/bin/python"; [ -x "$PY" ] || PY=python3

# Port is in use? (ss is unreliable under proot — probe with a real connect.)
port_busy() {
  "$PY" - "$1" <<'PYEOF'
import socket, sys
s = socket.socket(); s.settimeout(0.5)
try:
    s.connect(("127.0.0.1", int(sys.argv[1]))); sys.exit(0)
except Exception:
    sys.exit(1)
finally:
    s.close()
PYEOF
}

PORT="${PECUT_PORT:-5000}"; ORIG="$PORT"
# 1) clear stale processes of OUR app (narrow pattern — never match the invoking shell)
if port_busy "$PORT"; then
  echo "[launch] port $PORT busy — clearing stale app/tunnel..."
  pkill -f "python app.py" 2>/dev/null || true
  pkill -f "cloudflared tunnel" 2>/dev/null || true
  sleep 1
fi
# 2) still busy (another program) -> pick a free fallback port
if port_busy "$PORT"; then
  for p in 5001 5002 5050 8000 8080 8888; do
    if ! port_busy "$p"; then PORT="$p"; break; fi
  done
  [ "$PORT" != "$ORIG" ] && echo "[launch] $ORIG busy — using $PORT"
fi

# Ensure cloudflared (arm64 for aarch64 phones).
if [ ! -x "$CF" ]; then
  mkdir -p "$(dirname "$CF")"
  curl -sL -o "$CF" https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64
  chmod +x "$CF"
fi

CFLOG="$(mktemp)"
# --protocol http2: QUIC is often blocked on mobile networks.
"$CF" tunnel --protocol http2 --url "http://127.0.0.1:$PORT" >"$CFLOG" 2>&1 &
CF_PID=$!
trap 'kill "$CF_PID" 2>/dev/null; rm -f "$CFLOG"' EXIT INT TERM

URL=""
for _ in $(seq 1 40); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$CFLOG" | head -1 || true)
  [ -n "$URL" ] && break; sleep 1
done
[ -z "$URL" ] && { echo "[launch] no tunnel URL"; tail -20 "$CFLOG"; exit 1; }
export PUBLIC_URL="$URL"
echo "[launch] public URL: $URL  (local: http://127.0.0.1:$PORT)"

exec "$PY" app.py
