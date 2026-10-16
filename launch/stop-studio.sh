#!/bin/bash
# Stop the Studio dashboard and the engine. Renders in progress are lost.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$REPO/logs"
STUDIO_PID="$LOGS/studio.pid"

if [ -f "$STUDIO_PID" ] && kill -0 "$(cat "$STUDIO_PID")" 2>/dev/null; then
  kill "$(cat "$STUDIO_PID")"; echo "Studio stopped."
else
  PIDS="$(/usr/sbin/lsof -ti tcp:8420 -sTCP:LISTEN 2>/dev/null)"
  [ -n "$PIDS" ] && kill $PIDS && echo "Studio stopped."
fi
rm -f "$STUDIO_PID"
"$REPO/launch/engine.sh" stop
