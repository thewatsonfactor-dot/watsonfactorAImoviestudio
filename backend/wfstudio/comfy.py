"""Thin async client for the ComfyUI HTTP API (the engine)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from . import config


class EngineError(Exception):
    """The engine answered, but rejected the request."""

    def __init__(self, message: str, detail: Any = None):
        super().__init__(message)
        self.detail = detail


def base() -> str:
    return config.settings()["comfy_url"]


def ws_url(client_id: str) -> str:
    return base().replace("http://", "ws://").replace("https://", "wss://") + f"/ws?clientId={client_id}"


def _client(timeout: float = 10.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base(), timeout=timeout)


async def system_stats(timeout: float = 2.0) -> dict[str, Any] | None:
    try:
        async with _client(timeout) as c:
            r = await c.get("/system_stats")
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, ValueError):
        return None


async def object_info(node_class: str) -> dict[str, Any] | None:
    try:
        async with _client(15.0) as c:
            r = await c.get(f"/object_info/{node_class}")
            r.raise_for_status()
            return r.json().get(node_class)
    except (httpx.HTTPError, ValueError):
        return None


async def upload_image(path: Path, subfolder: str = "wfstudio") -> str:
    """Upload a keyframe; returns the name to put in LoadImage.image."""
    async with _client(60.0) as c:
        with path.open("rb") as f:
            r = await c.post("/upload/image",
                             files={"image": (path.name, f, "application/octet-stream")},
                             data={"subfolder": subfolder, "type": "input", "overwrite": "true"})
    if r.status_code != 200:
        raise EngineError(f"Engine refused the keyframe upload (HTTP {r.status_code})", r.text)
    d = r.json()
    return f"{d['subfolder']}/{d['name']}" if d.get("subfolder") else d["name"]


async def queue_prompt(prompt: dict[str, Any], client_id: str) -> str:
    async with _client(30.0) as c:
        r = await c.post("/prompt", json={"prompt": prompt, "client_id": client_id})
    if r.status_code != 200:
        try:
            body = r.json()
        except ValueError:
            body = {"error": {"message": r.text}}
        raise EngineError(plain_validation_error(body), body)
    return r.json()["prompt_id"]


async def interrupt(prompt_id: str) -> None:
    async with _client(5.0) as c:
        await c.post("/interrupt", json={"prompt_id": prompt_id})


async def delete_from_queue(prompt_id: str) -> None:
    async with _client(5.0) as c:
        await c.post("/queue", json={"delete": [prompt_id]})


async def history(prompt_id: str) -> dict[str, Any] | None:
    try:
        async with _client(10.0) as c:
            r = await c.get(f"/history/{prompt_id}")
            r.raise_for_status()
            return r.json().get(prompt_id)
    except (httpx.HTTPError, ValueError):
        return None


async def queue_state() -> dict[str, Any] | None:
    try:
        async with _client(5.0) as c:
            r = await c.get("/queue")
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, ValueError):
        return None


def plain_validation_error(body: dict[str, Any]) -> str:
    """Turn ComfyUI's /prompt validation errors into one readable sentence."""
    node_errors = body.get("node_errors") or {}
    for node_id, ne in node_errors.items():
        for err in ne.get("errors", []):
            details = err.get("details", "")
            msg = err.get("message", "")
            if "not in list" in msg.lower() or "value_not_in_list" in err.get("type", ""):
                return (f"The engine can't find a model file ({details}). "
                        "Check the Models screen and extra_model_paths.yaml.")
            return f"Workflow problem at node {node_id} ({ne.get('class_type', '?')}): {msg} {details}".strip()
    err = body.get("error") or {}
    msg = err.get("message") if isinstance(err, dict) else str(err)
    if msg and "missing_node_type" in str(err.get("type", "") if isinstance(err, dict) else ""):
        return f"The engine is missing a custom node: {msg}. Is ComfyUI-GGUF installed?"
    return msg or "The engine rejected the job."
