#!/bin/bash
# Downloads the model manifest to the SSD, asking before each file (they're 0.25–13 GB).
# Covers both sets: video (Wan, the Create screen) and image (Qwen, the Image screen). Say N to skip a set.
# Same files the Models screen downloads; use whichever you prefer.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/backend/.venv/bin/python"
[ -x "$PY" ] || { echo "Run scripts/install-studio.sh first."; exit 1; }

# The Python goes in a temp file, not stdin, so input() can read your answers.
TMP="$(mktemp -t wfmodels).py"; trap 'rm -f "$TMP"' EXIT
cat > "$TMP" <<'EOF'
import shutil, sys
from pathlib import Path
from huggingface_hub import hf_hub_download
from wfstudio import config, models

s = config.settings()
if not Path(s["ssd_root"]).exists():
    sys.exit(f"SSD not mounted at {s['ssd_root']}")
st = models.status()
todo = [m for m in st["models"] if m["state"] != "present"]
if not todo:
    print("All model files are already on the SSD."); sys.exit()
print(f"{len(todo)} file(s) to download, {st['missing_gb']} GB total:\n")
for m in todo:
    print(f"  [{m['group']}] {m['filename']}  ({m['size_bytes']/1e9:.1f} GB)  from huggingface.co/{m['repo']}")
print()
for m in todo:
    ans = input(f"Download {m['filename']} ({m['size_bytes']/1e9:.1f} GB)? [y/N] ").strip().lower()
    if ans != "y":
        print("  skipped"); continue
    dest = Path(m["path"]); staging = Path(s["models_dir"]) / ".downloads" / m["id"]
    got = hf_hub_download(repo_id=m["repo"], filename=m["repo_path"], local_dir=str(staging))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(got, dest); shutil.rmtree(staging, ignore_errors=True)
    print(f"  ✓ saved to {dest}")
EOF
cd "$REPO/backend" && PYTHONPATH="$REPO/backend" "$PY" "$TMP"
