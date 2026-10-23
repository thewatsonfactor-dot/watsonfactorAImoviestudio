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

## 20-second "Long" chain, mock-validated (Oct 23 2026)
Added a 4th length, "Long" (`extended` in presets.json, ~20s), built as four Standard-size (same proven size, same forecast bucket — no new memory risk) segments chained end to end rather than one bigger render: native frame-count increase hits a superlinear time wall (the Oct 17 data shows 1.65x frames costing 3.3x time), where chaining instead compounds render time roughly linearly. `WanImageToVideo`'s own `end_image` input isn't used for this — each segment is a full resubmission of the same template with a new `image` keyframe. A finished segment's last frame (ffmpeg, seeking 0.3s before EOF — asking for the exact last frame can return nothing) becomes the next segment's keyframe; `free_engine_memory()` runs between segments given the Oct 17 finding that macOS doesn't release swap between renders. Segments stay visible in the Library individually until the whole chain combines (ffmpeg stream-copy concat, same codec/res/fps every segment so no re-encode) into one clip with a summed sidecar — a broken chain mid-way never hides or loses a real finished clip. Not offered with Final yet (`POST /api/jobs` returns 409); untested combination of four 720p renders back to back.

Validated end to end against `dev/mock_comfy.py` (not yet on real hardware — a real "Long" render costs Daniel roughly four Standard renders, ~2+ hours, so this is deliberately mock-first): queued a Standard+Long job, watched all 4 segments auto-chain and land in the Library individually (frames/render_seconds visible per segment), confirmed the combine fired after segment 4 (frames=324, render_seconds=16.0, both exact sums; output file size ≈ sum of the 4 segment files, confirming a real concat and not a stub), confirmed the 4 segments then flipped to `hidden=1` in the database while the combined row stayed visible, confirmed Final+Long returns the 409 above, and confirmed re-rolling a combined clip regenerates a fresh `chain_id`/`chain_index`/`chain_total` rather than reusing the old chain (an earlier draft of `reroll()` didn't do this and would have silently produced one plain segment with no continuation). One incidental finding: `free_engine_memory()` logs a caught warning on every segment boundary against the mock, because `dev/mock_comfy.py` has no `/free` route — harmless against the mock (the call is try/except'd exactly for this), but worth knowing before reading mock-run logs.

**Not yet run on real hardware.** When ready: one "Long" render at Standard, expect roughly 4x a Standard render's time (~2+ hours per the Oct 22 real 34m37s baseline), watch Activity Monitor/swap across the segment boundaries the way the Oct 17 session did, and confirm the Library shows one clean combined entry with the segments correctly hidden — exactly what the mock run showed, just on the real engine.

## Image screen — local image generation, mock-validated (Oct 23 2026)
Hosted generators (Gemini etc.) filter what Daniel's films need, so keyframes are now made locally: a new **Image** screen (`frontend/src/pages/Image.tsx`) runs **Qwen-Image-Edit-2511** through `studio/templates/qwen_image_edit.api.json` + `.map.json`, rebuilt from ComfyUI 0.41's own `image_qwen_image_edit_2511` template (4-step Lightning path: UnetLoaderGGUF → ModelSamplingAuraFlow 3.1 → CFGNorm → Lightning LoRA → KSampler euler/simple, 4 steps, CFG 1; TextEncodeQwenImageEditPlus + FluxKontextMultiReferenceLatentMethod `index_timestep_zero` on both conditionings; EmptySD3LatentImage canvas). No content filter exists anywhere in this path and none should be added; what Daniel must not do is use real people's likenesses without written consent or depict anyone who reads as under 18 — that's a rule for how we build and help, not a setting.
- **Up to 3 reference photos** (Picture 1–3), all optional. `workflow.build` removes unused `references` slots (their LoadImage node and the encoder inputs it fed) so no wire points at nothing. Zero references = text-to-image.
- **Sizes** (`presets.json` → `image`): landscape 1664×960 / portrait 960×1664 are exactly 2× the Standard video size so a still animates without stretching; square 1328. The UI defaults to landscape and does *not* follow Picture 1 (character photos are usually portrait).
- **Models** (5 files, ≈20.4 GB, `group: "image"` in the manifest): `qwen-image-edit-2511-Q4_K_M.gguf` (unsloth, 13.2 GB; Q3_K_M variant 9.9 GB), `Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf` (unsloth, 4.7 GB; Q3_K_M variant), `mmproj-BF16.gguf` **saved as `Qwen2.5-VL-7B-Instruct-mmproj-BF16.gguf`**, `qwen_image_vae.safetensors` (Comfy-Org/Qwen-Image — the old `Qwen-Image_ComfyUI` repo name redirects), Lightning 4-step bf16 LoRA (0.85 GB). **No fp8:** ComfyUI's docs use `qwen_2.5_vl_7b_fp8_scaled.safetensors`; the GGUF encoder replaces it. **The mmproj rename matters:** ComfyUI-GGUF's `gguf_mmproj_loader` only picks an mmproj whose filename contains the text encoder's stem minus its quant suffix; under its Hugging Face name, reference photos would be silently ignored.
- **Groups gate their own screen.** The Models pill covers video models only; `health.check()` returns a separate `image` block (ready/reason/workflow_problems) validated against the live engine. `POST /api/images` returns 409 until the image models exist, so an image job can never sit at the head of the queue blocking video. Dispatch picks the blocker by the head job's kind.
- **Same queue, one model family at a time.** Image and video jobs share the single-job queue; when the next job's family differs from the last, the runner calls `free_engine_memory()` first so Wan (~20 GB) and Qwen (~19 GB) never sit in 36 GB together.
- **Same guarantees as video:** engine-log GPU-error scan + a flat-image check (`guards.image_problems`, same 24-luma threshold) quarantine bad output to `.failed/`; PNG + JPEG thumb + JSON sidecar (`kind: "image"`, `references`) in `Studio_Output/<project>/`; Library rescan recovers them. Image jobs are excluded from the memory forecast and from the Create screen's average render time. DB gained `kind` and `refs` columns (additive migration).
- **Library:** Videos/Images filter; image tiles open a still; **Animate** (`POST /api/library/{id}/to-keyframe` copies the PNG into `Studio_Inputs/` — a copy, so deleting the still never breaks the video) and **Use as reference**. Re-roll keeps references and shape. `dev/mock_comfy.py` now handles the image nodes (real PNG output, rejects dangling wires like the real engine) and has a `/free` route, which also silences the chain-boundary warning noted above.

Validated against the mock: 24/24 API checks (refusal before models, text-only / 2-ref / 3-ref renders, unused-slot removal, 4-ref rejection, Library filter, re-roll, still → keyframe → video, memory freed on family switch, blank-image guard, rescan, forecast exclusion), plus `tsc` and `vite build` clean and browser screenshots of Image, Library and Models. **Not yet run on real hardware** — the models aren't downloaded. Unverified on Metal: Qwen-Image speed and peak memory at 1664×960 on 36 GB, and the BF16 mmproj under MPS. First real test: one text-only landscape image, then one with two references, watching memory the way the Oct 17 session did; if memory is tight, switch `qwen_unet` to Q3_K_M via `quants`. Expect limited skill at graphic gore and nudity even with no filter — the base training data has little of either.

## Shot recipe dropdowns (Oct 23 2026)
Create and Image each get a **Shot recipe** panel (`frontend/src/components/PromptBuilder.tsx`): one dropdown per category, each pick appended to the typed prompt as a sentence in category order (`composePrompt` in `lib/api.ts`); a "Wan reads" / "Qwen reads" line shows the exact text submitted, and the token count covers it. Blocks live in `studio/config/prompt_library.json` — video: Camera move (46 moves in 7 groups, names and grouping from aicameramovements.com, descriptions our own and written as on-screen description, since the site states no license and Wan follows description better than instructions), Pace, Camera feel, Atmosphere; image: Shot size, Camera angle, Lens, Lighting, Film look. **Add your own** saves Daniel's blocks to `studio/config/prompt_library.local.json` (git-ignored) via `POST/DELETE /api/prompt-library/blocks`; only custom blocks can be deleted. The submitted prompt is the composed text, so Re-roll and Remix keep the recipe without storing picks.
