# Watson Factor AI Studio — Build Spec for Claude Code

> **Status (Oct 16 2026):** Phases 2 and 3 are built in this repo, and the Phase 1 workflow is pre-built at `studio/templates/wan22_i2v.api.json`. The Lightx2v LoRA is two files (high + low noise), so the manifest has six files (~28 GB). The installers use Python 3.12 (ComfyUI recommends 3.12+). See `CLAUDE.md` for what's left to do on the Mac.

**What this is:** a local, branded, one-click video studio on Daniel's Mac Studio.
**How it works:** ComfyUI is the engine underneath. Watson Factor AI Studio is the dashboard on top. Daniel never has to touch a node graph.

**Machine:** Mac Studio 2025, Apple M4 Max (14-core CPU / 32-core GPU), 36 GB unified memory, macOS 27.0.1, 261 GB free internal. Models live on an external Thunderbolt NVMe SSD.

**Rules for Claude Code**
- Build in the phase order below. **Do not start a phase until the previous phase's gate passes.**
- Bind every server to `127.0.0.1` only. Nothing is exposed to the network.
- Never edit ComfyUI core files. All customization lives in the Studio app.
- **No fp8 model files anywhere.** MPS cannot load Float8. GGUF or fp16 only.
- Before any download over 1 GB, print the filename, source URL and size, and wait for Daniel's OK.
- When something fails, stop and report the exact error. Don't work around it silently.

---

## PHASE 0 — Engine install (ComfyUI)

```bash
# 1. Clone
git clone https://github.com/Comfy-Org/ComfyUI.git ~/ComfyUI
cd ~/ComfyUI
python3.11 -m venv venv
source venv/bin/activate

# 2. Stable PyTorch (NOT nightly)
pip install torch torchvision torchaudio
pip install -r requirements.txt
pip install -r manager_requirements.txt

# 3. GATE — must print True
python -c "import torch; print(torch.__version__, torch.backends.mps.is_available())"

# 4. GGUF loader
cd custom_nodes
git clone https://github.com/city96/ComfyUI-GGUF.git
pip install -r ComfyUI-GGUF/requirements.txt
cd ..

# 5. Downloads tool
pip install -U "huggingface_hub[cli]"
```

**Install location:** `~/ComfyUI`. It must NOT sit inside Desktop or Documents, because iCloud is full and those folders may sync.

### External SSD layout

The volume name has no spaces; use `WFStudio`. Format it APFS.

```
/Volumes/WFStudio/
  ComfyUI_Models/
    diffusion_models/
    text_encoders/
    vae/
    loras/
  Studio_Output/        ← every render lands here
  Studio_Inputs/        ← uploaded keyframes are copied here
```

### `~/ComfyUI/extra_model_paths.yaml`

```yaml
wf_studio:
  base_path: /Volumes/WFStudio/ComfyUI_Models/
  diffusion_models: diffusion_models/
  unet: diffusion_models/
  text_encoders: text_encoders/
  clip: text_encoders/
  vae: vae/
  loras: loras/
```

### Model manifest (v1)

Verify the exact filenames on Hugging Face before downloading. Show Daniel the list with sizes first.

| Folder | File | Source |
|---|---|---|
| diffusion_models | Wan 2.2 I2V A14B **HighNoise** Q4_K_M `.gguf` | QuantStack/Wan2.2-I2V-A14B-GGUF |
| diffusion_models | Wan 2.2 I2V A14B **LowNoise** Q4_K_M `.gguf` | QuantStack/Wan2.2-I2V-A14B-GGUF |
| text_encoders | umt5-xxl-encoder **Q8_0** `.gguf` | city96/umt5-xxl-encoder-gguf |
| vae | `wan_2.1_vae.safetensors` | Comfy-Org Wan repackaged |
| loras | Lightx2v **I2V** 4-step LoRA — **high-noise** | Comfy-Org/Wan_2.2_ComfyUI_Repackaged |
| loras | Lightx2v **I2V** 4-step LoRA — **low-noise** | Comfy-Org/Wan_2.2_ComfyUI_Repackaged |

Save this list as `studio/config/models.manifest.json`. The dashboard's Models screen reads it.

**Phase 0 gate:** ComfyUI launches with `python main.py --listen 127.0.0.1 --enable-manager --output-directory /Volumes/WFStudio/Studio_Output`, and all six files show up in the loader dropdowns.

---

## PHASE 1 — Prove the workflow by hand (no dashboard yet)

The dashboard is only as good as the workflow it drives. Build and validate the workflow in the ComfyUI UI first.

1. Open the built-in **Wan 2.2 14B Image to Video** template.
2. Swap the model loaders to **Unet Loader (GGUF)**, one for high-noise and one for low-noise.
3. Swap the text encoder loader to **CLIPLoader (GGUF)** with the umt5 Q8 file.
4. Add the **Lightx2v LoRA** to both the high-noise and low-noise chains.
5. Set the output to **mp4 (h264)**.
6. Render a 480p, 81-frame test from any still.
7. Save it as `wan22_i2v_mac` in the UI, then use **Export (API)** to save `studio/templates/wan22_i2v.api.json`.
8. Write `studio/templates/wan22_i2v.map.json`. It maps friendly parameter names to `[node_id, input_name]` in the API JSON:

```json
{
  "image":          ["<LoadImage node id>", "image"],
  "positive":       ["<positive CLIPTextEncode id>", "text"],
  "negative":       ["<negative CLIPTextEncode id>", "text"],
  "width":          ["<WanImageToVideo id>", "width"],
  "height":         ["<WanImageToVideo id>", "height"],
  "length":         ["<WanImageToVideo id>", "length"],
  "seed":           ["<high-noise KSamplerAdvanced id>", "noise_seed"],
  "steps_high":     ["<high-noise KSamplerAdvanced id>", "steps"],
  "steps_low":      ["<low-noise KSamplerAdvanced id>", "steps"],
  "filename_prefix":["<SaveVideo id>", "filename_prefix"]
}
```

Fill in the real node IDs from the export. If the template's node names differ, map whatever controls the same thing.

**Phase 1 gate:** one clean mp4 rendered from the UI. Record the actual render time; it becomes the baseline ETA.

---

## PHASE 2 — Watson Factor AI Studio (the dashboard)

### Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | React + Vite + TypeScript + Tailwind | Fast, familiar, builds to static files |
| Backend | Python **FastAPI** (its own venv in `~/WatsonFactorAIStudio/backend`) | Python is already on the machine; handles filesystem, disk checks, and the ComfyUI proxy |
| Data | SQLite (`studio.db`), plus a JSON sidecar next to every render | The library survives losing the database |
| Engine | ComfyUI at `127.0.0.1:8188` | Untouched |
| Studio URL | `http://127.0.0.1:8420` | FastAPI serves the built frontend and the API |

### Project layout

```
~/WatsonFactorAIStudio/
  backend/            FastAPI app, comfy client, job runner
  frontend/           React app
  studio/
    config/           settings.json, models.manifest.json
    templates/        *.api.json + *.map.json (one pair per workflow)
  launch/
    start-studio.sh
    stop-studio.sh
    Watson Factor AI Studio.app
  studio.db
```

### Backend API

| Method | Route | Does |
|---|---|---|
| GET | `/api/health` | ComfyUI up? MPS ok? SSD mounted? Free space on internal + SSD, memory pressure (`memory_pressure` / psutil). Feeds the status bar. |
| GET | `/api/models` | Compares the manifest against the files on the SSD: present / missing / size. |
| POST | `/api/upload` | Copies the keyframe to `Studio_Inputs/`, forwards it to ComfyUI `/upload/image`, returns the dimensions. |
| POST | `/api/jobs` | Loads template + map, injects params, POSTs ComfyUI `/prompt` with a fixed `client_id`, writes the job row. |
| GET | `/api/jobs`, `/api/jobs/{id}` | Queue and history. |
| POST | `/api/jobs/{id}/cancel` | Running → ComfyUI `/interrupt`; queued → ComfyUI `/queue` delete. |
| WS | `/api/ws` | Relays the ComfyUI `/ws` events (`execution_start`, `executing`, `progress`, `executed`, `execution_error`) as clean events: `{job_id, stage, step, total_steps, percent, eta_seconds}`. |
| GET | `/api/library` | Every render with its metadata; filter by project, tag, favorite. |
| POST | `/api/library/{id}/favorite`, `/tag`, `/delete` | Library actions. Delete moves the file to the macOS Trash, never a hard delete. |
| POST | `/api/library/{id}/reveal` | `open -R <file>`, which shows the file in Finder. |
| GET | `/media/...` | Serves the mp4s and thumbnails from `Studio_Output/`. |

**On job completion:** save the mp4 as `Studio_Output/<project>/<YYYY-MM-DD>_<shortid>.mp4`. Write `<same>.json` next to it with the prompt, negative, seed, preset, input image path, render seconds, and model filenames. Generate a poster-frame thumbnail with ffmpeg; install it with `brew install ffmpeg` if missing.

### Screens

**Design language — match thewatsonfactor.dev exactly.** The Studio should feel like the same brand as the live site. Pull the real tokens (colors, fonts, gradients, radii) from the site's own source/CSS. Do not eyeball them. If the source isn't available, sample the live page at https://thewatsonfactor.dev.

What the site does, to replicate:
- **Background:** deep navy (`#070B16` family), with a faint glow bleeding in from the top-left corner.
- **Signature gradient:** cyan → violet → pink → coral, running left to right. It's used on the hero headline words, the primary CTA button fill, the active tab pill, and a thin rule under the top nav. In the Studio, use it for the **Generate button**, the **active sidebar item**, the **progress bar**, and a hairline under the top bar. Use it sparingly; everything else stays navy and white.
- **Display type:** heavy condensed uppercase headline font, the same one the site uses for "APP DEVELOPMENT." Use it for screen titles ("CREATE", "RENDERS", "LIBRARY") and big stat numbers.
- **Eyebrow labels:** small, widely letter-spaced uppercase **monospace** in cyan (like "FOR BUSINESSES IN SAN ANTONIO & NEW BRAUNFELS"). Use them for section labels ("MOTION PROMPT", "QUALITY", "PROJECT").
- **Body text:** the site's clean sans-serif, light gray-white on navy.
- **Stat cards:** the site's bordered navy cards with a gradient number on top and a gray caption below. Use them for the status bar and the Home stats (renders today, avg render time, SSD free).
- **Buttons:** the primary is a gradient fill with dark text. The secondary is a navy fill with a thin light border (like the site's "Call or text" button).
- **Logo:** Daniel supplies two files. Put them in `frontend/public/brand/` as `wf-lockup.png` (the horizontal mark + wordmark) and `wf-mark.png` (the square mark only, on navy). Use them as-is. `wf-mark.png` is the source for the app icon, the favicon and the collapsed sidebar. **Never redraw or re-trace the mark.**
  - **The mark:** a neon line-art "W" built from parallel outlines. An "F" is formed by a circuit trace that rises out of the right side of the W and ends in an arrow pointing up-right. A neural-network node cluster sits over the top-left of the W. The gradient runs blue → violet → magenta → orange.
  - **The wordmark:** "THE" small in white, "WATSON" in white in a bold wide geometric sans, "FACTOR" in the blue-violet-pink-orange gradient with a stylized R, then the subline "MARKETING & AI" in widely letter-spaced light blue-gray.
  - **Studio lockup:** the same mark + "THE WATSON FACTOR". Replace the subline "MARKETING & AI" with "**AI STUDIO**" in the same letter-spaced style. Use the gradient on "AI STUDIO" only if it stays readable at sidebar size.
  - **Sidebar:** the full lockup when expanded; the mark alone when collapsed.
  - **Background match:** if the logo file has a baked-in navy background (not transparent), set the sidebar/header background to that exact sampled navy so the edge never shows. Better still, request a transparent PNG or SVG from Daniel.
  - **App icon:** the mark alone, centered on deep navy, exported at 1024 px down to 16 px. Check that the node cluster still reads at 32 px; if it turns to mush, drop the icon to the W + arrow only and show Daniel before shipping.

Layout rules: generous spacing, large type, plain-English labels, no ComfyUI vocabulary on main screens, persistent left sidebar.

**Persistent status bar (top):** four pills, green/amber/red, each with a one-line reason on hover: Engine (ComfyUI), Models, SSD, Memory. When any pill is red, the Generate button is disabled and shows the plain reason, e.g. "SSD not connected — plug in WFStudio."

**1. Create (home screen)**
- **Big drop zone:** "Drop your keyframe." Shows a preview, and the aspect ratio is detected automatically (landscape / portrait / square).
- **Motion prompt** box with a live **token counter**.
  - ⚠️ Wan's text encoder reads about **512 tokens** max; anything past that is ignored. Show amber at 400 and red over 512 with: "Wan ignores everything past here — trim it." Long Seedance-style prompts won't transfer as-is.
- **Project** dropdown (create new inline). Example: "Farola Run".
- **Length:** Short (~3s) · Standard (~5s). Wan 2.2 14B renders 16 fps, so these map to 49 and 81 frames.
- **Quality:** Draft · Standard · Final (presets below).
- **Seed:** a "Random" toggle by default. "Lock" keeps the seed. "Re-roll" from the Library reuses everything but the seed.
- **Advanced** drawer, collapsed by default: negative prompt, steps (high/low), exact width/height (snapped to multiples of 16), seed value.
- **Generate** button with an ETA ("about 6 min") taken from the measured average for that preset. Show "first run — no estimate yet" until a baseline exists.

**2. Renders**
- The live job: input thumbnail, prompt snippet, stage ("Loading models" → "Sampling 3/8" → "Decoding" → "Saving"), a progress bar, elapsed and remaining time, and a Cancel button.
- Below it, the queue in order. Jobs can be reordered or removed before they start.
- Failed jobs show the error in plain English plus the raw error behind a "Details" toggle.

**3. Library**
- A grid of poster frames. Videos play on hover; click opens a large player.
- Filters: project, favorites, date, preset.
- Per item: Favorite · Re-roll (new seed) · Remix (opens Create pre-filled) · Copy prompt · Show in Finder · Delete (to Trash).

**4. Models**
- Manifest checklist: ✅ present / ❌ missing, with size and location.
- Total disk used on the SSD and free space on both drives.
- Missing files show the exact Hugging Face source plus a "Download" button that runs `hf download` into the right folder, with progress. Requires confirmation per file.

**5. Settings**
- SSD path, output folder, ComfyUI URL, default project, default preset.
- "Restart engine" button.
- Read-only system info: chip, memory, macOS, torch version, MPS status.

### Presets (`studio/config/presets.json` — editable, not hard-coded)

| Preset | Resolution | Frames | Steps (Lightx2v) | Notes |
|---|---|---|---|---|
| Draft | 480p (832×480 / 480×832 / 640×640) | 49 | 4 total | Blocking and motion tests |
| Standard | 480p | 81 | 4 total | Default |
| Final | 720p (1280×720 / 720×1280) | 81 | 6 total | Label it **Experimental** — memory-heavy on 36 GB; may fail or swap |

The app records actual render seconds per preset and shows the rolling average as the ETA.

### Guardrails
- One render at a time. ComfyUI serializes jobs; the UI says "Queued — 2 ahead."
- Pre-flight on Generate: engine up, SSD mounted, all models present, at least 20 GB free on the SSD. If any check fails, block the render with the reason.
- If memory pressure is high when a job is submitted, show the warning "Close Chrome tabs / other apps before rendering" but still allow the render.
- No telemetry, no cloud calls. Fully local.

---

## PHASE 3 — One-click launch

**`launch/start-studio.sh`**
1. Check that `/Volumes/WFStudio` is mounted. If it isn't, show a macOS dialog (`osascript`) and exit.
2. If nothing is listening on `127.0.0.1:8188`, start ComfyUI in the background:
   `cd ~/ComfyUI && source venv/bin/activate && python main.py --listen 127.0.0.1 --enable-manager --output-directory /Volumes/WFStudio/Studio_Output`
   Log to `~/WatsonFactorAIStudio/logs/comfyui.log`.
3. Wait for ComfyUI's `/system_stats` to respond, with a 120-second timeout.
4. Start the Studio backend on `127.0.0.1:8420` and log it.
5. Open `http://127.0.0.1:8420` in the default browser.

**`launch/stop-studio.sh`** stops both processes cleanly by PID file.

**`Watson Factor AI Studio.app`**: wrap `start-studio.sh` as a double-clickable app (AppleScript applet via `osacompile`, or a minimal app bundle) with an app icon built from the site's "WF" logo mark on deep navy. Daniel drags it to the Dock.

---

## Acceptance test (Claude Code runs this before calling it done)

1. Quit everything, then double-click the app. The dashboard opens and all four status pills are green.
2. Drop a still, type a short prompt, and pick Draft + Short. Generate. Live progress shows every stage, and the mp4 plays in Renders, then appears in Library under the chosen project.
3. The sidecar `.json` exists next to the mp4 with correct metadata.
4. Re-roll from the Library produces a new render with a different seed and the same everything else.
5. Cancel mid-render stops it within a few seconds, and the engine stays healthy for the next job.
6. Unplug the SSD: the SSD pill turns red and Generate is disabled with a plain message. Plug it back in and it recovers without a restart.
7. Paste a 700-token prompt: the counter goes red with the truncation warning.
8. Hand Daniel a 5-line "how to use it" note.

---

## Out of scope for v1 (v2 backlog)
- Text-to-video and Wan 2.2 5B fast mode
- Flux / local keyframe generation (Nano Banana Pro covers keyframes today)
- Frame interpolation to 24/30 fps (RIFE) and upscaling
- Prompt helper that condenses long Seedance prompts into Wan-length motion prompts
- LoRA library and character LoRA training
- Batch mode: one prompt across many stills, or many seeds of one still
