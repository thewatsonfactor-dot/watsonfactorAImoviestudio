#!/bin/bash
# Stop the Studio dashboard and the engine. Renders in progress are lost.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$REPO/logs"
STUDIO_PID="$LOGS/studio.pid"

# Ask nicely, then insist: a backend that ignores TERM for 8 s is killed.
stop_pid() {
  kill "$1" 2>/dev/null || return 0
  for _ in $(seq 1 16); do kill -0 "$1" 2>/dev/null || return 0; sleep 0.5; done
  kill -9 "$1" 2>/dev/null; echo "  (backend $1 didn't exit, killed)"
}

# Every Studio backend from this repo: the pid file, whoever holds the port, and any leftovers
# (older launches whose pid file was overwritten) found by their working directory.
PIDS="$( { [ -f "$STUDIO_PID" ] && cat "$STUDIO_PID"
           /usr/sbin/lsof -ti tcp:8420 -sTCP:LISTEN 2>/dev/null
           for p in $(/usr/bin/pgrep -f -- "-m wfstudio" 2>/dev/null); do
             [ "$(/usr/sbin/lsof -a -p "$p" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')" = "$REPO/backend" ] && echo "$p"
           done; } | sort -u)"
STOPPED=0
for p in $PIDS; do
  kill -0 "$p" 2>/dev/null || continue
  stop_pid "$p"; STOPPED=1
done
[ "$STOPPED" = 1 ] && echo "Studio stopped."
rm -f "$STUDIO_PID"
"$REPO/launch/engine.sh" stop

# Detach the WFStudio disk image, but only if the Studio attached it.
PY="$REPO/backend/.venv/bin/python"
if [ -x "$PY" ]; then
  eval "$(cd "$REPO/backend" && "$PY" -m wfstudio.envdump)"
  . "$REPO/launch/ssd.sh"
  ssd_release
fi
