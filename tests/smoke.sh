#!/usr/bin/env bash
# End-to-end smoke test for the AstroZ stack.
#   ./tests/smoke.sh [--quick]
# Checks: 9Router health, model sync, each worker CLI through the gateway,
# full orchestrator task (plan -> worker -> test -> review), git + UI API.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS="$DIR/workspace"
UI="http://127.0.0.1:${UI_PORT:-8799}"
PY="${PY:-/usr/local/lib/hermes-agent/venv/bin/python}"
LOG="$DIR/logs/smoke.log"
mkdir -p "$DIR/logs" "$WS"
: > "$LOG"
say() { echo "[smoke] $*" | tee -a "$LOG"; }
json() { "$PY" -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

say "1. 9Router health"
curl -s -m 10 http://127.0.0.1:20128/api/health | tee -a "$LOG"; echo | tee -a "$LOG"

say "2. UI API state"
curl -s -m 15 "$UI/api/state" | json "'workers: '+','.join(w['key']+('+' if w['installed'] else '-') for w in d['workers'])" | tee -a "$LOG"

say "3. model sync"
curl -s -m 120 -X POST "$UI/api/gateway/sync?apply=0" | json "'models=%s online=%s current=%s'%(d.get('models'),d.get('online'),d.get('model'))" | tee -a "$LOG"

MODEL="${MODEL:-}"
if [ -z "$MODEL" ]; then
  MODEL=$(curl -s -m 20 "$UI/api/gateway/models?limit=1" | json "d['current'] or ''")
fi
say "using model: $MODEL"

say "4. direct worker smoke (gateway model, 240s each)"
"$PY" "$DIR/tests/worker_smoke.py" --model "$MODEL" --timeout "${WORKER_TIMEOUT:-240}" | tee -a "$LOG"

say "5. orchestrator end-to-end task"
# The prompt is deliberately byte-exact: an ambiguous "containing exactly X"
# makes the reviewer FAIL on a trailing newline and the suite reports a
# false alarm. A smoke test must assert an unambiguous requirement.
TASK=$(curl -s -m 20 -X POST "$UI/api/tasks" -H 'Content-Type: application/json' \
  -d '{"prompt":"Create smoke_ok.txt whose content is exactly AI_TEAM_SMOKE_OK with no trailing newline, and check.sh which verifies that byte-exactly (cmp against printf) and exits non-zero on mismatch.","workflow":"auto"}')
TID=$(echo "$TASK" | json "d.get('id','')")
say "  task id: $TID"
for i in $(seq 1 60); do
  sleep 10
  ST=$(curl -s -m 20 "$UI/api/tasks/$TID" | json "d['task']['status']")
  say "  [$((i*10))s] status=$ST"
  [ "$ST" != "running" ] && break
done
curl -s -m 20 "$UI/api/tasks/$TID" | json "'  size=%s workers=%s test=%s review=%s\n  summary=%s'%(d['task'].get('size'),d['task'].get('workers'),(d['task'].get('test') or {}).get('ok'),(d['task'].get('review') or {}).get('verdict'),d['task'].get('summary'))" | tee -a "$LOG"

say "6. artifacts in workspace"
ls -la "$WS" | tee -a "$LOG"
[ -f "$WS/smoke_ok.txt" ] && say "  smoke_ok.txt: $(cat "$WS/smoke_ok.txt")" || say "  smoke_ok.txt: MISSING"

say "7. git state"
curl -s -m 20 "$UI/api/git" | json "'branch=%s dirty=%d'%(d.get('branch'),len([l for l in (d.get('status') or '').splitlines() if l and not l.startswith('##')]))" | tee -a "$LOG"

say "8. SSE feed alive"
timeout 6 curl -s -N "$UI/api/events?replay=5" | head -c 300 | tee -a "$LOG"; echo | tee -a "$LOG"
say "done, full log: $LOG"
