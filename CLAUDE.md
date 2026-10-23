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

## Memory findings (Oct 17 2026, 36 GB M4 Max)
Controlled test: same 832x480 keyframe, prompt and seed 12345 (warm run used 12346), Draft, 49 frames, 4 steps. Targets were pressure at most "warning", swap rise under 4 GB, render under 8 min. **Nothing met all three.** Baseline was a clean machine (no Resolve, no Chrome); baseline swap was 2-6 GB because macOS doesn't give swap back after a run.

| Run | Change | Time | Pressure | Swap start to peak (rise) |
|---|---|---|---|---|
| Phase 1 | Q4 unets + Q8 encoder, other apps open | 712.8 s | critical | 22.4 GB used afterwards |
| A cold | clean machine | 732.7 s | warning | 2.5 to 11.1 GB (+8.7) |
| A warm | second render, no restart | 673.5 s | critical (1/335) | 6.2 to 12.9 GB (+6.7) |
| B | A + `--disable-smart-memory` | 776.4 s | critical (2/386) | 2.2 to 11.0 GB (+8.8) |
| B2 job 1 | free after render ON, two-job queue | 721.1 s | critical (2/358) | 3.6 to 13.1 GB (+9.5) |
| B2 job 2 | same queue | 686.6 s | critical (3/340) | 4.6 to 14.7 GB (+10.1) |
| C | A + Q4_K_M text encoder (3.66 GB) | 730.1 s | warning | 3.6 to 8.1 GB (+4.5) |
| D | C + Q3_K_M high/low unets (7.18 GB each) | 680.8 s | warning | 3.0 to 7.4 GB (+4.4) |
| E (Standard) | D config, **81 frames** | 2219.5 s (37 min) | warning (0/1101 critical) | 3.8 to 4.2 GB (+0.4) |

- **The Q8 text encoder is the biggest lever.** Swapping it for Q4_K_M cut the swap rise roughly in half and removed all critical samples. The Q3 video models then bought only about 50 s and 0.7 GB more.
- **`--disable-smart-memory` did not help** (slightly worse). Keep `engine_flags` empty; the setting exists for experiments.
- **`/free` works but doesn't fix it.** After a job it released 7.7 and 10.5 GB of swap, but each render still peaks at 13-15 GB inside the render. So "free after every render" was not built. Settings has a manual **Free memory now** button only.
- **Render time is compute-bound.** Every config lands at 11-13 minutes for 49 frames; quantization changes memory, not speed.
- **Same seed, same frames:** A cold and B produced identical frames. Q4 encoder changed the sun's edge pattern; the Q3 clip looked as clean as Q4. One keyframe only, so quality is a spot check, not a verdict.
- **Standard (81 frames) is memory-safe but slow:** 37 minutes, 3.3x the 49-frame time for 1.65x the frames, with almost no extra swap. We don't know why swap rose less than in D (D's rise may have been paging in memory left over from earlier runs); treat swap deltas as noisy. Plan Standard renders as overnight jobs, and use Draft for blocking.
- **Not tested:** Final (720p), which will be slower and heavier still.
- **Quant selection:** `models.manifest.json` models can list `variants`; pick one with `"quants": {"<model id>": "<quant>"}` in `settings.local.json`. All files stay on the SSD. Daniel's current setting: Q4_K_M encoder, Q3_K_M unets.

## Acceptance (Oct 17 2026, real engine)
`dev/acceptance.py --timeout 1500` passed 11/11 (render, sidecar, re-roll, cancel, engine healthy after cancel, queue reorder/remove) with Draft + Short renders of 655-710 s each; peak swap 12.1 GB, pressure never critical. SPEC check 6 (SSD gone): with the engine stopped and the disk image detached, the SSD pill went red, Generate was disabled with "SSD not connected — plug in WFStudio.", and re-attaching turned it green with no Studio restart. The launcher's auto-mount and Stop-detach were both verified. `POST /api/jobs` and re-roll now also return 409 "SSD not connected — plug in WFStudio." when the SSD is missing (they used to accept the job; only the UI blocked Generate).

## Silent-failure guards (Oct 17 2026)
The first Final (720p, 81 frames) render came back "done" with a blank gray video. Cause: Metal ran out of GPU memory (`kIOGPUCommandBufferCallbackErrorOutOfMemory`, about 2,400 errors across both sampling passes and the VAE decode), ComfyUI printed the errors but finished with status success, and the Studio only checked that a file existed. `backend/wfstudio/guards.py` now fails a job if (1) the engine log shows GPU errors from the job's start offset (`logs/comfyui.log`), or (2) the finished video is flat (every sampled frame spans under 24 luma levels). A rejected render is moved to `Studio_Output/.failed/` (no sidecar, so it never reaches the Library) and the job shows as failed with a plain message. `dev/test_guards.py` checks both guards against the real engine log (all 15 earlier renders clean, the Final flagged) and synthetic clips; it renders nothing. **Not yet verified on a live render** — confirm with one real Draft and one real failing case.

## First real render — Phase 1 cleared (Oct 22 2026)
Loaded `wan22_i2v.api.json` through ComfyUI's workflow menu with the Studio dashboard driving it end to end for the first time on real hardware (prior runs were all `dev/mock_comfy.py`). Square keyframe, Standard quality, 81 frames @ 16fps, 640x640 (not the planned 832x480 landscape — square because of the keyframe, not a setting). **Succeeded cleanly: real mp4, real thumbnail, real sidecar, appeared correctly in the Library.** Render time **34m37s** — far above the Oct 17 Standard baseline (37 min was close, so roughly consistent; the 11-13 min numbers in that section are all Draft/49-frame). The output has no audio: `wan22_i2v.api.json` is image-to-video motion only, nothing in the graph generates or expects audio, so a silent result is correct, not a guard miss.

This also confirms the happy path of the Oct 17 silent-failure guards on a live render: a clean real render was not wrongly flagged. The failing-case path (a live render actually hitting the OOM/blank-frame guard) is still only confirmed against the real engine log replay in `dev/test_guards.py`, not a fresh live OOM — that part of "not yet verified on a live render" still stands.

Separately, the per-size memory forecast (guarding Final/1280x720/81 frames as "as big as or bigger than a render that ran out of GPU memory") fired correctly in the dashboard UI during this session, blocking that combination with the override checkbox rather than a hard wall — first live confirmation of that guard too.

**Open question raised by this render:** the workflow produces silent video only. Adding a voiceover (ElevenLabs TTS + ffmpeg compositing, or a manual DaVinci Resolve pass) is a new scope item, not yet designed.
