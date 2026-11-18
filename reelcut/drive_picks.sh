#!/bin/bash
# Reels picked from Daniel's footage catalog (Nov 18 2026).
# Only reads the drives; everything is written to ~/Movies/Reels on the Mac.
# Run from the repo:  bash reelcut/drive_picks.sh
set -e
cd "$(dirname "$0")/.."
RC="python3 reelcut/reelcut.py"
OUT="$HOME/Movies/Reels"
mkdir -p "$OUT"
TIPS="/Volumes/WATSON-DEV/CINEMATIC LIGHTING TIPS.mov"

# Lighting series (blur fill keeps the whole room and the lamp in frame).
# Cut points come from the video's captions: tip 1 0:00-0:31, tips 2+3 0:31-1:05, lights off 1:08-1:44.
$RC vertical --input "$TIPS" --start 0  --duration 31 --fit blur \
  --hook "Lighting tip 1: the key light" --end-text "Tip 2 Wednesday" \
  --out "$OUT/lighting_tip1.mp4"
$RC vertical --input "$TIPS" --start 31 --duration 34 --fit blur \
  --hook "Lighting tip 2: rim light + practicals" --end-text "Saturday: watch each light turn off" \
  --out "$OUT/lighting_tip2.mp4"
$RC vertical --input "$TIPS" --start 68 --duration 36 --fit blur \
  --hook "Watch what each light does" --end-text "Follow for more lighting tips" \
  --out "$OUT/lighting_lights_off.mp4"

# Contact sheets for every readable clip on WATSON-DEV, so Claude can pick scenes and cut points.
$RC library "/Volumes/WATSON-DEV" --all-sheets --zip --out "$OUT/library_sheets"

echo
echo "Done. Send Claude these from $OUT:"
echo "  lighting_tip1.mp4  lighting_tip2.mp4  lighting_lights_off.mp4"
echo "  library_sheets/library_upload.zip"
