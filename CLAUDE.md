# Watson Factor AI Studio — notes for Claude Code

Local, one-click image-to-video studio on Daniel's Mac Studio (M4 Max, 36 GB, macOS 27).
ComfyUI is the engine underneath; this repo is the branded dashboard on top. Daniel never touches a node graph.
Full design: `docs/SPEC.md`. Plain-English usage: `docs/HOW-TO-USE.md`.

## What's already built (and tested against `dev/mock_comfy.py`)
- **Backend** `backend/wfstudio/` — FastAPI on 127.0.0.1:8420. Owns the render queue, hands ComfyUI one job at a time, relays live progress, writes the mp4 + thumbnail + JSON sidecar to `Studio_Output/<project>/`.
- **Dashboard** `frontend/` — React + Vite + Tailwind v4. Create, Renders, Library, Models, Settings. Brand tokens and fonts are copied from thewatsonfactor.dev.
- **Workflow** `studio/templates/wan22_i2v.api.json` + `.map.json` — Wan 2.2 I2V 14B, GGUF loaders, Lightx2v 4-step LoRAs on both passes, 2-pass KSamplerAdvanced, CreateVideo → SaveVideo mp4. Written against ComfyUI 0.41 + ComfyUI-GGUF node definitions. **Not yet run on real hardware.**
- **Launch** `launch/` — `engine.sh`, `start-studio.sh`, `stop-studio.sh`, `make-app.sh` (Dock apps with the WF icon), `ssd.sh` (optional disk-image mount helper).
- **SSD as a disk image:** if the `ssd_image` setting points at a sparsebundle, the launchers run `hdiutil attach -nobrowse` when `ssd_root` isn't mounted, and Stop AI Studio detaches it afterwards, but only if the Studio attached it (marker `logs/ssd-attached-by-studio`). If the drive holding the image is missing, the "SSD not connected" dialog names that drive. Daniel's: `/Volumes/WATSON-DEV/WFStudio.sparsebundle` in `settings.local.json`.
- **Install** `scripts/install-engine.sh` (Phase 0, gated), `scripts/install-studio.sh`, `scripts/download-models.sh`.

## What's left — do this on the Mac, in order, stop at any failed gate
1. **Phase 0:** `scripts/install-engine.sh`. Gate: it prints `True` for MPS. If not, stop and report the exact output.
2. `scripts/install-studio.sh` — builds the backend venv, the dashboard, and the Dock apps.
3. **Models:** `scripts/download-models.sh` or the Models screen. Six files, ~28 GB. Before any file over 1 GB, show Daniel the name, source and size and wait for his OK (the script and the screen both ask).
4. **Phase 1 — prove the workflow on real hardware:**
   - Start the engine (`launch/engine.sh start`), open `http://127.0.0.1:8188`, and load `studio/templates/wan22_i2v.api.json` through ComfyUI's workflow menu.
   - Render once at 832×480, 49 frames. Record the time.
   - If ComfyUI rejects a node or an input name (it changes between versions), fix the template by rebuilding the graph from the built-in Wan 2.2 14B I2V template, then **Export (API)** over `wan22_i2v.api.json` and update the node ids in `wan22_i2v.map.json`. The Studio's Models pill runs the same check against `/object_info` and names the broken node.
   - `SaveVideo` uses `"format": "mp4", "format.codec": "h264"` (a dynamic combo). If validation rejects that, open the node in the UI, pick mp4/h264, and re-export.
5. **Acceptance:** with real models, run the 8 checks in `docs/SPEC.md` → "Acceptance test". `dev/acceptance.py` automates the API-level ones (render, sidecar, re-roll, cancel, queue order).

## Rules
- Everything binds to 127.0.0.1. No telemetry, no cloud calls (Hugging Face downloads only, on request).
- Never edit ComfyUI core files. Customization lives here.
- **No fp8 model files.** MPS can't load Float8. GGUF or fp16 only. `install-engine.sh` scans for them.
- Never redraw the logo. `frontend/public/brand/wf-lockup-studio.png` is the original lockup with only the "MARKETING & AI" line swapped for "AI STUDIO"; `wf-mark-tight.png` is a crop of the original mark.
- When something fails, stop and report the exact error. Don't work around it silently.
- Don't hand-edit `settings.json` for Daniel's paths. The Settings screen writes `studio/config/settings.local.json` (git-ignored).

## Dev loop without a GPU
```bash
python3 -m venv /tmp/wfvenv && /tmp/wfvenv/bin/pip install -r backend/requirements.txt
mkdir -p /tmp/fake-ssd                      # then create the six manifest files (sparse is fine)
WFSTUDIO_SSD_ROOT=/tmp/fake-ssd /tmp/wfvenv/bin/python dev/mock_comfy.py --speed 0.5 &
cd backend && WFSTUDIO_SSD_ROOT=/tmp/fake-ssd /tmp/wfvenv/bin/python -m wfstudio &
cd ../frontend && npm ci && npm run dev     # http://127.0.0.1:5173 (proxies /api to :8420)
/tmp/wfvenv/bin/python ../dev/acceptance.py
```
`mock_comfy.py --fail-at 13` simulates an out-of-memory crash in the first sampler.

## Map of the backend
| File | Does |
|---|---|
| `config.py` | settings.json + settings.local.json + env overrides; presets; manifest |
| `runner.py` | Studio queue → ComfyUI, websocket progress, poller fallback, finalize (move, thumbnail, sidecar) |
| `workflow.py` | inject params via the map; validate the template against the live engine |
| `health.py` | the four status pills and the pre-flight that blocks Generate |
| `models.py` | manifest check + one-at-a-time Hugging Face downloads |
| `system.py` | macOS memory pressure, disk, Finder reveal, Trash, ffmpeg thumbnails |
| `main.py` | HTTP API, media serving, `/api/ws`, serves `frontend/dist` |
