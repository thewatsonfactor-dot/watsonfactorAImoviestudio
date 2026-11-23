# Getting renders that look like film, not AI

Researched Nov 22 2026 for the Mac Studio (M4 Max, 36 GB). Ranked by how much each change cuts the "AI look".
Anything marked **unverified on this Mac** has no source showing it running on Apple Silicon at this size; test it before relying on it.

## The honest bar

The look Daniel wants is Higgsfield's. Higgsfield runs closed models (its own 2026 roundup lists Seedance 2.5, Kling 3.0 and Veo 3.1 among its top video engines) on data-center GPUs.
No open video model that runs on a 36 GB Mac matches them today:

- **LTX-2.5** (Lightricks, open weights Aug 2026, 22B) is the strongest open model, but its pipelines need an NVIDIA GPU with CUDA.
- **MiniMax H3** (33B, Aug 2026) runs on Macs through Draw Things (their Oct 2026 benchmark, 1024×512), but its licence **excludes the US**, so it's out.
- **LTX-2.3** in mlx-video is listed only for 64 GB+ Macs, and that listing is an estimate.
- **Wan 2.2 A14B** (what the Studio runs) is still the best open model that is proven on this Mac.

So the plan is a hybrid:

1. **Stills and plates locally**, where open models *can* reach photoreal: character sheets, anamorphic location plates, lighting plates, keyframes. No content filter, no cost per image.
2. **Hero shots on Higgsfield** (Seedance), fed those plates with the LENS Seedance prompt (LENS panel → "5 · Seedance prompt", **Copy for Higgsfield**).
3. **Local Wan for drafts, blocking and filler shots**, upgraded with the settings below.

## 1. The keyframe is the look (biggest lever)

Image-to-video copies what it sees in the keyframe. A plastic keyframe gives a plastic video, whatever the prompt says.

**Why the current stills look cartoonish:** the Image screen runs Qwen-Image-Edit-2511 with the 4-step Lightning LoRA at CFG 1. Community reports on Qwen's speed LoRAs say they give a plastic result nearly every time, and a research paper notes Qwen's skin tends to come out overly smooth. At CFG 1 the negative prompt is also ignored completely.

What to do, in order:

1. **Use the LENS panel** (built in this change). Realism lock on, Lens lock on for plates, Scope 2.39 shape. Make character sheets evenly lit, then location and lighting plates, then the keyframe. One or two generations per asset; never chain edits.
2. **Add Z-Image Turbo for text-only stills and plates.** 6B model; hands-on comparisons rate its skin detail above FLUX.2 dev and Qwen-Image. Small enough to fit easily:
   - BF16: diffusion model 12.3 GB + Qwen3-4B text encoder 8.0 GB + VAE 0.33 GB (about 20.6 GB on the SSD)
   - GGUF (ComfyUI-GGUF): Q5_K_M model 5.5 GB + Q5_K_M encoder 2.9 GB + VAE (about 8.7 GB)
   - ComfyUI ships an official Z-Image Turbo template. One user report shows it running in ComfyUI on an M3 Mac (19 s per step). **No M4 Max timing found.**
   - Keep Qwen-Image-Edit for shots that need 2-3 reference photos (two-character shots); Z-Image Turbo is text-to-image.
3. **For Qwen reference shots, try more steps without Lightning.** Turn off the Lightning LoRA, run 20-30 steps at CFG about 2.5-4 so the negative prompt works again. Slower (unverified on this Mac). Skin LoRAs exist (Skin Fix Qwen, made for Lightning; Qwen Edit Skin, trained on 2509), but none is confirmed on 2511.

## 2. Video: stop starving the model

Daniel's Mac runs Q3_K_M video models with a Q4_K_M text encoder and the 4-step Lightx2v LoRAs at CFG 1.

1. **Go back to Q4_K_M video models (keep the Q4_K_M encoder).** The Oct 17 tests on this Mac (CLAUDE.md, run C) showed Q4 models + Q4 encoder stayed at memory "warning" with a 4.5 GB swap rise; Q3 bought only 0.7 GB more. Q3 is a real detail loss for almost no memory gain. Change in Settings → quants: remove `unet_high` and `unet_low` (files already on the SSD, 9.65 GB each).
2. **Fix the slow, floaty "Lightning" motion with a 3-pass sampler.** Community recipe: pass 1 high-noise model *without* the LoRA at CFG 3.5 for the first 2 steps, pass 2 high-noise with the LoRA at CFG 1, pass 3 low-noise with the LoRA (strength about 0.7-1.0) at CFG 1. CFG above 1 doubles the cost of those steps, so expect longer renders. **Unverified on this Mac**; needs a new workflow template (job for the Mac session).
3. **Negative prompts at CFG 1: NAG.** ComfyUI has a built-in NAGuidance node and the ComfyUI-NAG custom node supports Wan with GGUF. For image-to-video, use low nag_tau / nag_alpha so the keyframe is kept. **Unverified on this Mac.** Until then, the LENS Realism lock puts "no CGI look" in the positive prompt, which is the only place CFG 1 reads it.

## 3. Frame rate, resolution and grain (post)

16 fps at 480p reads as AI or cheap video on its own.

1. **Film grain**: built in this change (LENS panel → Film grain finish). ffmpeg, a few seconds, the clean original is kept in `.raw/`.
2. **Frame interpolation 16 → 32 fps** (ComfyUI-Frame-Interpolation, RIFE). Small model, cheap. **Unverified on this Mac.**
3. **Upscale with SeedVR2** (numz/ComfyUI-SeedVR2_VideoUpscaler). Its README lists MPS support since 2.5.0 with later Mac fixes; no independent Mac speed tests found. Try the 3B GGUF first. **Unverified on this Mac.**
4. **Scope framing**: built in this change. 960×400 video (fewer latent tokens per frame than 832×480, so it fits the proven memory size), 1920×800 stills.

## Sources

- [Local video models: VRAM and licence (vdf.ai, Nov 2026)](https://vdf.ai/blog/best-local-video-generation-models/)
- [ComfyUI video models 2026 (tutorial3d.it)](https://www.tutorial3d.it/en/ai-artificial-intelligence/comfyui-video-models/)
- [Higgsfield: best AI video models 2026](https://higgsfield.ai/blog/5-Best-AI-Video-Models-2026-Tested-Compared)
- [Model rundown: Z-Image Turbo, Qwen-Image-2512, FLUX.2 dev](https://medium.com/diffusion-doodles/model-rundown-z-image-turbo-qwen-image-2512-edit-2511-flux-2-dev-fc787f5e87ad)
- [RealGen paper (Qwen skin smoothness)](https://arxiv.org/pdf/2512.00473)
- [Z-Image Turbo in ComfyUI (docs)](https://docs.comfy.org/tutorials/image/z-image/z-image-turbo.md)
- [Z-Image GGUF sizes (AmazingZImageWorkflow)](https://github.com/martin-rizzo/AmazingZImageWorkflow)
- [Z-Image BF16 file sizes](https://huggingface.co/GreyWizardInc/comfy-zimage-turbo)
- [Z-Image on an M3 Mac (stable-diffusion.cpp issue)](https://github.com/leejet/stable-diffusion.cpp/issues/1030)
- [Wan 2.2 Lightning: 3-sampler discussion](https://huggingface.co/lightx2v/Wan2.2-Lightning/discussions/5)
- [Wan 2.2 I2V Lightx2v slow-mo fix](https://huggingface.co/rzgar/Wan2.2_I2V_LightX2V_Slow-Mo_Fix)
- [Skin Fix Qwen](https://civarchive.com/models/2031296/skin-fix-qwen)
- [Qwen Edit Skin](https://huggingface.co/tlennon-ie/qwen-edit-skin)
- [Qwen-Image 2512 workflow notes](https://aistudynow.com/qwen-image-2512-comfyui-workflow/)
- [ComfyUI NAGuidance node](https://docs.comfy.org/built-in-nodes/NAGuidance)
- [ComfyUI-NAG](https://github.com/ChenDarYen/ComfyUI-NAG)
- [SeedVR2 upscaler for ComfyUI](https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler)
- [Wan 2.2 GGUF quant guide](https://www.wan27.org/blog/wan-2-2-gguf-guide)
