"""A fake ComfyUI engine for developing and testing the Studio without a GPU.

It speaks the same HTTP + websocket API the Studio uses, walks the submitted
workflow node by node with realistic progress events, and "renders" a slow
push-in on the keyframe with ffmpeg so the Library has a real mp4. Image
workflows (Qwen, SaveImage) get a real PNG: the first reference image fitted to
the canvas, or a test pattern when there are no references.

    WFSTUDIO_SSD_ROOT=/tmp/fake-ssd python dev/mock_comfy.py --port 8188 [--speed 0.2] [--fail-at 14] [--blank]

--blank imitates a silent GPU out-of-memory: the run reports success but the mp4 is flat gray.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8188)
ap.add_argument("--speed", type=float, default=0.25, help="seconds per sampling step")
ap.add_argument("--fail-at", default=None, help="node id that raises an OOM error")
ap.add_argument("--blank", action="store_true", help="report success but write a flat gray video")
args, _ = ap.parse_known_args()

SSD = Path(os.environ.get("WFSTUDIO_SSD_ROOT", "/tmp/fake-ssd"))
OUT = Path(os.environ.get("MOCK_OUTPUT_DIR", SSD / "Studio_Output"))
MODELS = SSD / "ComfyUI_Models"
INPUT = Path(os.environ.get("MOCK_INPUT_DIR", "/tmp/mock-comfy-input"))
INPUT.mkdir(parents=True, exist_ok=True)

app = FastAPI()
sockets: dict[str, WebSocket] = {}
history: dict[str, dict] = {}
queue_running: list = []
interrupted: set[str] = set()


def files(folder: str) -> list[str]:
    d = MODELS / folder
    return sorted(p.name for p in d.iterdir() if p.is_file()) if d.exists() else []


def object_info() -> dict:
    combo = lambda opts: [opts]  # noqa: E731
    return {
        "LoadImage": {"input": {"required": {"image": combo([p.name for p in INPUT.rglob("*.png")])}}},
        "UnetLoaderGGUF": {"input": {"required": {"unet_name": combo(files("diffusion_models"))}}},
        "CLIPLoaderGGUF": {"input": {"required": {"clip_name": combo(files("text_encoders")),
                                                  "type": combo(["wan", "stable_diffusion", "qwen_image"])}}},
        "VAELoader": {"input": {"required": {"vae_name": combo(files("vae"))}}},
        "LoraLoaderModelOnly": {"input": {"required": {"model": ["MODEL"], "lora_name": combo(files("loras")),
                                                       "strength_model": ["FLOAT", {}]}}},
        "ModelSamplingSD3": {"input": {"required": {"model": ["MODEL"], "shift": ["FLOAT", {}]}}},
        "CLIPTextEncode": {"input": {"required": {"text": ["STRING", {}], "clip": ["CLIP"]}}},
        "WanImageToVideo": {"input": {"required": {k: ["X"] for k in ("positive", "negative", "vae", "width", "height", "length", "batch_size")},
                                      "optional": {"start_image": ["IMAGE"], "clip_vision_output": ["X"], "ref_pad_image": ["IMAGE"]}}},
        "KSamplerAdvanced": {"input": {"required": {k: ["X"] for k in (
            "model", "add_noise", "noise_seed", "steps", "cfg", "sampler_name", "scheduler", "positive",
            "negative", "latent_image", "start_at_step", "end_at_step", "return_with_leftover_noise")}}},
        "VAEDecode": {"input": {"required": {"samples": ["LATENT"], "vae": ["VAE"]}}},
        "CreateVideo": {"input": {"required": {"images": ["IMAGE"], "fps": ["FLOAT", {}]},
                                  "optional": {"audio": ["AUDIO"]}}},
        "SaveVideo": {"input": {"required": {"video": ["VIDEO"], "filename_prefix": ["STRING", {}],
                                             "format": ["COMFY_DYNAMICCOMBO_V3", {}]}}},
        # Image workflow (Qwen-Image-Edit-2511)
        "ModelSamplingAuraFlow": {"input": {"required": {"model": ["MODEL"], "shift": ["FLOAT", {}]},
                                            "optional": {"sampling": [["flow", "img_to_img_velocity"]]}}},
        "CFGNorm": {"input": {"required": {"model": ["MODEL"], "strength": ["FLOAT", {}]},
                              "optional": {"pre_cfg": ["BOOLEAN", {}]}}},
        "TextEncodeQwenImageEditPlus": {"input": {"required": {"clip": ["CLIP"], "prompt": ["STRING", {}]},
                                                  "optional": {"vae": ["VAE"], "image1": ["IMAGE"],
                                                               "image2": ["IMAGE"], "image3": ["IMAGE"]}}},
        "FluxKontextMultiReferenceLatentMethod": {"input": {"required": {
            "conditioning": ["CONDITIONING"],
            "reference_latents_method": [["offset", "index", "uxo/uno", "index_timestep_zero"]]}}},
        "EmptySD3LatentImage": {"input": {"required": {"width": ["INT", {}], "height": ["INT", {}],
                                                       "batch_size": ["INT", {}]}}},
        "KSampler": {"input": {"required": {k: ["X"] for k in (
            "model", "seed", "steps", "cfg", "sampler_name", "scheduler", "positive", "negative",
            "latent_image", "denoise")}}},
        "SaveImage": {"input": {"required": {"images": ["IMAGE"], "filename_prefix": ["STRING", {}]}}},
    }


@app.get("/system_stats")
def system_stats():
    return {"system": {"os": "darwin", "comfyui_version": "0.41.0 (mock)", "pytorch_version": "2.9.0",
                       "python_version": "3.11"},
            "devices": [{"name": "mps", "type": "mps", "vram_total": 38654705664}]}


@app.get("/object_info/{cls}")
def object_info_one(cls: str):
    info = object_info().get(cls)
    return {cls: info} if info else {}


@app.post("/upload/image")
async def upload(image: UploadFile = File(...), subfolder: str = Form(""), overwrite: str = Form("")):
    d = INPUT / subfolder
    d.mkdir(parents=True, exist_ok=True)
    (d / image.filename).write_bytes(await image.read())
    return {"name": image.filename, "subfolder": subfolder, "type": "input"}


async def send(client_id: str, type_: str, data: dict) -> None:
    ws = sockets.get(client_id)
    if ws:
        try:
            await ws.send_text(json.dumps({"type": type_, "data": data}))
        except Exception:  # noqa: BLE001
            pass


def render_still(img: Path | None, out: Path, w: int, h: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.blank:
        src = ["-f", "lavfi", "-i", f"color=c=gray:s={w}x{h}"]
        vf = "null"
    elif img is not None:
        src = ["-i", str(img)]
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    else:
        src = ["-f", "lavfi", "-i", f"testsrc2=s={w}x{h}"]
        vf = "null"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src, "-vf", vf, "-frames:v", "1", str(out)], check=True)


def render(img: Path, out: Path, w: int, h: int, frames: int, fps: float) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.blank:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=gray:s={w}x{h}:r={fps}",
                        "-frames:v", str(frames), "-pix_fmt", "yuv420p", "-c:v", "libx264", str(out)], check=True)
        return
    vf = (f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,crop={w*2}:{h*2},"
          f"zoompan=z='min(zoom+0.0025,1.25)':d={frames}:s={w}x{h}:fps={fps}")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(img), "-vf", vf, "-frames:v",
                    str(frames), "-pix_fmt", "yuv420p", "-c:v", "libx264", str(out)], check=True)


async def execute(prompt_id: str, prompt: dict, client_id: str) -> None:
    started = time.time()
    await send(client_id, "execution_start", {"prompt_id": prompt_id})
    queue_running.append([0, prompt_id, prompt, {}, []])
    order = sorted(prompt, key=lambda k: int(k))
    output = None
    out_node = "17"
    try:
        for nid in order:
            if prompt_id in interrupted:
                await send(client_id, "execution_interrupted", {"prompt_id": prompt_id, "node_id": nid})
                history[prompt_id] = {"status": {"status_str": "error", "completed": False, "messages": []}, "outputs": {}}
                return
            node = prompt[nid]
            await send(client_id, "executing", {"node": nid, "display_node": nid, "prompt_id": prompt_id})
            if args.fail_at and nid == args.fail_at:
                err = {"prompt_id": prompt_id, "node_id": nid, "node_type": node["class_type"],
                       "exception_type": "torch.OutOfMemoryError",
                       "exception_message": "MPS backend out of memory (MPS allocated: 34.1 GB)",
                       "traceback": ["fake traceback"]}
                await send(client_id, "execution_error", err)
                history[prompt_id] = {"status": {"status_str": "error", "completed": False,
                                                 "messages": [["execution_error", err]]}, "outputs": {}}
                return
            if node["class_type"] in ("KSamplerAdvanced", "KSampler"):
                i = node["inputs"]
                total = i["steps"]
                run = (min(i["end_at_step"], total) - i["start_at_step"]) if "end_at_step" in i else total
                for v in range(1, run + 1):
                    if prompt_id in interrupted:
                        break
                    await asyncio.sleep(args.speed)
                    await send(client_id, "progress", {"value": v, "max": run, "prompt_id": prompt_id, "node": nid})
            elif node["class_type"] in ("UnetLoaderGGUF", "VAEDecode"):
                await asyncio.sleep(args.speed * 2)
            elif node["class_type"] == "SaveImage":
                canvas = next(n["inputs"] for n in prompt.values() if n["class_type"] == "EmptySD3LatentImage")
                loads = [prompt[k]["inputs"]["image"] for k in sorted(prompt, key=int)
                         if prompt[k]["class_type"] == "LoadImage"]
                prefix = node["inputs"]["filename_prefix"]
                sub, base = (prefix.rsplit("/", 1) if "/" in prefix else ("", prefix))
                fname = f"{base}_00001_.png"
                await asyncio.to_thread(render_still, INPUT / loads[0] if loads else None, OUT / sub / fname,
                                        canvas["width"], canvas["height"])
                output = {"images": [{"filename": fname, "subfolder": sub, "type": "output"}]}
                out_node = nid
                await send(client_id, "executed", {"node": nid, "display_node": nid, "output": output,
                                                   "prompt_id": prompt_id})
            elif node["class_type"] == "SaveVideo":
                img_name = prompt["1"]["inputs"]["image"]
                wi = prompt["12"]["inputs"]
                prefix = node["inputs"]["filename_prefix"]
                sub, base = (prefix.rsplit("/", 1) if "/" in prefix else ("", prefix))
                fname = f"{base}_00001_.mp4"
                await asyncio.to_thread(render, INPUT / img_name, OUT / sub / fname, wi["width"], wi["height"],
                                        wi["length"], prompt["16"]["inputs"]["fps"])
                output = {"images": [{"filename": fname, "subfolder": sub, "type": "output"}], "animated": [True]}
                out_node = nid
                await send(client_id, "executed", {"node": nid, "display_node": nid, "output": output,
                                                   "prompt_id": prompt_id})
            else:
                await asyncio.sleep(0.05)
        await send(client_id, "executing", {"node": None, "prompt_id": prompt_id})
        await send(client_id, "execution_success", {"prompt_id": prompt_id})
        history[prompt_id] = {"status": {"status_str": "success", "completed": True, "messages": []},
                              "outputs": {out_node: output or {}}, "took": time.time() - started}
    finally:
        queue_running[:] = [q for q in queue_running if q[1] != prompt_id]


@app.post("/prompt")
async def post_prompt(req: Request):
    body = await req.json()
    prompt, client_id = body["prompt"], body.get("client_id", "")
    info = object_info()
    for nid, node in prompt.items():
        if node["class_type"] not in info:
            return JSONResponse({"error": {"type": "missing_node_type", "message": f"Node '{node['class_type']}' not found"},
                                 "node_errors": {}}, status_code=400)
    # Like the real engine: every wire must point at a node that's in the prompt.
    for nid, node in prompt.items():
        for inp, v in node["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in prompt:
                return JSONResponse({"error": {"type": "prompt_outputs_failed_validation",
                                               "message": f"Node {nid} input '{inp}' links to missing node {v[0]}"},
                                     "node_errors": {}}, status_code=400)
    for nid in [k for k, n in prompt.items() if n["class_type"] == "UnetLoaderGGUF"]:
        name = prompt[nid]["inputs"]["unet_name"]
        if name not in files("diffusion_models"):
            return JSONResponse({"error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation"},
                                 "node_errors": {nid: {"class_type": "UnetLoaderGGUF", "errors": [
                                     {"type": "value_not_in_list", "message": "Value not in list",
                                      "details": f"unet_name: '{name}' not in []"}]}}}, status_code=400)
    pid = str(uuid.uuid4())
    asyncio.create_task(execute(pid, prompt, client_id))
    return {"prompt_id": pid, "number": 0, "node_errors": {}}


@app.post("/interrupt")
async def interrupt(req: Request):
    try:
        pid = (await req.json()).get("prompt_id")
    except Exception:  # noqa: BLE001
        pid = None
    for q in queue_running:
        if pid is None or q[1] == pid:
            interrupted.add(q[1])
    return {}


@app.post("/free")
async def free(req: Request):
    return {}


@app.post("/queue")
async def post_queue():
    return {}


@app.get("/queue")
def get_queue():
    return {"queue_running": queue_running, "queue_pending": []}


@app.get("/history/{pid}")
def get_history(pid: str):
    return {pid: history[pid]} if pid in history else {}


@app.get("/view")
def view(filename: str, subfolder: str = "", type: str = "output"):  # noqa: A002
    return FileResponse(OUT / subfolder / filename)


@app.websocket("/ws")
async def ws(socket: WebSocket, clientId: str = ""):  # noqa: N803
    await socket.accept()
    sockets[clientId] = socket
    await socket.send_text(json.dumps({"type": "status", "data": {"status": {"exec_info": {"queue_remaining": 0}}},
                                       "sid": clientId}))
    try:
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        sockets.pop(clientId, None)


if __name__ == "__main__":
    if not shutil.which("ffmpeg"):
        raise SystemExit("mock_comfy needs ffmpeg on PATH")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
