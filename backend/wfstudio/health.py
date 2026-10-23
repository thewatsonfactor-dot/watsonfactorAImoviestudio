"""The four status pills: Engine, Models, SSD, Memory — plus pre-flight."""
from __future__ import annotations

import time
from typing import Any

from . import comfy, config, models, system, workflow

_wf_cache: dict[str, dict[str, Any]] = {}


async def _workflow_problems(name: str, engine_started: Any) -> list[str] | None:
    """Validate a template against the engine; cached per template, refreshed every 60s or on engine restart."""
    now = time.time()
    c = _wf_cache.get(name)
    if c and c["problems"] is not None and now - c["at"] < 60 and c["engine_started"] == engine_started:
        return c["problems"]
    problems = await workflow.validate(name)
    _wf_cache[name] = {"at": now, "problems": problems, "engine_started": engine_started}
    return problems


def invalidate() -> None:
    _wf_cache.clear()


def _group(ms: dict[str, Any], name: str) -> dict[str, Any]:
    return ms.get("groups", {}).get(name) or {"present": 0, "total": 0, "missing_gb": 0}


async def check() -> dict[str, Any]:
    s = config.settings()
    stats = await comfy.system_stats()

    # Engine
    if stats is None:
        engine = {"level": "red", "label": "Engine", "blocking": True,
                  "reason": "Engine not running — use Start engine, or relaunch the Studio app."}
        device = None
    else:
        dev = (stats.get("devices") or [{}])[0]
        device = dev.get("type")
        ver = stats.get("system", {}).get("comfyui_version", "")
        if device == "mps":
            engine = {"level": "green", "label": "Engine", "blocking": False,
                      "reason": f"ComfyUI {ver} running on Apple Metal."}
        else:
            engine = {"level": "amber", "label": "Engine", "blocking": False,
                      "reason": f"ComfyUI {ver} is running on {device or 'unknown device'}, not Metal — renders will be very slow."}

    # SSD
    ssd = system.ssd_state(s["ssd_root"])
    free = (ssd["disk"] or {}).get("free_gb", 0)
    if not ssd["mounted"]:
        ssd_pill = {"level": "red", "label": "SSD", "blocking": True,
                    "reason": f"SSD not connected — plug in {ssd['path'].rstrip('/').split('/')[-1]}."}
    elif not ssd["writable"]:
        ssd_pill = {"level": "red", "label": "SSD", "blocking": True,
                    "reason": "SSD is read-only — check it's formatted APFS and not locked."}
    elif free < s["min_free_gb"]:
        ssd_pill = {"level": "red", "label": "SSD", "blocking": True,
                    "reason": f"Only {free:.0f} GB free on the SSD — need {s['min_free_gb']} GB to render."}
    else:
        ssd_pill = {"level": "green", "label": "SSD", "blocking": False,
                    "reason": f"{free:.0f} GB free on the SSD."}

    # Models (+ workflow validation when the engine is up). The pill covers the video models
    # (Create); the image models (Image screen) are reported separately and never block video.
    ms = models.status() if ssd["mounted"] else {"present": 0, "total": len(config.manifest()), "missing_gb": 0}
    vid = _group(ms, "video")
    wf_problems: list[str] = []
    if not workflow.exists(s["workflow"]):
        wf_problems = [f"Workflow template '{s['workflow']}' is missing."]
    elif stats is not None:
        # Re-validate whenever the SSD or model set changes, not just every 60s.
        wf_problems = await _workflow_problems(s["workflow"], (ssd["mounted"], vid["present"])) or []
    if not ssd["mounted"]:
        models_pill = {"level": "red", "label": "Models", "blocking": True,
                       "reason": "Can't check models until the SSD is connected."}
    elif vid["present"] < vid["total"]:
        models_pill = {"level": "red", "label": "Models", "blocking": True,
                       "reason": f"{vid['total'] - vid['present']} of {vid['total']} video model files missing "
                                 f"({vid['missing_gb']} GB) — see the Models screen."}
    elif wf_problems:
        models_pill = {"level": "red", "label": "Models", "blocking": True, "reason": wf_problems[0]}
    else:
        models_pill = {"level": "green", "label": "Models", "blocking": False,
                       "reason": f"All {vid['total']} video model files present."}

    # Image generation (Qwen): its own readiness, so it can be ready while video isn't and vice versa.
    img = _group(ms, "image")
    img_wf = s.get("image_workflow", "qwen_image_edit")
    img_problems: list[str] = []
    if not ssd["mounted"]:
        img_reason = ssd_pill["reason"]
    elif stats is None:
        img_reason = engine["reason"]
    elif img["present"] < img["total"]:
        img_reason = (f"{img['total'] - img['present']} of {img['total']} image model files missing "
                      f"({img['missing_gb']} GB) — download them on the Models screen.")
    elif not workflow.exists(img_wf):
        img_reason = f"Workflow template '{img_wf}' is missing."
    else:
        img_problems = await _workflow_problems(img_wf, (ssd["mounted"], img["present"])) or []
        img_reason = img_problems[0] if img_problems else None
    if img_reason is None and free < s["min_free_gb"]:
        img_reason = ssd_pill["reason"]
    image = {"ready": img_reason is None, "reason": img_reason, "present": img["present"],
             "total": img["total"], "missing_gb": img["missing_gb"], "workflow_problems": img_problems}

    # Memory (never blocks — warns)
    mem = system.memory()
    if mem["level"] == "critical":
        mem_pill = {"level": "red", "label": "Memory", "blocking": False,
                    "reason": "Memory pressure is critical — close Chrome tabs and other apps before rendering."}
    elif mem["level"] == "warning":
        mem_pill = {"level": "amber", "label": "Memory", "blocking": False,
                    "reason": "Memory is getting tight — close Chrome tabs and other apps before rendering."}
    else:
        mem_pill = {"level": "green", "label": "Memory", "blocking": False,
                    "reason": f"{mem['available_gb']} GB available."}

    pills = {"engine": engine, "models": models_pill, "ssd": ssd_pill, "memory": mem_pill}
    # Most actionable first: a missing SSD explains missing models.
    order = ("ssd", "engine", "models", "memory")
    blockers = [pills[k]["reason"] for k in order if pills[k]["blocking"]]
    return {
        "pills": pills,
        "can_generate": not blockers,
        "blocked_reason": blockers[0] if blockers else None,
        "workflow_problems": wf_problems,
        "image": image,
        "engine": {"up": stats is not None, "device": device,
                   "comfyui_version": (stats or {}).get("system", {}).get("comfyui_version"),
                   "pytorch_version": (stats or {}).get("system", {}).get("pytorch_version")},
        "disk": {"internal": system.disk("/"), "ssd": ssd["disk"]},
        "memory": mem,
        "system": system.info(),
        "checked_at": time.time(),
    }
