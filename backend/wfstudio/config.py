"""Settings, presets and manifest loading.

settings.json holds defaults (committed). settings.local.json holds Daniel's
overrides from the Settings screen (git-ignored). Environment variables win
over both, which is how the dev/test harness points the app at a fake SSD.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "studio" / "config"
TEMPLATE_DIR = REPO_ROOT / "studio" / "templates"
DATA_DIR = Path(os.environ.get("WFSTUDIO_DATA_DIR", REPO_ROOT / "data"))
LOG_DIR = REPO_ROOT / "logs"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
LAUNCH_DIR = REPO_ROOT / "launch"

_LOCAL = CONFIG_DIR / "settings.local.json"
_lock = threading.Lock()

ENV_OVERRIDES = {
    "ssd_root": "WFSTUDIO_SSD_ROOT",
    "comfy_url": "WFSTUDIO_COMFY_URL",
    "comfy_dir": "WFSTUDIO_COMFY_DIR",
    "studio_port": "WFSTUDIO_PORT",
}

EDITABLE = {
    "ssd_root", "models_dir", "output_dir", "inputs_dir", "comfy_url",
    "comfy_dir", "default_project", "default_preset", "default_length", "min_free_gb",
}


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def raw_settings() -> dict[str, Any]:
    s = _read(CONFIG_DIR / "settings.json")
    s.update(_read(_LOCAL))
    for key, env in ENV_OVERRIDES.items():
        if os.environ.get(env):
            val: Any = os.environ[env]
            if key == "studio_port":
                val = int(val)
            s[key] = val
    return s


def settings() -> dict[str, Any]:
    """Settings with {ssd_root} placeholders and ~ expanded."""
    s = raw_settings()
    root = os.path.expanduser(s["ssd_root"])
    s["ssd_root"] = root
    for key in ("models_dir", "output_dir", "inputs_dir", "comfy_dir"):
        s[key] = os.path.expanduser(str(s[key]).replace("{ssd_root}", root))
    s["comfy_url"] = s["comfy_url"].rstrip("/")
    return s


def save_local(updates: dict[str, Any]) -> dict[str, Any]:
    clean = {k: v for k, v in updates.items() if k in EDITABLE}
    with _lock:
        local = _read(_LOCAL)
        local.update(clean)
        _LOCAL.write_text(json.dumps(local, indent=2))
    return settings()


def presets() -> dict[str, Any]:
    return _read(CONFIG_DIR / "presets.json")


def manifest() -> list[dict[str, Any]]:
    return _read(CONFIG_DIR / "models.manifest.json")["models"]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
