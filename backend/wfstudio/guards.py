"""Checks that catch renders the engine reports as successful but that are actually broken.

ComfyUI on Apple Metal can lose GPU memory mid-render ("kIOGPUCommandBufferCallbackErrorOutOfMemory"),
print the error, keep going, and finish with status "success" and a blank video. Two independent
checks, either of which fails the job:

  1. engine_log_problems  — the engine's own log, from where the job started, shows GPU errors.
  2. video_problems       — the finished file is flat (no picture content in any sampled frame).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

# Lines the engine prints when the GPU gave up on work. Any hit during a job means the output can't be trusted.
ENGINE_ERROR_MARKERS = (
    "kIOGPUCommandBufferCallbackErrorOutOfMemory",
    "command buffer exited with error status",
    "MPS backend out of memory",
)

# A real frame has dark and bright areas. If every sampled frame spans less than this
# many luma levels (0-255), the clip is a flat colour — i.e. blank.
FLAT_LUMA_RANGE = 24
MAX_LOG_SCAN_BYTES = 64 * 1024 * 1024


def log_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def scan_engine_text(text: str) -> dict[str, Any]:
    """Count GPU-error lines in a chunk of engine log."""
    hits = [ln.strip() for ln in text.splitlines() if any(m in ln for m in ENGINE_ERROR_MARKERS)]
    return {"count": len(hits), "example": hits[0][:200] if hits else None}


def engine_log_problems(path: Path, start_offset: int | None) -> dict[str, Any] | None:
    """Scan the engine log from `start_offset` to the end. None means clean or not checkable."""
    if start_offset is None:
        return None
    try:
        size = path.stat().st_size
        if size < start_offset:  # log was rotated or truncated: scan what's there
            start_offset = 0
        with path.open("rb") as f:
            f.seek(max(start_offset, size - MAX_LOG_SCAN_BYTES))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    found = scan_engine_text(text)
    return found if found["count"] else None


def video_stats(video: Path, ffmpeg_exe: str) -> list[tuple[float, float]]:
    """(min, max) luma of ~2 frames per second of video."""
    proc = subprocess.run(
        [ffmpeg_exe, "-v", "error", "-i", str(video), "-an",
         "-vf", "fps=2,signalstats,metadata=print:file=-", "-f", "null", "-"],
        capture_output=True, text=True, timeout=120)
    lows = [float(x) for x in re.findall(r"lavfi\.signalstats\.YMIN=([\d.]+)", proc.stdout)]
    highs = [float(x) for x in re.findall(r"lavfi\.signalstats\.YMAX=([\d.]+)", proc.stdout)]
    return list(zip(lows, highs))


def video_problems(video: Path, ffmpeg_exe: str | None) -> dict[str, Any] | None:
    """None if the clip has picture content (or can't be checked); otherwise why it's blank."""
    if not ffmpeg_exe:
        return None
    try:
        frames = video_stats(video, ffmpeg_exe)
    except (OSError, subprocess.SubprocessError):
        return None
    if not frames:
        return {"reason": "no frames could be read", "frames_checked": 0}
    widest = max(hi - lo for lo, hi in frames)
    if widest < FLAT_LUMA_RANGE:
        return {"reason": "every sampled frame is a flat colour", "frames_checked": len(frames),
                "widest_luma_range": widest}
    return None


GPU_ERROR_MESSAGE = (
    "The GPU ran out of memory partway through this render. The engine hid the error and called it "
    "a success, but the video can't be trusted, so it was not saved to the Library. Try Draft or "
    "Standard with Short length, quit other apps, and Re-roll. 720p (Final) is known to do this on 36 GB.")
BLANK_MESSAGE = (
    "The render finished, but the video is blank (every frame is one flat colour), so it was not "
    "saved to the Library. This is most often the GPU running out of memory. Try a lighter "
    "quality or length, quit other apps, and Re-roll.")
