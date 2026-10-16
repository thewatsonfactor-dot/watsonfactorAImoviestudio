#!/bin/bash
# Builds two double-clickable apps with the Watson Factor icon:
#   launch/Watson Factor AI Studio.app   — starts everything and opens the dashboard
#   launch/Stop AI Studio.app            — stops the dashboard and the engine
# Then copies them to ~/Applications so they can be dragged to the Dock.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO/launch"
MARK="$REPO/frontend/public/brand/wf-mark-tight.png"
WORK="$(mktemp -d)"

[ "$(uname)" = "Darwin" ] || { echo "make-app.sh only runs on macOS"; exit 1; }

# --- icon: the WF mark on its own navy, every size macOS asks for ---
ICONSET="$WORK/AppIcon.iconset"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$MARK" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2)); sips -z $d $d "$MARK" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$WORK/AppIcon.icns"
cp "$ICONSET/icon_32x32.png" "$OUT/icon-preview-32.png"   # eyeball this: does the node cluster still read?

build() {  # name, script
  local app="$OUT/$1.app"
  rm -rf "$app"
  osacompile -o "$app" -e "do shell script \"/bin/bash \" & quoted form of \"$2\" & \" > /dev/null 2>&1 &\""
  cp "$WORK/AppIcon.icns" "$app/Contents/Resources/applet.icns"
  /usr/libexec/PlistBuddy -c "Set :CFBundleName $1" "$app/Contents/Info.plist" 2>/dev/null || true
  touch "$app"
  echo "Built: $app"
}

build "Watson Factor AI Studio" "$REPO/launch/start-studio.sh"
build "Stop AI Studio" "$REPO/launch/stop-studio.sh"

mkdir -p "$HOME/Applications"
rm -rf "$HOME/Applications/Watson Factor AI Studio.app" "$HOME/Applications/Stop AI Studio.app"
cp -R "$OUT/Watson Factor AI Studio.app" "$OUT/Stop AI Studio.app" "$HOME/Applications/"
rm -rf "$WORK"
echo
echo "Done. Both apps are in ~/Applications — drag 'Watson Factor AI Studio' to the Dock."
echo "Check $OUT/icon-preview-32.png: if the node cluster is mush at 32 px, tell Claude to make a simplified small icon."
