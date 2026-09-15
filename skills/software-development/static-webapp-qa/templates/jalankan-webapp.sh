#!/usr/bin/env bash
# Launcher for a no-build static web app served over python3 -m http.server.
# Copy next to index.html, rename to whatever the user calls it, adjust APPNAME/PORT, chmod +x.
#
#   ./<script>              -> localhost only, opens the browser automatically
#   ./<script> lan          -> reachable from other devices on the same wifi (0.0.0.0)
#   ./<script> 9000         -> different port
#   ./<script> nobuka       -> do not open a browser
#
# Ctrl+C stops the server.

set -u

APPNAME="App"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8100
BIND=127.0.0.1
BUKA=1

for arg in "$@"; do
  case "$arg" in
    lan|LAN|jaringan|0.0.0.0) BIND=0.0.0.0 ;;
    nobuka|no-buka|nobrowser) BUKA=0 ;;
    ''|*[!0-9]*) echo "Argumen tidak dikenal: $arg" >&2; exit 1 ;;
    *) PORT="$arg" ;;
  esac
done

command -v python3 >/dev/null 2>&1 || { echo "python3 tidak ditemukan." >&2; exit 1; }

# Port already taken? Probe the socket directly: in a proot/Termux container a listening-port
# listing can be empty even while something is bound, so never gate on that listing.
if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
  exec 3<&- 3>&-
  echo "Port $PORT sudah dipakai proses lain."
  echo "Matikan dulu, atau pakai port lain:  ./$(basename "${BASH_SOURCE[0]}") $((PORT + 1))"
  exit 1
fi

URL="http://127.0.0.1:$PORT/"
echo "$APPNAME"
echo "  folder : $DIR"
echo "  alamat : $URL"
if [ "$BIND" = "0.0.0.0" ]; then
  IPS="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' | tr '\n' ' ')"
  [ -n "$IPS" ] && echo "  dari lain: http://<IP-perangkat-ini>:$PORT/   (IP terdeteksi: $IPS)"
fi
echo "  stop   : Ctrl+C"
echo

cd "$DIR" || exit 1
python3 -m http.server "$PORT" --bind "$BIND" &
SRV=$!

cleanup() { kill "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; echo; echo "Server dimatikan."; }
trap cleanup INT TERM

# Wait for readiness instead of sleeping blindly (max ~5s).
for _ in $(seq 1 25); do
  if curl -s -o /dev/null --max-time 1 "$URL" 2>/dev/null; then break; fi
  sleep 0.2
done

if [ "$BUKA" = "1" ]; then
  if command -v termux-open-url >/dev/null 2>&1; then
    termux-open-url "$URL" 2>/dev/null && echo "Browser dibuka: $URL"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 && echo "Browser dibuka: $URL"
  else
    echo "Buka manual di browser: $URL"
  fi
fi

wait "$SRV"
