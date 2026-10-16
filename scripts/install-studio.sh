#!/bin/bash
# Installs the Studio itself: backend venv, dashboard build, and the Dock apps.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYV="3.12"
say()  { printf "\n\033[1;36m▸ %s\033[0m\n" "$1"; }
ok()   { printf "  \033[1;32m✓\033[0m %s\n" "$1"; }
fail() { printf "\n\033[1;31m✗ %s\033[0m\n" "$1"; exit 1; }

[ "$(uname)" = "Darwin" ] || fail "This installer is for macOS."
command -v brew >/dev/null || fail "Homebrew is missing — install it from https://brew.sh first."

say "Toolchain (python@$PYV, node, ffmpeg)"
for pkg in "python@$PYV" node ffmpeg; do
  brew list --versions "$pkg" >/dev/null 2>&1 && ok "$pkg" || { brew install "$pkg"; ok "$pkg installed"; }
done
PY="$(brew --prefix "python@$PYV")/bin/python$PYV"

say "Backend"
cd "$REPO/backend"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -c "import wfstudio.main" && ok "backend ready"

say "Dashboard"
cd "$REPO/frontend"
npm ci --no-audit --no-fund --silent
npm run build --silent
[ -f dist/index.html ] && ok "dashboard built"

say "Dock apps"
chmod +x "$REPO/launch/"*.sh "$REPO/scripts/"*.sh
"$REPO/launch/make-app.sh"

say "Studio installed."
echo "  Double-click 'Watson Factor AI Studio' in ~/Applications (drag it to the Dock)."
