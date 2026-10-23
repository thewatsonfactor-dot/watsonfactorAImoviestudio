"""macOS helpers: memory pressure, disk space, Finder, Trash, system info.
Everything degrades gracefully on non-Mac machines (used for testing)."""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import psutil

IS_MAC = platform.system() == "Darwin"


def _sysctl(key: str) -> str | None:
    try:
        return subprocess.run(["sysctl", "-n", key], capture_output=True, text=True,
                              timeout=2).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def memory() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    level = "normal"
    if IS_MAC:
        # kern.memorystatus_vm_pressure_level: 1 normal, 2 warning, 4 critical
        raw = _sysctl("kern.memorystatus_vm_pressure_level")
        level = {"1": "normal", "2": "warning", "4": "critical"}.get(raw or "", "normal")
    else:
        level = "critical" if vm.percent > 95 else "warning" if vm.percent > 85 else "normal"
    return {"level": level, "used_percent": vm.percent,
            "total_gb": round(vm.total / 1e9, 1), "available_gb": round(vm.available / 1e9, 1)}


def swap_used_mb() -> float | None:
    """Swap in use, in MB (macOS vm.swapusage; psutil elsewhere)."""
    if IS_MAC:
        m = re.search(r"used = ([\d.]+)M", _sysctl("vm.swapusage") or "")
        if m:
            return float(m.group(1))
    try:
        return round(psutil.swap_memory().used / 2**20, 1)
    except OSError:
        return None


def mem_snapshot() -> dict[str, Any]:
    m = memory()
    return {"level": m["level"], "available_gb": m["available_gb"], "swap_used_mb": swap_used_mb()}


def disk(path: str) -> dict[str, Any] | None:
    try:
        u = shutil.disk_usage(path)
    except OSError:
        return None
    return {"total_gb": round(u.total / 1e9, 1), "free_gb": round(u.free / 1e9, 1),
            "used_gb": round(u.used / 1e9, 1)}


def ssd_state(root: str) -> dict[str, Any]:
    p = Path(root)
    mounted = p.exists() and (os.path.ismount(root) or not root.startswith("/Volumes/"))
    writable = mounted and os.access(root, os.W_OK)
    return {"path": root, "mounted": mounted, "writable": writable,
            "disk": disk(root) if mounted else None}


@lru_cache(maxsize=1)
def info() -> dict[str, Any]:
    chip = _sysctl("machdep.cpu.brand_string") if IS_MAC else platform.processor()
    mem = _sysctl("hw.memsize") if IS_MAC else None
    mac_ver = platform.mac_ver()[0] if IS_MAC else None
    return {
        "chip": chip or platform.machine(),
        "memory_gb": round(int(mem) / 2**30) if mem else round(psutil.virtual_memory().total / 2**30),
        "os": f"macOS {mac_ver}" if mac_ver else f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
    }


def reveal(path: str) -> bool:
    if not IS_MAC or not Path(path).exists():
        return False
    subprocess.Popen(["open", "-R", path])
    return True


def trash(path: str) -> None:
    from send2trash import send2trash
    if Path(path).exists():
        send2trash(path)


def ffmpeg() -> str | None:
    for candidate in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def make_thumbnail(video: Path, out: Path) -> bool:
    exe = ffmpeg()
    if not exe:
        return False
    try:
        subprocess.run([exe, "-y", "-loglevel", "error", "-i", str(video),
                        "-vf", "thumbnail,scale=640:-2", "-frames:v", "1", str(out)],
                       timeout=60, check=True)
        return out.exists()
    except (OSError, subprocess.SubprocessError):
        return False


def extract_last_frame(video: Path, out: Path) -> bool:
    """Grab a frame near the very end of a clip, to use as the next chain segment's keyframe.

    Seeks 0.3s before end-of-file rather than exactly to it: ffmpeg can return nothing when asked
    to decode right at EOF, and 0.3s (a handful of frames at 16fps) is close enough to be seamless."""
    exe = ffmpeg()
    if not exe:
        return False
    try:
        subprocess.run([exe, "-y", "-loglevel", "error", "-sseof", "-0.3", "-i", str(video),
                        "-update", "1", "-frames:v", "1", str(out)],
                       timeout=60, check=True)
        return out.exists()
    except (OSError, subprocess.SubprocessError):
        return False


def concat_videos(videos: list[Path], out: Path) -> bool:
    """Stitch finished chain segments into one clip. They all share codec/resolution/fps
    (same preset rendered every segment), so this is a stream copy — fast, no re-encode."""
    exe = ffmpeg()
    if not exe or not videos:
        return False
    import tempfile
    listfile: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            for v in videos:
                f.write(f"file '{v.resolve()}'\n")
            listfile = f.name
        subprocess.run([exe, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", listfile, "-c", "copy", str(out)], timeout=180, check=True)
        return out.exists()
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        if listfile:
            try:
                Path(listfile).unlink()
            except OSError:
                pass


def image_thumbnail(image: Path, out: Path) -> bool:
    """640px-wide JPEG of a still, matching make_thumbnail's size for videos."""
    try:
        from PIL import Image
        with Image.open(image) as im:
            im = im.convert("RGB")
            im.thumbnail((640, 640 * 4))
            im.save(out, "JPEG", quality=88)
        return out.exists()
    except Exception:  # noqa: BLE001
        return False
