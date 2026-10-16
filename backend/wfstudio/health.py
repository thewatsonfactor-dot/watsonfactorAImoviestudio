"""The four status pills: Engine, Models, SSD, Memory — plus pre-flight."""
from __future__ import annotations

import time
from typing import Any

from . import comfy, config, models, system, workflow

_wf_cache: dict[str, Any] = {"at": 0.0, "problems": None, "engine_started": None}


async def _workflow_problems(engine_started: Any) -> list[str] | None:
    """Validate the template against the engine; cached, refreshed every 60s or on engine restart."""
    now = time.time()
    if (_wf_cache["problems"] is not None and now - _wf_cache["at"] < 60
            and _wf_cache["engine_started"] == engine_started):
        return _wf_cache["problems"]
    problems = await workflow.validate(config.settings()["workflow"])
    _wf_cache.update(at=now, problems=problems, engine_started=engine_started)
    return problems


def invalidate() -> None:
    _wf_cache["problems"] = None


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

    # Models (+ workflow validation when the engine is up)
    ms = models.status() if ssd["mounted"] else {"present": 0, "total": len(config.manifest()), "missing_gb": 0}
    wf_problems: list[str] = []
    if not workflow.exists(s["workflow"]):
        wf_problems = [f"Workflow template '{s['workflow']}' is missing."]
    elif stats is not None:
        # Re-validate whenever the SSD or model set changes, not just every 60s.
        wf_problems = await _workflow_problems((ssd["mounted"], ms["present"])) or []
    if not ssd["mounted"]:
        models_pill = {"level": "red", "label": "Models", "blocking": True,
                       "reason": "Can't check models until the SSD is connected."}
    elif ms["present"] < ms["total"]:
        models_pill = {"level": "red", "label": "Models", "blocking": True,
                       "reason": f"{ms['total'] - ms['present']} of {ms['total']} model files missing "
                                 f"({ms['missing_gb']} GB) — see the Models screen."}
    elif wf_problems:
        models_pill = {"level": "red", "label": "Models", "blocking": True, "reason": wf_problems[0]}
    else:
        models_pill = {"level": "green", "label": "Models", "blocking": False,
                       "reason": f"All {ms['total']} model files present."}

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
        "engine": {"up": stats is not None, "device": device,
                   "comfyui_version": (stats or {}).get("system", {}).get("comfyui_version"),
                   "pytorch_version": (stats or {}).get("system", {}).get("pytorch_version")},
        "disk": {"internal": system.disk("/"), "ssd": ssd["disk"]},
        "memory": mem,
        "system": system.info(),
        "checked_at": time.time(),
    }
