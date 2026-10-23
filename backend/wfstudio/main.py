"""Watson Factor AI Studio — local API + dashboard server (127.0.0.1 only)."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from . import config, db, forecast, health, models, runner, system, workflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wfstudio")

hub = runner.Hub()
engine_runner = runner.Runner(hub)


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.ensure_dirs()
    db.conn()
    engine_runner.start()
    yield
    await engine_runner.stop()


app = FastAPI(title="Watson Factor AI Studio", lifespan=lifespan)


# ---------------------------------------------------------------- health
@app.get("/api/health")
async def get_health() -> dict[str, Any]:
    h = await health.check()
    h["queue_blocked_reason"] = engine_runner.blocked_reason
    h["stats"] = db.stats()
    return h


@app.post("/api/engine/free")
async def engine_free() -> dict[str, Any]:
    """Free the engine's memory now. Returns swap/memory before and after."""
    try:
        return await runner.free_engine_memory()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Couldn't reach the engine: {e}")


@app.post("/api/engine/{action}")
async def engine(action: str) -> dict[str, Any]:
    if action not in ("start", "stop", "restart"):
        raise HTTPException(404)
    script = config.LAUNCH_DIR / "engine.sh"
    if not script.exists():
        raise HTTPException(500, "launch/engine.sh is missing")
    log_file = (config.LOG_DIR / "engine-control.log").open("a")
    subprocess.Popen(["/bin/bash", str(script), action], stdout=log_file, stderr=log_file,
                     start_new_session=True)
    health.invalidate()
    return {"ok": True, "action": action}


# ---------------------------------------------------------------- config
@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    # Raw values keep the {ssd_root} placeholders, so saving doesn't freeze resolved paths.
    return {"settings": config.raw_settings(), "resolved": config.settings(),
            "editable": sorted(config.EDITABLE)}


@app.put("/api/settings")
def put_settings(body: dict[str, Any]) -> dict[str, Any]:
    raw = config.raw_settings()
    changed = {k: v for k, v in body.items() if k in config.EDITABLE and raw.get(k) != v}
    config.save_local(changed)
    health.invalidate()
    return {"settings": config.raw_settings(), "resolved": config.settings()}


@app.get("/api/presets")
def get_presets() -> dict[str, Any]:
    p = config.presets()
    for key in p["presets"]:
        p["presets"][key]["avg_seconds"] = {
            length: db.avg_render_seconds(key, length) for length in p["lengths"]}
    return p


@app.get("/api/projects")
def get_projects() -> list[dict[str, Any]]:
    return db.projects()


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@app.post("/api/projects")
def add_project(p: ProjectIn) -> list[dict[str, Any]]:
    db.ensure_project(p.name.strip())
    return db.projects()


# ---------------------------------------------------------------- models
@app.get("/api/models")
def get_models() -> dict[str, Any]:
    return models.status()


@app.post("/api/models/{model_id}/download")
def download_model(model_id: str) -> dict[str, Any]:
    if not system.ssd_state(config.settings()["ssd_root"])["mounted"]:
        raise HTTPException(409, "Connect the SSD before downloading models.")
    try:
        return models.start_download(model_id)
    except KeyError:
        raise HTTPException(404, "Unknown model") from None


# ---------------------------------------------------------------- upload
@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    s = config.settings()
    if not system.ssd_state(s["ssd_root"])["mounted"]:
        raise HTTPException(409, "SSD not connected — plug it in to upload keyframes.")
    ext = Path(file.filename or "keyframe.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(415, "Use a PNG, JPG or WEBP keyframe.")
    day = datetime.now().strftime("%Y-%m-%d")
    folder = Path(s["inputs_dir"]) / day
    folder.mkdir(parents=True, exist_ok=True)
    stem = "".join(c if c.isalnum() or c in "-_" else "-" for c in Path(file.filename or "keyframe").stem)[:40]
    dest = folder / f"{uuid.uuid4().hex[:8]}_{stem}.png"
    data = await file.read()

    def save() -> tuple[int, int]:
        import io
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        im.save(dest, "PNG")
        return im.size

    try:
        w, h = await asyncio.to_thread(save)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "That file isn't a readable image.") from None
    orientation = workflow.orientation_for(w, h)
    return {"path": str(dest), "width": w, "height": h, "orientation": orientation,
            "url": f"/media/inputs/{dest.relative_to(s['inputs_dir']).as_posix()}"}


# ---------------------------------------------------------------- jobs
class JobIn(BaseModel):
    input_path: str
    prompt: str = Field(min_length=1)
    negative: str | None = None
    project: str | None = None
    preset: str = "standard"
    length: str = "standard"
    seed: int | None = None
    width: int | None = None
    height: int | None = None
    steps: int | None = None
    split: int | None = None
    parent_id: str | None = None
    allow_risky: bool = False  # "Try anyway" on a size that ran out of memory before


def _build_job(j: JobIn) -> dict[str, Any]:
    s, p = config.settings(), config.presets()
    if j.preset not in p["presets"]:
        raise HTTPException(400, f"Unknown quality preset '{j.preset}'")
    if j.length not in p["lengths"]:
        raise HTTPException(400, f"Unknown length '{j.length}'")
    length_def = p["lengths"][j.length]
    segments = length_def.get("segments", 1)
    if segments > 1 and j.preset == "final":
        raise HTTPException(409, "Long isn't supported with Final yet — chaining four 720p renders back "
                                 "to back is untested on this Mac and likely to run out of memory. "
                                 "Use Draft or Standard.")
    src = Path(j.input_path)
    if not src.exists():
        raise HTTPException(400, "The keyframe file is gone — drop it in again.")
    preset = p["presets"][j.preset]
    with Image.open(src) as im:
        orientation = workflow.orientation_for(*im.size)
    w, h = workflow.dimensions(orientation, preset["tier"])
    if j.width and j.height:
        w, h = workflow.snap16(j.width), workflow.snap16(j.height)
    steps = j.steps or preset["steps"]
    split = j.split if j.split is not None else preset["split"]
    split = max(1, min(split, steps - 1))
    job = {
        "project": (j.project or s["default_project"]).strip(),
        "prompt": j.prompt.strip(),
        "negative": j.negative if j.negative is not None else p["negative_default"],
        "preset": j.preset, "length": j.length,
        "seed": j.seed if j.seed is not None else runner.new_seed(),
        "width": w, "height": h, "frames": length_def["frames"],
        "steps": steps, "split": split, "cfg": preset["cfg"], "shift": preset["shift"],
        "input_path": str(src), "parent_id": j.parent_id, "tags": [],
    }
    if segments > 1:
        # The first segment of a new chain. The runner queues segments 2..N itself as each one
        # finishes (extracting the last frame forward), then stitches them into one combined clip.
        job.update(chain_id=uuid.uuid4().hex[:12], chain_index=1, chain_total=segments)
    return job


def _require_ssd() -> None:
    """Server-side half of the pre-flight: the dashboard already disables Generate, this stops scripts too."""
    root = config.settings()["ssd_root"]
    if not system.ssd_state(root)["mounted"]:
        raise HTTPException(409, f"SSD not connected — plug in {Path(root).name}.")


def _require_fits(job: dict[str, Any], allow_risky: bool) -> None:
    fc = forecast.forecast(job["width"], job["height"], job["frames"])
    if fc["level"] == "failed" and not allow_risky:
        raise HTTPException(409, fc["message"])


@app.get("/api/forecast")
def get_forecast(width: int, height: int, frames: int) -> dict[str, Any]:
    return forecast.forecast(width, height, frames)


@app.post("/api/jobs")
def create_job(j: JobIn) -> dict[str, Any]:
    _require_ssd()
    job = _build_job(j)
    _require_fits(job, j.allow_risky)
    return engine_runner.view(engine_runner.enqueue(job))  # type: ignore[return-value]


@app.get("/api/jobs")
def list_jobs(scope: str = "active") -> list[dict[str, Any]]:
    if scope == "active":
        rows = [r for r in [db.running()] if r] + db.queued()
        rows += db.jobs("status IN ('failed','cancelled') AND finished_at > ?", (time.time() - 86400,),
                        order="finished_at DESC", limit=10)
    else:
        rows = db.jobs("status != 'deleted'", limit=200)
    return [engine_runner.view(r) for r in rows]  # type: ignore[misc]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404)
    return engine_runner.view(j)  # type: ignore[return-value]


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, Any]:
    j = await engine_runner.cancel(job_id)
    if not j:
        raise HTTPException(404)
    return engine_runner.view(j)  # type: ignore[return-value]


@app.post("/api/jobs/{job_id}/dismiss")
def dismiss_job(job_id: str) -> dict[str, Any]:
    j = db.get_job(job_id)
    if not j or j["status"] not in ("failed", "cancelled"):
        raise HTTPException(400, "Only failed or cancelled jobs can be dismissed.")
    db.update_job(job_id, status="deleted")
    return {"ok": True}


@app.post("/api/queue/order")
def queue_order(ids: list[str]) -> dict[str, Any]:
    engine_runner.reorder(ids)
    return {"ok": True}


# ---------------------------------------------------------------- library
@app.get("/api/library")
def library(project: str | None = None, favorites: bool = False, preset: str | None = None,
            q: str | None = None) -> list[dict[str, Any]]:
    # A chained ("Long") render's own segments are hidden once stitched into the combined clip,
    # so the Library shows one finished entry per render, not four.
    where, params = ["status='done'", "(hidden IS NULL OR hidden=0)"], []
    if project:
        where.append("project=?")
        params.append(project)
    if favorites:
        where.append("favorite=1")
    if preset:
        where.append("preset=?")
        params.append(preset)
    if q:
        where.append("prompt LIKE ?")
        params.append(f"%{q}%")
    rows = db.jobs(" AND ".join(where), tuple(params), order="finished_at DESC", limit=500)
    return [engine_runner.view(r) for r in rows]  # type: ignore[misc]


class FavIn(BaseModel):
    favorite: bool


@app.post("/api/library/{job_id}/favorite")
def favorite(job_id: str, body: FavIn) -> dict[str, Any]:
    return engine_runner.view(db.update_job(job_id, favorite=body.favorite))  # type: ignore[return-value]


class TagsIn(BaseModel):
    tags: list[str]


@app.post("/api/library/{job_id}/tag")
def tag(job_id: str, body: TagsIn) -> dict[str, Any]:
    tags = sorted({t.strip() for t in body.tags if t.strip()})
    return engine_runner.view(db.update_job(job_id, tags=tags))  # type: ignore[return-value]


@app.post("/api/library/{job_id}/reroll")
def reroll(job_id: str) -> dict[str, Any]:
    _require_ssd()
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404)
    clone = {k: j[k] for k in ("project", "prompt", "negative", "preset", "length", "width", "height",
                               "frames", "steps", "split", "cfg", "shift", "input_path")}
    if not Path(clone["input_path"]).exists():
        raise HTTPException(400, "The original keyframe is no longer on the SSD.")
    _require_fits(clone, allow_risky=False)
    clone.update(seed=runner.new_seed(), parent_id=j["id"], tags=[])
    # Re-rolling a combined ("Long") clip restarts the whole chain from the original keyframe —
    # it must get a fresh chain_id, not the finished chain's stale one.
    segments = config.presets()["lengths"].get(clone["length"], {}).get("segments", 1)
    if segments > 1:
        clone.update(chain_id=uuid.uuid4().hex[:12], chain_index=1, chain_total=segments)
    return engine_runner.view(engine_runner.enqueue(clone))  # type: ignore[return-value]


@app.post("/api/library/{job_id}/delete")
def delete(job_id: str) -> dict[str, Any]:
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404)
    for key in ("output_path", "thumb_path", "sidecar_path"):
        if j.get(key):
            try:
                system.trash(j[key])
            except Exception as e:  # noqa: BLE001
                raise HTTPException(500, f"Couldn't move {Path(j[key]).name} to the Trash: {e}") from None
    db.update_job(job_id, status="deleted")
    hub.publish({"type": "library_changed"})
    return {"ok": True}


@app.post("/api/library/{job_id}/reveal")
def reveal(job_id: str) -> dict[str, Any]:
    j = db.get_job(job_id)
    if not j or not j.get("output_path"):
        raise HTTPException(404)
    if not system.reveal(j["output_path"]):
        raise HTTPException(409, "Show in Finder only works on the Mac, with the file on the SSD.")
    return {"ok": True}


@app.post("/api/library/rescan")
def rescan() -> dict[str, Any]:
    """Re-import renders from their JSON sidecars (recovers a lost database)."""
    s = config.settings()
    root = Path(s["output_dir"])
    added = 0
    if root.exists():
        for side in root.rglob("*.json"):
            try:
                meta = json.loads(side.read_text())
            except (OSError, ValueError):
                continue
            if meta.get("studio") != "Watson Factor AI Studio" or db.get_job(meta.get("job_id", "")):
                continue
            video = next((side.with_suffix(e) for e in (".mp4", ".webm", ".mkv") if side.with_suffix(e).exists()), None)
            if not video:
                continue
            thumb = side.with_suffix(".jpg")
            ts = lambda v: datetime.fromisoformat(v).timestamp() if v else time.time()  # noqa: E731
            db.insert_job({
                "id": meta["job_id"], "created_at": ts(meta.get("created_at")),
                "finished_at": ts(meta.get("finished_at")), "status": "done",
                "project": meta.get("project"), "prompt": meta.get("prompt"), "negative": meta.get("negative"),
                "preset": meta.get("preset"), "length": meta.get("length"), "seed": meta.get("seed"),
                "width": meta.get("width"), "height": meta.get("height"), "frames": meta.get("frames"),
                "steps": meta.get("steps"), "split": meta.get("split"), "cfg": meta.get("cfg"),
                "shift": meta.get("shift"), "input_path": meta.get("input_image"),
                "output_path": str(video), "thumb_path": str(thumb) if thumb.exists() else None,
                "sidecar_path": str(side), "render_seconds": meta.get("render_seconds"),
                "parent_id": meta.get("parent_id"), "tags": [],
            })
            added += 1
    hub.publish({"type": "library_changed"})
    return {"added": added}


# ---------------------------------------------------------------- media
def _safe(root: str, rel: str) -> Path:
    base = Path(root).resolve()
    p = (base / rel).resolve()
    if base not in p.parents and p != base:
        raise HTTPException(403)
    if not p.is_file():
        raise HTTPException(404)
    return p


@app.get("/media/output/{rel:path}")
def media_output(rel: str) -> FileResponse:
    return FileResponse(_safe(config.settings()["output_dir"], rel))


@app.get("/media/inputs/{rel:path}")
def media_inputs(rel: str) -> FileResponse:
    return FileResponse(_safe(config.settings()["inputs_dir"], rel))


# ---------------------------------------------------------------- live events
@app.websocket("/api/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()
    q = hub.subscribe()
    try:
        await socket.send_json({"type": "hello", "client": engine_runner.client_id})
        while True:
            event = await q.get()
            await socket.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(q)


# ---------------------------------------------------------------- dashboard
@app.get("/{path:path}", include_in_schema=False)
def spa(path: str) -> Any:
    dist = config.FRONTEND_DIST
    if path.startswith("api/") or path.startswith("media/"):
        raise HTTPException(404)
    target = (dist / path).resolve()
    if path and target.is_file() and dist.resolve() in target.parents:
        return FileResponse(target)
    index = dist / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"error": "Dashboard not built. Run scripts/install-studio.sh"}, status_code=503)
