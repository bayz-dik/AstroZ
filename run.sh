#!/usr/bin/env bash
# AstroZ launcher: gateway -> UI -> URL untuk HP.
# Usage: ./run.sh [port] [--no-9router] [--foreground]
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
PY="${PY:-/usr/local/lib/hermes-agent/venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p "$DIR/logs" "$DIR/runtime"

port_open() { (echo > "/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1; }

if [ "$START_9R" = "1" ] && ! port_open 20128; then
  echo "[run] starting 9Router on :20128"
  nohup 9router --no-browser --skip-update --port 20128 >> "$DIR/logs/9router.log" 2>&1 &
  for _ in $(seq 1 40); do port_open 20128 && break; sleep 0.5; done
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

IP="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -1)"
[ -n "$IP" ] || IP="127.0.0.1"
echo "[run] UI (phone):  http://$IP:$PORT/"
echo "[run] UI (local):  http://127.0.0.1:$PORT/"
echo "[run] logs:        $DIR/logs/ui.log"
command -v termux-open-url >/dev/null 2>&1 && termux-open-url "http://127.0.0.1:$PORT/" || true
