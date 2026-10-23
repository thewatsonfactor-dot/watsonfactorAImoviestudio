"""The render queue.

Studio owns its own queue (so jobs can be reordered or removed before they
start) and hands ComfyUI exactly one job at a time. A websocket listener turns
the engine's raw events into clean progress for the dashboard; a poller covers
for missed events and Studio restarts mid-render."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import websockets

from . import comfy, config, db, guards, health, system, workflow

log = logging.getLogger("wfstudio.runner")
ENGINE_LOG = config.LOG_DIR / "comfyui.log"  # where launch/engine.sh sends the engine's output

STAGE_LABELS = {
    "queued": "Waiting in line",
    "submitting": "Sending to engine",
    "load": "Loading models",
    "prompt": "Reading prompt",
    "encode": "Encoding keyframe",
    "sample_1": "Sampling — pass 1 of 2",
    "sample_2": "Sampling — pass 2 of 2",
    "decode": "Decoding frames",
    "save": "Saving video",
    "finishing": "Finishing up",
}
# Share of the progress bar each stage owns (sums to 100).
STAGE_WEIGHTS = [("load", 10), ("prompt", 4), ("encode", 6), ("sample_1", 34),
                 ("sample_2", 34), ("decode", 8), ("save", 4)]


def slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return s or "unsorted"


class Hub:
    """Fan-out of events to every open dashboard tab."""

    def __init__(self) -> None:
        self.queues: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.queues.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        for q in list(self.queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


def plain_engine_error(msg: str, exc_type: str = "", stage: str | None = None) -> str:
    low = f"{exc_type} {msg}".lower()
    if "out of memory" in low or "mps backend out of memory" in low:
        return ("Ran out of memory. Try Draft or Standard quality with Short length, "
                "and close Chrome and other apps.")
    if "float8" in low or "fp8" in low:
        return "A model file is fp8, which this Mac can't run. Use the GGUF files from the Models screen."
    if "no such file" in low or "not found" in low:
        return f"The engine couldn't find a file it needed: {msg}"
    where = f" while {STAGE_LABELS.get(stage or '', 'rendering').lower()}" if stage else ""
    return f"Render failed{where}: {msg}".strip()


class Runner:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.client_id = f"wfstudio-{uuid.uuid4().hex[:8]}"
        self.live: dict[str, dict[str, Any]] = {}
        self.ws_connected = False
        self.last_event_at = 0.0
        self.blocked_reason: str | None = None
        self._outputs: dict[str, list[dict[str, Any]]] = {}
        self._log_start: dict[str, int | None] = {}  # engine-log offset when each job was submitted
        self._node_stage: dict[str, str] = {}
        self._tasks: list[asyncio.Task] = []
        self._wake = asyncio.Event()

    # ---------- lifecycle ----------
    def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._tasks = [loop.create_task(self._dispatch_loop()),
                       loop.create_task(self._ws_loop()),
                       loop.create_task(self._poll_loop())]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()

    def wake(self) -> None:
        self._wake.set()

    # ---------- public actions ----------
    def enqueue(self, job: dict[str, Any]) -> dict[str, Any]:
        job.setdefault("id", uuid.uuid4().hex[:12])
        job.setdefault("created_at", time.time())
        job["status"] = "queued"
        job["queue_pos"] = db.next_queue_pos()
        row = db.insert_job(job)
        self.emit_job(row)
        self.emit_queue()
        self.wake()
        return row

    async def cancel(self, job_id: str) -> dict[str, Any] | None:
        job = db.get_job(job_id)
        if not job:
            return None
        if job["status"] == "queued":
            job = db.update_job(job_id, status="cancelled", finished_at=time.time())
        elif job["status"] == "running":
            if job.get("prompt_id"):
                try:
                    await comfy.interrupt(job["prompt_id"])
                    await comfy.delete_from_queue(job["prompt_id"])
                except httpx.HTTPError:
                    pass
            # Mark immediately; a late "interrupted" event is ignored.
            job = db.update_job(job_id, status="cancelled", finished_at=time.time())
            self.live.pop(job_id, None)
        self.emit_job(job)
        self.emit_queue()
        self.wake()
        return job

    def reorder(self, ids: list[str]) -> None:
        for i, jid in enumerate(ids):
            j = db.get_job(jid)
            if j and j["status"] == "queued":
                db.update_job(jid, queue_pos=float(i + 1))
        self.emit_queue()

    # ---------- events ----------
    def view(self, job: dict[str, Any] | None) -> dict[str, Any] | None:
        if job is None:
            return None
        s = config.settings()
        out = dict(job)

        def media(path: str | None, root_key: str, prefix: str) -> str | None:
            if not path:
                return None
            try:
                rel = Path(path).relative_to(s[root_key])
            except ValueError:
                return None
            return f"/media/{prefix}/{rel.as_posix()}"

        out["video_url"] = media(job.get("output_path"), "output_dir", "output")
        out["thumb_url"] = media(job.get("thumb_path"), "output_dir", "output") or \
            media(job.get("input_path"), "inputs_dir", "inputs")
        out["input_url"] = media(job.get("input_path"), "inputs_dir", "inputs")
        out["file_exists"] = bool(job.get("output_path") and Path(job["output_path"]).exists())
        out["live"] = self.live.get(job["id"])
        return out

    def emit_job(self, job: dict[str, Any] | None) -> None:
        if job:
            self.hub.publish({"type": "job", "job": self.view(job)})

    def emit_queue(self) -> None:
        q = db.queued()
        self.hub.publish({"type": "queue", "ids": [j["id"] for j in q],
                          "blocked_reason": self.blocked_reason})

    # ---------- dispatch ----------
    async def _dispatch_loop(self) -> None:
        while True:
            try:
                await self._dispatch_once()
            except Exception:  # noqa: BLE001
                log.exception("dispatch loop error")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _dispatch_once(self) -> None:
        if db.running():
            return
        q = db.queued()
        if not q:
            if self.blocked_reason:
                self.blocked_reason = None
                self.emit_queue()
            return
        h = await health.check()
        if not h["can_generate"]:
            if self.blocked_reason != h["blocked_reason"]:
                self.blocked_reason = h["blocked_reason"]
                self.emit_queue()
            return
        self.blocked_reason = None
        await self._submit(q[0])

    async def _submit(self, job: dict[str, Any]) -> None:
        s = config.settings()
        if not db.claim(job["id"]):
            return  # cancelled while we were checking health
        self.last_event_at = time.time()
        job = db.get_job(job["id"])  # type: ignore[assignment]
        self._set_live(job, "submitting")
        try:
            image_name = await comfy.upload_image(Path(job["input_path"]))
            params = {
                "image": image_name, "positive": job["prompt"], "negative": job["negative"] or "",
                "width": job["width"], "height": job["height"], "length": job["frames"],
                "seed": job["seed"], "steps": job["steps"], "split": job["split"],
                "cfg": job["cfg"], "shift": job["shift"],
                "fps": float(config.presets()["fps"]),
                "filename_prefix": f"wfstudio_tmp/{job['id']}",
            }
            prompt = workflow.build(s["workflow"], params)
            self._node_stage = workflow.stage_map(s["workflow"])
            log_start = guards.log_size(ENGINE_LOG)
            prompt_id = await comfy.queue_prompt(prompt, self.client_id)
        except comfy.EngineError as e:
            self._fail(job, str(e), json.dumps(e.detail)[:4000] if e.detail else None)
            return
        except (httpx.HTTPError, OSError) as e:
            self._fail(job, f"Couldn't reach the engine: {e}", None)
            return
        self._outputs.pop(prompt_id, None)
        self._log_start[job["id"]] = log_start
        job = db.update_job(job["id"], prompt_id=prompt_id)  # type: ignore[assignment]
        self.last_event_at = time.time()
        self._set_live(job, "load")
        self.emit_queue()

    # ---------- progress ----------
    def _set_live(self, job: dict[str, Any], stage: str, value: int | None = None,
                  maximum: int | None = None) -> None:
        started = job.get("started_at") or time.time()
        elapsed = time.time() - started
        pct = 0.0
        for name, w in STAGE_WEIGHTS:
            if name == stage:
                if value is not None and maximum:
                    pct += w * min(value / maximum, 1.0)
                break
            pct += w
        if stage in ("queued", "submitting"):
            pct = 0.0
        if stage == "finishing":
            pct = 99.0
        avg = db.avg_render_seconds(job["preset"], job["length"])
        eta = None
        if pct >= 20:
            eta = max(elapsed / (pct / 100) - elapsed, 0)
        elif avg:
            eta = max(avg - elapsed, 0)
        label = STAGE_LABELS.get(stage, stage)
        if stage.startswith("sample") and value is not None and maximum:
            label = f"{label} · step {value}/{maximum}"
        if job.get("chain_total") and job["chain_total"] > 1:
            label = f"{label} — part {job['chain_index']}/{job['chain_total']}"
        self.live[job["id"]] = {"stage": stage, "label": label, "step": value, "total_steps": maximum,
                                "percent": round(pct, 1), "elapsed": round(elapsed),
                                "eta_seconds": round(eta) if eta is not None else None}
        self.emit_job(db.get_job(job["id"]))

    def _job_for_prompt(self, prompt_id: str | None) -> dict[str, Any] | None:
        r = db.running()
        if r and prompt_id and r.get("prompt_id") == prompt_id:
            return r
        return None

    # ---------- engine websocket ----------
    async def _ws_loop(self) -> None:
        while True:
            try:
                async with websockets.connect(comfy.ws_url(self.client_id), max_size=None,
                                              open_timeout=5, ping_interval=20) as ws:
                    self.ws_connected = True
                    health.invalidate()
                    self.wake()
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue  # latent previews
                        try:
                            await self._on_event(json.loads(raw))
                        except Exception:  # noqa: BLE001
                            log.exception("bad engine event")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — never let the listener die; reconnect
                pass
            self.ws_connected = False
            await asyncio.sleep(2)

    async def _on_event(self, msg: dict[str, Any]) -> None:
        t, d = msg.get("type"), msg.get("data") or {}
        job = self._job_for_prompt(d.get("prompt_id"))
        if job:
            self.last_event_at = time.time()  # only events about our job count as "alive"
        if t == "executing" and job and d.get("node") is not None:
            stage = self._node_stage.get(str(d["node"]), "load")
            self._set_live(job, stage)
        elif t == "progress" and job:
            stage = self._node_stage.get(str(d.get("node")), "sample_1")
            self._set_live(job, stage, d.get("value"), d.get("max"))
        elif t == "executed" and d.get("prompt_id"):
            out = d.get("output") or {}
            files = [f for v in out.values() if isinstance(v, list) for f in v
                     if isinstance(f, dict) and f.get("filename")]
            if files:
                self._outputs.setdefault(d["prompt_id"], []).extend(files)
        elif t == "execution_success" and job:
            await self._finalize(job, self._outputs.pop(d["prompt_id"], []))
        elif t == "execution_error" and job:
            stage = (self.live.get(job["id"]) or {}).get("stage")
            self._fail(job, plain_engine_error(d.get("exception_message", ""), d.get("exception_type", ""), stage),
                       json.dumps({k: d.get(k) for k in ("node_type", "exception_type", "exception_message",
                                                          "traceback")})[:6000])
        elif t == "execution_interrupted" and job:
            db.update_job(job["id"], status="cancelled", finished_at=time.time())
            self.live.pop(job["id"], None)
            self.emit_job(db.get_job(job["id"]))
            self.wake()

    # ---------- fallback poller ----------
    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            try:
                await self._poll_once()
            except Exception:  # noqa: BLE001
                log.exception("poll loop error")

    async def _poll_once(self) -> None:
        job = db.running()
        if not job:
            return
        quiet = time.time() - self.last_event_at
        if self.ws_connected and quiet < 30:
            return
        if not job.get("prompt_id"):
            # Still being submitted (keyframe upload + /prompt). Only give up after 2 minutes.
            if time.time() - (job.get("started_at") or time.time()) > 120:
                self._fail(job, "The job never reached the engine. Try again.", None)
            return
        if await comfy.system_stats() is None:
            return  # engine down — wait for it
        hist = await comfy.history(job["prompt_id"])
        if hist:
            status = hist.get("status") or {}
            if status.get("status_str") == "error" or status.get("completed") is False:
                msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                detail = msgs[-1][1] if msgs else {}
                self._fail(job, plain_engine_error(detail.get("exception_message", "unknown error"),
                                                   detail.get("exception_type", "")),
                           json.dumps(detail)[:6000] if detail else None)
                return
            files = [f for o in (hist.get("outputs") or {}).values() for v in o.values()
                     if isinstance(v, list) for f in v if isinstance(f, dict) and f.get("filename")]
            await self._finalize(job, files)
            return
        qs = await comfy.queue_state()
        if qs is not None:
            ids = {item[1] for item in qs.get("queue_running", []) + qs.get("queue_pending", [])}
            if job["prompt_id"] not in ids:
                self._fail(job, "The engine restarted mid-render, so this job was lost. Re-roll it to try again.", None)

    # ---------- finishing ----------
    def _fail(self, job: dict[str, Any], message: str, detail: str | None) -> None:
        self._log_start.pop(job["id"], None)
        cur = db.get_job(job["id"])
        if cur and cur["status"] in ("cancelled", "done"):
            return
        self.live.pop(job["id"], None)
        self.emit_job(db.update_job(job["id"], status="failed", error=message, error_detail=detail,
                                    finished_at=time.time()))
        self.wake()

    async def _finalize(self, job: dict[str, Any], files: list[dict[str, Any]]) -> None:
        cur = db.get_job(job["id"])
        if not cur or cur["status"] != "running":
            return
        self._set_live(cur, "finishing")
        s = config.settings()
        video = next((f for f in files if str(f["filename"]).lower().endswith((".mp4", ".webm", ".mov", ".mkv"))),
                     files[0] if files else None)
        if not video:
            self._fail(cur, "The engine finished but didn't save a video. Check the Save step in the workflow.", None)
            return
        finished = time.time()
        date = datetime.now().strftime("%Y-%m-%d")
        dest_dir = Path(s["output_dir"]) / slug(cur["project"] or s["default_project"])
        dest_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(video["filename"]).suffix or ".mp4"
        dest = dest_dir / f"{date}_{cur['id'][:8]}{ext}"
        try:
            await self._collect(video, dest)
        except Exception as e:  # noqa: BLE001
            self._fail(cur, f"Render finished but the file couldn't be saved to the SSD: {e}", None)
            return
        # Never trust "success" alone: the engine can hide a GPU out-of-memory and hand back a blank video.
        gpu = guards.engine_log_problems(ENGINE_LOG, self._log_start.pop(cur["id"], None))
        blank = None if gpu else await asyncio.to_thread(guards.video_problems, dest, system.ffmpeg())
        if gpu or blank:
            kept = await asyncio.to_thread(self._quarantine, dest)
            detail = json.dumps({"check": "engine log" if gpu else "blank video", **(gpu or blank),
                                 "saved_for_inspection": str(kept) if kept else None})
            log.warning("job %s rejected: %s", cur["id"], detail)
            self._fail(cur, guards.GPU_ERROR_MESSAGE if gpu else guards.BLANK_MESSAGE, detail)
            return
        thumb = dest.with_suffix(".jpg")
        has_thumb = await asyncio.to_thread(system.make_thumbnail, dest, thumb)
        render_seconds = finished - (cur["started_at"] or finished)
        sidecar = dest.with_suffix(".json")
        meta = {
            "studio": "Watson Factor AI Studio", "job_id": cur["id"], "project": cur["project"],
            "prompt": cur["prompt"], "negative": cur["negative"], "seed": cur["seed"],
            "preset": cur["preset"], "length": cur["length"], "frames": cur["frames"],
            "width": cur["width"], "height": cur["height"], "steps": cur["steps"], "split": cur["split"],
            "cfg": cur["cfg"], "shift": cur["shift"], "fps": config.presets()["fps"],
            "input_image": cur["input_path"], "render_seconds": round(render_seconds, 1),
            "created_at": datetime.fromtimestamp(cur["created_at"]).isoformat(timespec="seconds"),
            "finished_at": datetime.fromtimestamp(finished).isoformat(timespec="seconds"),
            "models": {m["id"]: m["filename"] for m in config.manifest()},
            "workflow": s["workflow"], "parent_id": cur.get("parent_id"),
        }
        sidecar.write_text(json.dumps(meta, indent=2))
        self.live.pop(cur["id"], None)
        done = db.update_job(cur["id"], status="done", finished_at=finished, output_path=str(dest),
                             thumb_path=str(thumb) if has_thumb else None, sidecar_path=str(sidecar),
                             render_seconds=round(render_seconds, 1))
        self.emit_job(done)
        if done.get("chain_id"):
            await self._chain_advance(done)
        self.hub.publish({"type": "library_changed"})
        self.wake()

    async def _chain_advance(self, done: dict[str, Any]) -> None:
        """A segment of a chained ('Long') render just finished. Queue the next segment with this
        one's last frame as its keyframe, or — if this was the last segment — stitch every segment
        into one combined clip. Segments stay visible in the Library on their own (so a broken chain
        still leaves real, usable clips) until a successful combine hides them in favor of the one
        stitched result."""
        chain_id, index, total = done["chain_id"], done["chain_index"], done["chain_total"]
        if index < total:
            s = config.settings()
            frame_dir = Path(s["inputs_dir"]) / "chain"
            frame_dir.mkdir(parents=True, exist_ok=True)
            next_frame = frame_dir / f"{chain_id}_{index + 1}.png"
            ok = await asyncio.to_thread(system.extract_last_frame, Path(done["output_path"]), next_frame)
            if not ok:
                log.error("chain %s: couldn't pull the last frame after segment %s — chain stops here, "
                         "the %d finished segment(s) are still in the Library.", chain_id, done["id"], index)
                return
            nxt = {k: done[k] for k in ("project", "prompt", "negative", "preset", "length",
                                        "width", "height", "frames", "steps", "split", "cfg", "shift", "seed")}
            nxt.update(input_path=str(next_frame), chain_id=chain_id, chain_index=index + 1,
                       chain_total=total, parent_id=done["id"], tags=[])
            self.enqueue(nxt)
            # Macs don't release swap between renders (Oct 17 findings) — flush it before the next
            # segment so a 4-segment chain doesn't compound memory pressure a single render wouldn't see.
            try:
                await free_engine_memory()
            except Exception:  # noqa: BLE001 — best-effort; a failed flush shouldn't stop the chain
                log.warning("free-memory between chain segments failed", exc_info=True)
            return
        # Last segment: every piece should be done now — stitch them into one clip in order.
        segments = db.jobs("chain_id=? AND status='done'", (chain_id,), order="chain_index ASC")
        if len(segments) != total:
            log.error("chain %s: only %d of %d segments finished — leaving them as separate clips",
                      chain_id, len(segments), total)
            return
        s = config.settings()
        first = segments[0]
        date = datetime.now().strftime("%Y-%m-%d")
        dest_dir = Path(done["output_path"]).parent
        combined = dest_dir / f"{date}_{chain_id[:8]}_combined.mp4"
        ok = await asyncio.to_thread(system.concat_videos,
                                     [Path(g["output_path"]) for g in segments], combined)
        if not ok:
            log.error("chain %s: segments rendered but couldn't be stitched — leaving them as separate "
                     "clips in the Library.", chain_id)
            return
        thumb = combined.with_suffix(".jpg")
        has_thumb = await asyncio.to_thread(system.make_thumbnail, combined, thumb)
        total_seconds = sum(g["render_seconds"] or 0 for g in segments)
        total_frames = sum(g["frames"] or 0 for g in segments)
        sidecar = combined.with_suffix(".json")
        meta = {
            "studio": "Watson Factor AI Studio", "job_id": chain_id, "project": first["project"],
            "prompt": first["prompt"], "negative": first["negative"], "seed": first["seed"],
            "preset": first["preset"], "length": first["length"], "frames": total_frames,
            "width": first["width"], "height": first["height"], "steps": first["steps"],
            "split": first["split"], "cfg": first["cfg"], "shift": first["shift"],
            "fps": config.presets()["fps"], "input_image": first["input_path"],
            "render_seconds": round(total_seconds, 1),
            "created_at": datetime.fromtimestamp(first["created_at"]).isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "models": {m["id"]: m["filename"] for m in config.manifest()},
            "workflow": s["workflow"], "chain_id": chain_id, "segments": total,
        }
        sidecar.write_text(json.dumps(meta, indent=2))
        row = db.insert_job({
            "id": chain_id, "created_at": first["created_at"], "started_at": first["started_at"],
            "finished_at": time.time(), "status": "done", "project": first["project"],
            "prompt": first["prompt"], "negative": first["negative"], "preset": first["preset"],
            "length": first["length"], "seed": first["seed"], "width": first["width"],
            "height": first["height"], "frames": total_frames, "steps": first["steps"],
            "split": first["split"], "cfg": first["cfg"], "shift": first["shift"],
            "input_path": first["input_path"], "output_path": str(combined),
            "thumb_path": str(thumb) if has_thumb else None, "sidecar_path": str(sidecar),
            "render_seconds": round(total_seconds, 1), "tags": [], "hidden": 0,
            "chain_id": chain_id, "chain_index": total, "chain_total": total,
        })
        for g in segments:
            db.update_job(g["id"], hidden=1)
        self.emit_job(row)
        self.hub.publish({"type": "library_changed"})

    @staticmethod
    def _quarantine(dest: Path) -> Path | None:
        """Move a rejected render out of the project folder so it can't pass for real output."""
        qdir = Path(config.settings()["output_dir"]) / ".failed"
        try:
            qdir.mkdir(parents=True, exist_ok=True)
            target = qdir / dest.name
            shutil.move(str(dest), str(target))
            return target
        except OSError:
            return None

    async def _collect(self, video: dict[str, Any], dest: Path) -> None:
        """Move the engine's file into the project folder; download it if it lives elsewhere."""
        s = config.settings()
        sub = video.get("subfolder") or ""
        for root in (s["output_dir"], str(Path(s["comfy_dir"]) / "output")):
            src = Path(root) / sub / video["filename"]
            if src.exists():
                await asyncio.to_thread(shutil.move, str(src), str(dest))
                try:
                    src.parent.rmdir()  # remove empty wfstudio_tmp
                except OSError:
                    pass
                return
        async with httpx.AsyncClient(base_url=comfy.base(), timeout=120) as c:
            r = await c.get("/view", params={"filename": video["filename"], "subfolder": sub,
                                             "type": video.get("type", "output")})
            r.raise_for_status()
            dest.write_bytes(r.content)


async def free_engine_memory(settle_seconds: float = 20.0) -> dict[str, Any]:
    """POST /free, then watch swap until it stops falling (or settle_seconds pass).

    A 200 from the engine only means the request was accepted, so the result carries
    memory/swap before and after, and `swap_released_mb` says whether swap really dropped."""
    before = system.mem_snapshot()
    await comfy.free()
    after = before
    low = before["swap_used_mb"]
    deadline = time.monotonic() + settle_seconds
    stable = 0
    while time.monotonic() < deadline:
        await asyncio.sleep(2)
        after = system.mem_snapshot()
        cur, prev = after["swap_used_mb"], low
        if cur is not None and prev is not None and cur < prev - 5:
            low, stable = cur, 0
        else:
            stable += 1
            if stable >= 2:
                break
    released = None
    if before["swap_used_mb"] is not None and after["swap_used_mb"] is not None:
        released = round(before["swap_used_mb"] - after["swap_used_mb"], 1)
    result = {"before": before, "after": after, "swap_released_mb": released}
    log.info("free memory: %s", result)
    return result


def new_seed() -> int:
    return random.randint(0, 2**32 - 1)
