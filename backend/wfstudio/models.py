"""Model manifest checks and confirmed, one-at-a-time downloads from Hugging Face."""
from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Any

from . import config

_downloads: dict[str, dict[str, Any]] = {}
_dl_lock = threading.Lock()
_one_at_a_time = threading.Lock()


def _path(m: dict[str, Any]) -> Path:
    return Path(config.settings()["models_dir"]) / m["folder"] / m["filename"]


def status() -> dict[str, Any]:
    items = []
    for m in config.manifest():
        p = _path(m)
        size = p.stat().st_size if p.exists() else 0
        if not p.exists():
            state = "missing"
        elif m.get("size_bytes") and abs(size - m["size_bytes"]) > m["size_bytes"] * 0.01:
            state = "wrong_size"
        else:
            state = "present"
        dl = _downloads.get(m["id"])
        items.append({**m, "path": str(p), "state": state, "size_on_disk": size,
                      "download": dl if dl and dl["state"] in ("queued", "downloading", "failed") else None})
    def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        need = sum(i["size_bytes"] for i in rows if i["state"] != "present")
        return {"present": sum(1 for i in rows if i["state"] == "present"), "total": len(rows),
                "missing_gb": round(need / 1e9, 1)}

    # Each group gates its own screen: video models -> Create, image models -> Image.
    groups = {g: summary([i for i in items if i["group"] == g]) for g in sorted({i["group"] for i in items})}
    return {"models": items, **summary(items), "groups": groups}


def _staging_bytes(staging: Path) -> int:
    total = 0
    if staging.exists():
        for f in staging.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    return total


def _worker(model_id: str) -> None:
    from huggingface_hub import hf_hub_download

    m = next(x for x in config.manifest() if x["id"] == model_id)
    dest = _path(m)
    staging = Path(config.settings()["models_dir"]) / ".downloads" / model_id
    staging.mkdir(parents=True, exist_ok=True)
    state = _downloads[model_id]
    state.update(state="downloading", started_at=time.time())

    stop = threading.Event()

    def poll() -> None:
        while not stop.wait(1.0):
            state["bytes"] = _staging_bytes(staging)

    poller = threading.Thread(target=poll, daemon=True)
    poller.start()
    try:
        got = hf_hub_download(repo_id=m["repo"], filename=m["repo_path"], local_dir=str(staging))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(got, dest)
        shutil.rmtree(staging, ignore_errors=True)
        state.update(state="done", bytes=m["size_bytes"], finished_at=time.time())
    except Exception as e:  # noqa: BLE001 — surface any failure to the UI
        state.update(state="failed", error=str(e))
    finally:
        stop.set()


def start_download(model_id: str) -> dict[str, Any]:
    m = next((x for x in config.manifest() if x["id"] == model_id), None)
    if m is None:
        raise KeyError(model_id)
    with _dl_lock:
        cur = _downloads.get(model_id)
        if cur and cur["state"] in ("queued", "downloading"):
            return cur
        _downloads[model_id] = {"id": model_id, "state": "queued", "bytes": 0,
                                "total": m["size_bytes"], "error": None}
    # One at a time: each download waits its turn on a single lock.
    def run() -> None:
        with _one_at_a_time:
            _worker(model_id)

    threading.Thread(target=run, daemon=True).start()
    return _downloads[model_id]
