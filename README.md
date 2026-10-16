<p align="center"><img src="frontend/public/brand/wf-lockup-studio.png" alt="The Watson Factor — AI Studio" width="420"></p>

# Watson Factor AI Studio

**A local, one-click image-to-video studio for Mac.** You drop in a keyframe, describe the motion, and get back an mp4. Everything runs on the Mac Studio, and nothing leaves the machine.

Under the hood, [ComfyUI](https://github.com/Comfy-Org/ComfyUI) runs **Wan 2.2 I2V 14B** (GGUF Q4_K_M) with the **Lightx2v 4-step** speed LoRAs on Apple Metal. The Studio is the dashboard on top of it: a render queue, live progress, a project-sorted library, model management and health checks, all in the thewatsonfactor.dev brand.

| | |
|---|---|
| **Machine** | Mac Studio M4 Max, 36 GB, macOS 27 |
| **Models** | 6 files, about 28 GB, on an external APFS SSD named `WFStudio` |
| **Output** | 480p (720p experimental), 49 or 81 frames at 16 fps, h264 mp4 |
| **Addresses** | Dashboard at `127.0.0.1:8420`, engine at `127.0.0.1:8188`; both local only |

## Install (once)

```bash
git clone https://github.com/thewatsonfactor-dot/watsonfactoraimoviestudio ~/WatsonFactorAIStudio
cd ~/WatsonFactorAIStudio
scripts/install-engine.sh      # ComfyUI + Metal check + GGUF loader + SSD folders
scripts/install-studio.sh      # dashboard + Dock apps
scripts/download-models.sh     # ~28 GB, asks before each file (or use the Models screen)
```

Then drag **Watson Factor AI Studio** from `~/Applications` to the Dock. For day-to-day use, see [docs/HOW-TO-USE.md](docs/HOW-TO-USE.md).

## Repo map

```
backend/        FastAPI app — queue, engine client, health, library (python -m wfstudio)
frontend/       React dashboard — Create · Renders · Library · Models · Settings
studio/config/  settings, quality presets, model manifest
studio/templates/  the ComfyUI workflow (API format) + its parameter map
launch/         engine.sh, start/stop scripts, make-app.sh (Dock apps)
scripts/        installers and the model downloader
dev/            mock ComfyUI engine + acceptance tests (no GPU needed)
docs/           SPEC.md (full design), HOW-TO-USE.md
```

Building on this with Claude Code? Read [CLAUDE.md](CLAUDE.md) first.
