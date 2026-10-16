#!/bin/bash
# One-click launch: check the SSD, start the engine, start the Studio, open the dashboard.
# This is what "Watson Factor AI Studio.app" runs.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/backend/.venv/bin/python"
LOGS="$REPO/logs"; mkdir -p "$LOGS"
STUDIO_PID="$LOGS/studio.pid"

dialog() {  # macOS alert; falls back to stderr elsewhere
  /usr/bin/osascript -e "display dialog \"$1\" with title \"Watson Factor AI Studio\" buttons {\"OK\"} default button \"OK\" with icon caution" >/dev/null 2>&1 || echo "$1" >&2
}
notify() {
  /usr/bin/osascript -e "display notification \"$1\" with title \"Watson Factor AI Studio\"" >/dev/null 2>&1 || true
}

if [ ! -x "$PY" ]; then dialog "The Studio isn't installed yet. In Terminal, run: $REPO/scripts/install-studio.sh"; exit 1; fi
eval "$(cd "$REPO/backend" && "$PY" -m wfstudio.envdump)"
STUDIO_URL="http://127.0.0.1:$WF_STUDIO_PORT"

# 1. SSD
if [ ! -d "$WF_SSD_ROOT" ]; then
  dialog "SSD not connected. Plug in $(basename "$WF_SSD_ROOT") and open the Studio again."
  exit 1
fi

# 2. Engine (no-op if it's already up)
if ! "$REPO/launch/engine.sh" status >/dev/null 2>&1; then
  notify "Starting the engine… about 20 seconds."
  "$REPO/launch/engine.sh" start >> "$LOGS/launch.log" 2>&1
fi

# 3. Studio backend
if ! /usr/bin/curl -s -m 2 -o /dev/null "$STUDIO_URL/api/health"; then
  cd "$REPO/backend" || exit 1
  nohup "$PY" -m wfstudio >> "$LOGS/studio.log" 2>&1 &
  echo $! > "$STUDIO_PID"
  for _ in $(seq 1 30); do /usr/bin/curl -s -m 2 -o /dev/null "$STUDIO_URL/api/health" && break; sleep 0.5; done
fi

# 4. Wait for the engine (up to 120s), then open the dashboard either way —
#    the status bar explains anything that's still wrong.
"$REPO/launch/engine.sh" wait 120 || notify "The engine is slow to start — the dashboard will show its status."
/usr/bin/open "$STUDIO_URL" 2>/dev/null || echo "Open $STUDIO_URL"
