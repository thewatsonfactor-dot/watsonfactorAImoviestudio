"""Workflow templates: load the API-format JSON exported from ComfyUI, inject
job parameters through the .map.json, and validate the template against what
the running engine actually has installed."""
from __future__ import annotations

import copy
import json
from typing import Any

from . import comfy, config


def _paths(name: str) -> tuple[Any, Any]:
    api = config.TEMPLATE_DIR / f"{name}.api.json"
    mp = config.TEMPLATE_DIR / f"{name}.map.json"
    return api, mp


def exists(name: str) -> bool:
    api, mp = _paths(name)
    return api.exists() and mp.exists()


def load(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    api, mp = _paths(name)
    return json.loads(api.read_text()), json.loads(mp.read_text())


def _set(prompt: dict[str, Any], targets: list[list[str]], value: Any) -> None:
    for node_id, input_name in targets:
        prompt[node_id]["inputs"][input_name] = value


def build(name: str, params: dict[str, Any]) -> dict[str, Any]:
    api, mp = load(name)
    prompt = copy.deepcopy(api)
    for key, value in params.items():
        if key in mp["params"] and value is not None:
            _set(prompt, mp["params"][key], value)
    models = {m["id"]: m["filename"] for m in config.manifest()}
    for model_id, targets in mp.get("models", {}).items():
        if model_id in models:
            _set(prompt, targets, models[model_id])
    return prompt


def stage_map(name: str) -> dict[str, str]:
    _, mp = load(name)
    return mp.get("stages", {})


def output_node(name: str) -> str | None:
    _, mp = load(name)
    return mp.get("output_node")


def dimensions(orientation: str, tier: str) -> tuple[int, int]:
    tiers = config.presets()["tiers"]
    w, h = tiers[tier][orientation]
    return int(w), int(h)


def orientation_for(width: int, height: int) -> str:
    ratio = width / max(height, 1)
    if ratio > 1.15:
        return "landscape"
    if ratio < 0.87:
        return "portrait"
    return "square"


def snap16(v: int) -> int:
    return max(16, int(round(v / 16)) * 16)


async def validate(name: str) -> list[str]:
    """Check the template against the live engine. Returns plain-English problems."""
    if not exists(name):
        return [f"Workflow template '{name}' is missing from studio/templates."]
    api, mp = load(name)
    problems: list[str] = []
    info_cache: dict[str, Any] = {}
    for node_id, node in api.items():
        cls = node["class_type"]
        if cls not in info_cache:
            info_cache[cls] = await comfy.object_info(cls)
        info = info_cache[cls]
        if info is None:
            hint = " (install ComfyUI-GGUF)" if "GGUF" in cls else ""
            problems.append(f"Engine is missing the '{cls}' node{hint}.")
            continue
        declared = {**info.get("input", {}).get("required", {}), **info.get("input", {}).get("optional", {})}
        for input_name in node["inputs"]:
            if "." in input_name:  # dynamic sub-inputs (e.g. SaveVideo format.codec)
                continue
            if input_name not in declared:
                problems.append(f"Node {node_id} ({cls}) has no input '{input_name}' in this engine version.")
    # Every mapped target must point at a real node.
    for key, targets in {**mp["params"], **mp.get("models", {})}.items():
        for node_id, _ in targets:
            if node_id not in api:
                problems.append(f"Map entry '{key}' points at node {node_id}, which isn't in the workflow.")
    # Model files the engine can actually see.
    models = {m["id"]: m for m in config.manifest()}
    for model_id, targets in mp.get("models", {}).items():
        m = models.get(model_id)
        if not m:
            continue
        for node_id, input_name in targets:
            info = info_cache.get(api[node_id]["class_type"])
            if not info:
                continue
            spec = {**info.get("input", {}).get("required", {}),
                    **info.get("input", {}).get("optional", {})}.get(input_name)
            options = None
            if spec and isinstance(spec[0], list):
                options = spec[0]
            elif spec and spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
                options = spec[1].get("options")
            if options is not None and m["filename"] not in options:
                problems.append(f"Engine can't see {m['filename']} — check the file is in "
                                f"{m['folder']}/ and extra_model_paths.yaml points at the SSD.")
    return problems
