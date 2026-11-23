"""Cloud shots: send a Studio frame and a LENS prompt to a top video model (Seedance 2.5, Kling 3.0)
through fal.ai or Replicate, and keep every take in a take library with its prompt, model and cost.

Spending money is Daniel's call, so nothing here runs on its own: a take is only sent when the
dashboard posts it with the estimate he confirmed. API keys live in studio/config/keys.local.json
(git-ignored, owner-only file mode), are only ever sent to the two providers' own API hosts, and are
scrubbed from anything the Studio logs, stores or shows.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image

from . import config, db, system

log = logging.getLogger("wfstudio.cloud")

CATALOG = config.CONFIG_DIR / "cloud.json"
KEYS = config.CONFIG_DIR / "keys.local.json"
PROVIDERS = ("fal", "replicate")
# The only hosts a key is ever sent to. cloud.json can rename models, not redirect keys.
API_HOSTS = {"fal": ("queue.fal.run",), "replicate": ("api.replicate.com",)}
KEY_ENV = {"fal": "WFSTUDIO_FAL_KEY", "replicate": "WFSTUDIO_REPLICATE_KEY"}
KEY_RE = re.compile(r"^[A-Za-z0-9_\-:.]{8,256}$")

ACTIVE = ("sending", "queued", "running")
POLL_SECONDS = 5.0
GIVE_UP_SECONDS = 45 * 60          # a take still not back after this is marked failed (it may still bill)
MAX_DOWNLOAD_BYTES = 1_500_000_000
DATA_URI_LIMIT = 950_000           # Replicate recommends data URIs under 1 MB


class CloudError(Exception):
    """A take can't be sent or was refused; the message is safe to show Daniel."""


# ---------------------------------------------------------------- catalog and keys
def catalog() -> dict[str, Any]:
    return json.loads(CATALOG.read_text())


def model_def(model_id: str) -> dict[str, Any]:
    m = next((m for m in catalog()["models"] if m["id"] == model_id), None)
    if not m:
        raise CloudError(f"Unknown model {model_id!r}.")
    return m


def _read_keys() -> dict[str, str]:
    try:
        data = json.loads(KEYS.read_text())
    except (OSError, ValueError):
        data = {}
    out = {p: str(data[p]) for p in PROVIDERS if data.get(p)}
    for p, env in KEY_ENV.items():
        if os.environ.get(env):
            out[p] = os.environ[env]
    return out


def key_for(provider: str) -> str | None:
    return _read_keys().get(provider)


def keys_status() -> dict[str, dict[str, Any]]:
    keys = _read_keys()
    return {p: {"saved": p in keys, "hint": f"…{keys[p][-4:]}" if p in keys else None} for p in PROVIDERS}


def save_key(provider: str, key: str) -> dict[str, dict[str, Any]]:
    if provider not in PROVIDERS:
        raise CloudError("Unknown provider.")
    key = key.strip()
    if key and not KEY_RE.match(key):
        raise CloudError("That doesn't look like an API key. Paste the whole key, with nothing around it.")
    try:
        data = json.loads(KEYS.read_text())
    except (OSError, ValueError):
        data = {}
    if key:
        data[provider] = key
    else:
        data.pop(provider, None)
    # Owner-only from the moment it exists: other accounts on the Mac can't read the keys.
    fd = os.open(KEYS, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(KEYS, 0o600)
    return keys_status()


def redact(text: Any) -> str:
    """Strip every saved key out of text before it is logged, stored or shown."""
    s = str(text or "")
    for k in _read_keys().values():
        if k:
            s = s.replace(k, "[key]")
    return s


def _auth(provider: str) -> dict[str, str]:
    key = key_for(provider)
    if not key:
        raise CloudError(f"No {catalog()['providers'][provider]['label']} key yet. Add it in Settings > Cloud keys.")
    return {"Authorization": f"Key {key}" if provider == "fal" else f"Bearer {key}"}


def _api_url(provider: str, url: str) -> str:
    """Refuse to send a key anywhere but the provider's own API host, over https."""
    u = urlparse(url)
    if u.scheme != "https" or u.hostname not in API_HOSTS[provider]:
        raise CloudError(f"Refused to send your key to {u.hostname or url}: it isn't {provider}'s API.")
    return url


# ---------------------------------------------------------------- pricing and request shape
def estimate(model_id: str, provider: str, duration: int, resolution: str, audio: bool) -> float:
    pc = _provider_cfg(model_def(model_id), provider)
    per_second = float(pc["price_per_second"][resolution])
    mult = float(pc.get("audio_multiplier", 1.0)) if audio else 1.0
    return round(per_second * duration * mult, 2)


def _provider_cfg(m: dict[str, Any], provider: str) -> dict[str, Any]:
    pc = m["providers"].get(provider)
    if not pc:
        raise CloudError(f"{m['label']} isn't set up for {provider} in cloud.json.")
    return pc


def validate(model_id: str, provider: str, duration: int, resolution: str, audio: bool) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise CloudError("Pick fal.ai or Replicate.")
    m = model_def(model_id)
    _provider_cfg(m, provider)
    if duration not in m["durations"]:
        raise CloudError(f"{m['label']} takes {', '.join(map(str, m['durations']))} second shots here.")
    if resolution not in m["resolutions"]:
        raise CloudError(f"{m['label']} takes {' or '.join(m['resolutions'])} here.")
    if audio and not m.get("audio"):
        raise CloudError(f"{m['label']} has no sound option.")
    return m


def build_input(m: dict[str, Any], provider: str, image: str, prompt: str, duration: int,
                resolution: str, audio: bool) -> dict[str, Any]:
    """Map the Studio's fields onto the provider's own input names (all set in cloud.json)."""
    pc = _provider_cfg(m, provider)
    inp: dict[str, Any] = dict(pc.get("extra") or {})
    inp[pc["image"]] = image
    inp[pc["prompt"]] = prompt
    d = pc["duration"]
    inp[d["key"]] = str(duration) if d.get("type") == "string" else int(duration)
    r = pc.get("resolution")
    if r and r.get("key"):
        inp[r["key"]] = resolution
    elif r and r.get("map"):
        inp.update(r["map"][resolution])
    if pc.get("audio"):
        inp[pc["audio"]] = bool(audio)
    return inp


def submit_url(m: dict[str, Any], provider: str, resolution: str) -> str:
    pc = _provider_cfg(m, provider)
    base = catalog()["providers"][provider]["base"].rstrip("/")
    if provider == "fal":
        endpoint = (pc.get("endpoints_by_resolution") or {}).get(resolution) or pc["endpoint"]
        return _api_url(provider, f"{base}/{endpoint.strip('/')}")
    return _api_url(provider, f"{base}/models/{pc['model'].strip('/')}/predictions")


# ---------------------------------------------------------------- frames
def frame_from_job(job: dict[str, Any], seconds: float) -> Path:
    """Save the chosen frame of a Library render (or the still itself) into the keyframe folder."""
    src = Path(job.get("output_path") or "")
    if not src.is_file():
        raise CloudError("That render isn't on the SSD.")
    folder = Path(config.settings()["inputs_dir"]) / datetime.now().strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    stamp = f"{seconds:.2f}".replace(".", "s")
    dest = folder / f"{uuid.uuid4().hex[:8]}_frame-{job['id'][:8]}-{stamp}.png"
    if job.get("kind") == "image":
        with Image.open(src) as im:
            im.convert("RGB").save(dest, "PNG")
    elif not system.extract_frame(src, seconds, dest):
        raise CloudError("Couldn't grab that frame. Is ffmpeg installed?")
    return dest


def data_uri(path: Path) -> str:
    """The frame as a JPEG data URI small enough for both providers (under ~1 MB). Full size first;
    only shrinks quality, then size, when a big frame needs it."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        if max(im.size) > 3840:
            im.thumbnail((3840, 3840), Image.LANCZOS)
        quality = 95
        while True:
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=quality, optimize=True)
            if buf.tell() <= DATA_URI_LIMIT:
                break
            if quality > 80:
                quality -= 5
            else:
                im = im.resize((int(im.width * 0.85), int(im.height * 0.85)), Image.LANCZOS)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _inside(path: Path, *roots: str) -> bool:
    p = path.resolve()
    return any(Path(r).resolve() in p.parents for r in roots if r)


def check_frame(path_str: str) -> Path:
    s = config.settings()
    p = Path(path_str)
    if not p.is_file() or not _inside(p, s["inputs_dir"], s["output_dir"]):
        raise CloudError("Pick a frame from the Studio first (upload one, or grab one from a render).")
    return p


# ---------------------------------------------------------------- provider responses
def _explain(r: httpx.Response) -> str:
    """The provider's own reason, readable, with any key scrubbed."""
    try:
        body = r.json()
    except ValueError:
        return redact(f"HTTP {r.status_code}: {r.text[:300]}")
    detail = body.get("detail") if isinstance(body, dict) else body
    if isinstance(detail, list):  # fal / pydantic style: [{"loc": [...], "msg": "..."}]
        parts = []
        for d in detail[:4]:
            if isinstance(d, dict):
                loc = ".".join(str(x) for x in d.get("loc", []) if x != "body")
                parts.append(f"{loc}: {d.get('msg')}" if loc else str(d.get("msg")))
        detail = "; ".join(parts)
    msg = detail
    if not msg and isinstance(body, dict):
        msg = body.get("error") or body.get("title")
    return redact(f"HTTP {r.status_code}: {msg or r.text[:300]}")


def _video_url(output: Any) -> str | None:
    """Find the video URL in a provider result (fal: {"video": {"url"}}, Replicate: str or list)."""
    if isinstance(output, str):
        return output if output.startswith("https://") else None
    if isinstance(output, list):
        for o in output:
            u = _video_url(o)
            if u:
                return u
    if isinstance(output, dict):
        for k in ("video", "output", "url", "videos"):
            if k in output:
                u = _video_url(output[k])
                if u:
                    return u
    return None


# ---------------------------------------------------------------- the take runner
class CloudShots:
    def __init__(self, hub: Any) -> None:
        self.hub = hub
        self.tasks: dict[str, asyncio.Task] = {}

    def start(self) -> None:
        """Pick up takes that were in flight when the Studio last stopped (they may already be billed)."""
        for t in db.takes(f"status IN ({','.join('?' * len(ACTIVE))})", ACTIVE):
            if t["remote_id"]:
                self._spawn(t["id"])
            else:
                db.update_take(t["id"], status="failed", finished_at=time.time(),
                               error="The Studio stopped before this take was sent. Nothing was charged for it.")

    async def stop(self) -> None:
        for task in self.tasks.values():
            task.cancel()

    def view(self, take: dict[str, Any] | None) -> dict[str, Any] | None:
        if take is None:
            return None
        s = config.settings()

        def media(path: str | None) -> str | None:
            if not path:
                return None
            for root, prefix in ((s["output_dir"], "output"), (s["inputs_dir"], "inputs")):
                try:
                    return f"/media/{prefix}/{Path(path).relative_to(root).as_posix()}"
                except ValueError:
                    continue
            return None

        out = {k: v for k, v in take.items() if k not in ("status_url", "result_url", "cancel_url")}
        out["video_url"] = media(take.get("output_path"))
        out["thumb_url"] = media(take.get("thumb_path")) or media(take.get("frame_path"))
        out["frame_url"] = media(take.get("frame_path"))
        out["file_exists"] = bool(take.get("output_path") and Path(take["output_path"]).exists())
        return out

    def emit(self, take: dict[str, Any] | None) -> None:
        if take:
            self.hub.publish({"type": "take", "take": self.view(take)})

    def create(self, *, project: str, provider: str, model: str, prompt: str, duration: int, resolution: str,
               audio: bool, frame_path: str, confirmed_cost: float, source_job_id: str | None = None,
               source_time: float | None = None) -> dict[str, Any]:
        m = validate(model, provider, duration, resolution, audio)
        _auth(provider)  # fail now, before anything is recorded, when the key is missing
        frame = check_frame(frame_path)
        prompt = prompt.strip()
        if not prompt:
            raise CloudError("Write the shot prompt first.")
        if len(prompt) > 2500:
            raise CloudError("Keep the prompt under 2,500 characters.")
        est = estimate(model, provider, duration, resolution, audio)
        if abs(est - float(confirmed_cost)) > 0.005:
            raise CloudError(f"The price changed to about ${est:.2f}. Check it and send again.")
        take = db.insert_take({
            "id": uuid.uuid4().hex, "created_at": time.time(), "status": "sending", "project": project,
            "provider": provider, "model": m["id"], "prompt": prompt, "duration": duration,
            "resolution": resolution, "audio": audio, "frame_path": str(frame),
            "source_job_id": source_job_id, "source_time": source_time, "est_cost": est, "favorite": False,
        })
        self.emit(take)
        self._spawn(take["id"])
        return take

    def _spawn(self, take_id: str) -> None:
        task = asyncio.create_task(self._run(take_id))
        self.tasks[take_id] = task
        task.add_done_callback(lambda _t: self.tasks.pop(take_id, None))

    def _set(self, take_id: str, **fields: Any) -> dict[str, Any] | None:
        if "error" in fields and fields["error"]:
            fields["error"] = redact(fields["error"])[:600]
        t = db.update_take(take_id, **fields)
        self.emit(t)
        return t

    async def _run(self, take_id: str) -> None:
        t = db.get_take(take_id)
        if not t:
            return
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                if not t["remote_id"]:
                    t = await self._submit(client, t)
                await self._poll(client, t)
        except asyncio.CancelledError:
            raise
        except CloudError as e:
            self._set(take_id, status="failed", finished_at=time.time(), error=str(e))
        except Exception as e:  # noqa: BLE001
            log.warning("take %s failed: %s", take_id[:8], redact(e))
            self._set(take_id, status="failed", finished_at=time.time(),
                      error=f"Lost touch with {t['provider']}: {redact(e)}. Check the provider dashboard before re-sending.")

    async def _submit(self, client: httpx.AsyncClient, t: dict[str, Any]) -> dict[str, Any]:
        m = model_def(t["model"])
        inp = build_input(m, t["provider"], data_uri(Path(t["frame_path"])), t["prompt"], int(t["duration"]),
                          t["resolution"], bool(t["audio"]))
        url = submit_url(m, t["provider"], t["resolution"])
        headers = {**_auth(t["provider"]), "Content-Type": "application/json"}
        if t["provider"] == "fal":
            r = await client.post(url, json=inp, headers=headers)
            if r.status_code >= 400:
                raise CloudError(f"fal.ai refused the shot ({_explain(r)}). Nothing should be charged.")
            body = r.json()
            fields = {"remote_id": body.get("request_id"), "status_url": body.get("status_url"),
                      "result_url": body.get("response_url"), "cancel_url": body.get("cancel_url")}
        else:
            r = await client.post(url, json={"input": inp}, headers=headers)
            if r.status_code >= 400:
                raise CloudError(f"Replicate refused the shot ({_explain(r)}). Nothing should be charged.")
            body = r.json()
            urls = body.get("urls") or {}
            fields = {"remote_id": body.get("id"), "status_url": urls.get("get"), "result_url": urls.get("get"),
                      "cancel_url": urls.get("cancel")}
        if not fields["remote_id"] or not fields["status_url"]:
            raise CloudError(f"{t['provider']} accepted the shot but sent back no way to follow it. Check its dashboard.")
        log.info("take %s sent to %s (%s)", t["id"][:8], t["provider"], t["model"])
        return self._set(t["id"], status="queued", **fields)  # type: ignore[return-value]

    async def _poll(self, client: httpx.AsyncClient, t: dict[str, Any]) -> None:
        provider = t["provider"]
        while True:
            if time.time() - t["created_at"] > GIVE_UP_SECONDS:
                raise CloudError(f"No result after {GIVE_UP_SECONDS // 60} minutes. It may still finish (and bill) on "
                                 f"{provider}; check its dashboard.")
            r = await client.get(_api_url(provider, t["status_url"]), headers=_auth(provider))
            if r.status_code >= 500:
                await asyncio.sleep(POLL_SECONDS * 2)
                continue
            if r.status_code >= 400 and r.status_code not in (202,):
                raise CloudError(f"{provider} stopped answering about this take ({_explain(r)}).")
            body = r.json() if r.content else {}
            if provider == "fal":
                state = str(body.get("status", "")).upper()
                if state == "IN_PROGRESS" and t["status"] != "running":
                    t = self._set(t["id"], status="running") or t
                if state == "COMPLETED":
                    res = await client.get(_api_url(provider, t["result_url"]), headers=_auth(provider))
                    if res.status_code >= 400:
                        raise CloudError(f"fal.ai couldn't make this take ({_explain(res)}).")
                    url = _video_url(res.json())
                    if not url:
                        raise CloudError("fal.ai finished but sent no video back.")
                    await self._finish(client, t, url)
                    return
            else:
                state = str(body.get("status", ""))
                if state == "processing" and t["status"] != "running":
                    t = self._set(t["id"], status="running") or t
                if state == "succeeded":
                    url = _video_url(body.get("output"))
                    if not url:
                        raise CloudError("Replicate finished but sent no video back.")
                    await self._finish(client, t, url)
                    return
                if state == "failed":
                    raise CloudError(f"Replicate couldn't make this take: {redact(body.get('error') or 'no reason given')}")
                if state == "canceled":
                    self._set(t["id"], status="cancelled", finished_at=time.time())
                    return
            await asyncio.sleep(POLL_SECONDS)

    async def _finish(self, client: httpx.AsyncClient, t: dict[str, Any], url: str) -> None:
        u = urlparse(url)
        if u.scheme != "https" or not u.hostname:
            raise CloudError("The provider sent back a video link the Studio won't open.")
        s = config.settings()
        from .runner import slug
        folder = Path(s["output_dir"]) / slug(t["project"] or "unsorted") / "cloud"
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{t['model']}_{t['id'][:8]}"
        dest = folder / f"{stem}.mp4"
        part = dest.with_suffix(".part")
        size = 0
        # No key on the download: the file link is the provider's public delivery URL.
        async with client.stream("GET", url, follow_redirects=True, timeout=300.0) as r:
            if r.status_code >= 400:
                raise CloudError(f"Couldn't download the finished take (HTTP {r.status_code}). It's still on "
                                 f"{t['provider']} for a while; check its dashboard.")
            with part.open("wb") as f:
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise CloudError("The finished take was larger than expected; download stopped.")
                    f.write(chunk)
        part.rename(dest)
        thumb = dest.with_suffix(".jpg")
        if not await asyncio.to_thread(system.make_thumbnail, dest, thumb):
            thumb = None  # type: ignore[assignment]
        finished = time.time()
        side = dest.with_suffix(".json")
        side.write_text(json.dumps({
            "studio": "Watson Factor AI Studio", "kind": "cloud", "take_id": t["id"], "project": t["project"],
            "provider": t["provider"], "model": t["model"], "prompt": t["prompt"], "duration": t["duration"],
            "resolution": t["resolution"], "audio": bool(t["audio"]), "frame": t["frame_path"],
            "source_job_id": t["source_job_id"], "source_time": t["source_time"], "remote_id": t["remote_id"],
            "est_cost_usd": t["est_cost"], "created_at": datetime.fromtimestamp(t["created_at"]).isoformat(),
            "finished_at": datetime.fromtimestamp(finished).isoformat(),
        }, indent=2))
        self._set(t["id"], status="done", finished_at=finished, output_path=str(dest),
                  thumb_path=str(thumb) if thumb else None, sidecar_path=str(side), error=None)
        log.info("take %s done (%s)", t["id"][:8], dest.name)

    async def cancel(self, take_id: str) -> dict[str, Any] | None:
        t = db.get_take(take_id)
        if not t or t["status"] not in ACTIVE:
            return t
        task = self.tasks.get(take_id)
        if task:
            task.cancel()
        note = None
        if t.get("cancel_url"):
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    url = _api_url(t["provider"], t["cancel_url"])
                    if t["provider"] == "fal":
                        r = await client.put(url, headers=_auth(t["provider"]))
                    else:
                        r = await client.post(url, headers=_auth(t["provider"]))
                if r.status_code >= 400:
                    note = f"{t['provider']} may already have started it, so it can still bill."
            except (httpx.HTTPError, CloudError):
                note = f"Couldn't reach {t['provider']} to stop it, so it can still bill."
        return self._set(take_id, status="cancelled", finished_at=time.time(), error=note)


def restore_take(meta: dict[str, Any], side: Path) -> bool:
    """Rebuild a take from its JSON sidecar (Library rescan). Returns True when one was added."""
    if not meta.get("take_id") or db.get_take(meta["take_id"]):
        return False
    video = side.with_suffix(".mp4")
    if not video.exists():
        return False
    thumb = side.with_suffix(".jpg")
    ts = lambda v: datetime.fromisoformat(v).timestamp() if v else time.time()  # noqa: E731
    db.insert_take({
        "id": meta["take_id"], "created_at": ts(meta.get("created_at")), "finished_at": ts(meta.get("finished_at")),
        "status": "done", "project": meta.get("project"), "provider": meta.get("provider"), "model": meta.get("model"),
        "prompt": meta.get("prompt"), "duration": meta.get("duration"), "resolution": meta.get("resolution"),
        "audio": bool(meta.get("audio")), "frame_path": meta.get("frame"), "source_job_id": meta.get("source_job_id"),
        "source_time": meta.get("source_time"), "remote_id": meta.get("remote_id"), "output_path": str(video),
        "thumb_path": str(thumb) if thumb.exists() else None, "sidecar_path": str(side),
        "est_cost": meta.get("est_cost_usd"), "favorite": False,
    })
    return True
