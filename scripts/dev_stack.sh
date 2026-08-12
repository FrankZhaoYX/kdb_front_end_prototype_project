#!/usr/bin/env bash
# Start the report console: the kdb+ gateway plus the FastAPI front-end.
#
#   scripts/dev_stack.sh
#
# The front-end is not runnable on its own -- it needs kdb+ to talk to -- so
# this starts the gateway, waits for its port, then runs uvicorn in the
# foreground. uvicorn is deliberately NOT exec'd: the EXIT trap has to survive
# so the gateway is torn down with it rather than orphaned.
#
# Point the app at a kdb+ server you already run instead by setting KDB_HOST
# and KDB_PORT and starting uvicorn yourself (`make app`); this script exists
# for the local case where there is nothing listening yet.
#
# Used by .claude/launch.json. Overridable: KDB_PORT, APP_PORT, APP_HOST.
#
# APP_HOST defaults to loopback. Set APP_HOST=0.0.0.0 to reach the console from
# another machine on the LAN -- but read the warning it prints first: there is
# no authentication in front of this. The kdb+ gateway is deliberately NOT
# exposed; it always stays on 127.0.0.1.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

KDB_PORT="${KDB_PORT:-5000}"
APP_PORT="${APP_PORT:-8000}"
APP_HOST="${APP_HOST:-127.0.0.1}"
PY="$ROOT/.venv/bin/python"
export KDB_HTML2PDF="${KDB_HTML2PDF:-$ROOT/scripts/html2pdf.sh}"

die() { echo "dev_stack: $*" >&2; exit 1; }

[ -x "$PY" ] || die "no virtualenv at .venv -- run 'make setup' first"
[ -f data/nsdq_daily.csv ] || \
  die "dataset missing (data/nsdq_daily.csv) -- run 'make data' first"

echo "dev_stack: kdb=127.0.0.1:$KDB_PORT  app=$APP_HOST:$APP_PORT"

if [ "$APP_HOST" != "127.0.0.1" ] && [ "$APP_HOST" != "localhost" ]; then
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo '<this-host>')"
  cat >&2 <<WARN

  *** the report console will be reachable from your network ***
  http://$LAN_IP:$APP_PORT

  There is NO authentication in front of it. Anyone who can reach this host
  can run every report and download the PDFs it generates. Fine on a trusted
  network for a prototype; put nginx with TLS and auth in front of anything
  else. The kdb+ gateway stays on 127.0.0.1 and is not exposed.

WARN
fi

"$PY" scripts/serve_q.py -p "$KDB_PORT" &
KDB_PID=$!

cleanup() {
  if kill -0 "$KDB_PID" 2>/dev/null; then
    echo "dev_stack: stopping the kdb+ gateway ($KDB_PID)"
    kill "$KDB_PID" 2>/dev/null || true
    wait "$KDB_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Loading the dataset into kdb+ takes a couple of seconds; wait for the port
# rather than guessing at a sleep.
for _ in $(seq 1 120); do
  if nc -z 127.0.0.1 "$KDB_PORT" 2>/dev/null; then
    echo "dev_stack: kdb+ gateway is up"
    break
  fi
  kill -0 "$KDB_PID" 2>/dev/null || die "the gateway exited before opening a port"
  sleep 0.5
done
nc -z 127.0.0.1 "$KDB_PORT" 2>/dev/null || die "gateway did not open $KDB_PORT in time"

KDB_PORT="$KDB_PORT" "$PY" -m uvicorn app.main:app \
  --host "$APP_HOST" --port "$APP_PORT" \
  --reload --reload-dir app
