#!/bin/bash
# PHASE 0 — install the ComfyUI engine on this Mac, with gates.
# Safe to re-run: every step checks before it acts. Stops on the first failure.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
COMFY="${WFSTUDIO_COMFY_DIR:-$HOME/ComfyUI}"
SSD="${WFSTUDIO_SSD_ROOT:-/Volumes/WFStudio}"
PYV="3.12"

say()  { printf "\n\033[1;36m▸ %s\033[0m\n" "$1"; }
ok()   { printf "  \033[1;32m✓\033[0m %s\n" "$1"; }
fail() { printf "\n\033[1;31m✗ %s\033[0m\n" "$1"; exit 1; }

say "Checking this Mac"
[ "$(uname)" = "Darwin" ] || fail "This installer is for macOS."
[ "$(uname -m)" = "arm64" ] || fail "Apple Silicon (arm64) required."
ok "macOS $(sw_vers -productVersion) on $(sysctl -n machdep.cpu.brand_string)"
case "$COMFY" in
  "$HOME/Desktop"*|"$HOME/Documents"*) fail "Install outside Desktop/Documents — iCloud may sync them. Use ~/ComfyUI.";;
esac

say "Homebrew packages (python@$PYV, git, ffmpeg)"
command -v brew >/dev/null || fail "Homebrew is missing. Install it from https://brew.sh, then re-run this script."
for pkg in "python@$PYV" git ffmpeg; do
  if brew list --versions "$pkg" >/dev/null 2>&1; then ok "$pkg already installed"; else brew install "$pkg"; ok "$pkg installed"; fi
done
PY="$(brew --prefix "python@$PYV")/bin/python$PYV"
[ -x "$PY" ] || fail "python$PYV not found at $PY"

say "ComfyUI → $COMFY"
if [ -d "$COMFY/.git" ]; then ok "already cloned ($(git -C "$COMFY" log -1 --format=%cd --date=short))"
else git clone https://github.com/Comfy-Org/ComfyUI.git "$COMFY"; ok "cloned"; fi
cd "$COMFY"
[ -x venv/bin/python ] || "$PY" -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
python -m pip install -q --upgrade pip

say "PyTorch (stable — not nightly)"
pip install -q torch torchvision torchaudio
pip install -q -r requirements.txt
[ -f manager_requirements.txt ] && pip install -q -r manager_requirements.txt
ok "dependencies installed"

say "GATE — Apple Metal (MPS) check"
RESULT="$(python -c 'import torch; print(torch.__version__, torch.backends.mps.is_available())')"
echo "  torch $RESULT"
case "$RESULT" in
  *True) ok "Metal is available";;
  *) fail "MPS is NOT available. Stop here and send this output to Claude: $RESULT";;
esac

say "ComfyUI-GGUF loader"
if [ -d custom_nodes/ComfyUI-GGUF/.git ]; then ok "already installed"
else git clone https://github.com/city96/ComfyUI-GGUF.git custom_nodes/ComfyUI-GGUF; fi
pip install -q -r custom_nodes/ComfyUI-GGUF/requirements.txt
ok "GGUF loader ready"

say "External SSD → $SSD"
if [ ! -d "$SSD" ]; then
  fail "SSD not mounted at $SSD. Format it APFS, name it WFStudio (no spaces), plug it in, re-run."
fi
DISKFMT="$(diskutil info "$SSD" 2>/dev/null | awk -F: '/Type \(Bundle\)/{gsub(/ /,"",$2); print $2}')"
[ "$DISKFMT" = "apfs" ] && ok "APFS" || echo "  ! File system is '$DISKFMT' — APFS is recommended."
mkdir -p "$SSD/ComfyUI_Models/"{diffusion_models,text_encoders,vae,loras} "$SSD/Studio_Output" "$SSD/Studio_Inputs"
ok "folders ready"

say "extra_model_paths.yaml (points the engine at the SSD)"
YAML="$COMFY/extra_model_paths.yaml"
[ -f "$YAML" ] && cp "$YAML" "$YAML.bak.$(date +%s)" && ok "backed up the existing file"
cat > "$YAML" <<EOF
wf_studio:
  base_path: $SSD/ComfyUI_Models/
  diffusion_models: diffusion_models/
  unet: diffusion_models/
  text_encoders: text_encoders/
  clip: text_encoders/
  vae: vae/
  loras: loras/
EOF
ok "written"

say "Scan for fp8 files (Metal can't load them)"
FP8="$(find "$SSD/ComfyUI_Models" "$COMFY/models" -iname '*fp8*' 2>/dev/null || true)"
if [ -n "$FP8" ]; then echo "  ! Remove these — they will crash on this Mac:"; echo "$FP8" | sed 's/^/    /'; else ok "none found"; fi

deactivate
say "Engine installed."
echo "  Next: scripts/install-studio.sh, then download the 6 model files (~28 GB) from the Models screen"
echo "  or with scripts/download-models.sh."
