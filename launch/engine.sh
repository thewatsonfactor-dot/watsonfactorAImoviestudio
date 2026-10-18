#!/bin/bash
# Start / stop / restart / status for the ComfyUI engine, bound to 127.0.0.1.
# Used by start-studio.sh, stop-studio.sh and the Studio's Settings screen.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/backend/.venv/bin/python"
LOGS="$REPO/logs"; mkdir -p "$LOGS"
PIDFILE="$LOGS/comfyui.pid"

if [ ! -x "$PY" ]; then echo "Studio backend not installed — run scripts/install-studio.sh"; exit 1; fi
eval "$(cd "$REPO/backend" && "$PY" -m wfstudio.envdump)"
. "$REPO/launch/ssd.sh"
PORT="${WF_COMFY_URL##*:}"; PORT="${PORT%%/*}"

listening() { /usr/bin/curl -s -m 2 -o /dev/null "$WF_COMFY_URL/system_stats"; }

start() {
  if listening; then echo "Engine already running on $WF_COMFY_URL"; return 0; fi
  ssd_ensure || return 1
  if [ ! -x "$WF_COMFY_DIR/venv/bin/python" ]; then echo "ComfyUI not installed at $WF_COMFY_DIR — run scripts/install-engine.sh"; return 1; fi
  mkdir -p "$WF_OUTPUT_DIR"
  echo "Starting engine: $WF_COMFY_DIR (port $PORT, output $WF_OUTPUT_DIR)"
  cd "$WF_COMFY_DIR" || return 1
  nohup "$WF_COMFY_DIR/venv/bin/python" main.py \
    --listen 127.0.0.1 --port "$PORT" \
    --enable-manager \
    --output-directory "$WF_OUTPUT_DIR" \
    $WF_ENGINE_FLAGS \
    >> "$LOGS/comfyui.log" 2>&1 &
  echo $! > "$PIDFILE"
}

stop() {
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    kill "$(cat "$PIDFILE")"
    for _ in $(seq 1 20); do kill -0 "$(cat "$PIDFILE")" 2>/dev/null || break; sleep 0.5; done
    kill -9 "$(cat "$PIDFILE")" 2>/dev/null
    rm -f "$PIDFILE"; echo "Engine stopped."
  else
    # Engine started some other way (e.g. by hand): find it by port.
    PIDS="$(/usr/sbin/lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null)"
    if [ -n "$PIDS" ]; then
      kill $PIDS
      for _ in $(seq 1 20); do /usr/sbin/lsof -ti tcp:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 || break; sleep 0.5; done
      kill -9 $PIDS 2>/dev/null
      echo "Engine stopped."
    else echo "Engine was not running."; fi
    rm -f "$PIDFILE"
  fi
}

wait_up() {
  for _ in $(seq 1 "${1:-120}"); do listening && return 0; sleep 1; done
  return 1
}

case "${1:-status}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; sleep 1; start ;;
  wait)    wait_up "${2:-120}" ;;
  status)  if listening; then echo "running"; else echo "stopped"; exit 1; fi ;;
  *) echo "usage: engine.sh start|stop|restart|status|wait [seconds]"; exit 2 ;;
esac
