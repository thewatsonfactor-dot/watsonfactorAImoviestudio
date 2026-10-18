"""Will this render fit in memory on this Mac? A forecast from what has actually happened here.

Wan's memory use grows with the number of latent tokens: (width/16) x (height/16) x ((frames-1)/4 + 1).
Every finished render proves a size works; every render that hit a GPU out-of-memory proves a size
doesn't. presets.json "memory_profile" seeds both from the Oct 17 2026 tests, and the job history
moves them as more renders finish or fail.
"""
from __future__ import annotations

from typing import Any

from . import config, db


def latent_tokens(width: int, height: int, frames: int) -> int:
    return (int(width) // 16) * (int(height) // 16) * ((int(frames) - 1) // 4 + 1)


def limits() -> dict[str, int | None]:
    prof = config.presets().get("memory_profile") or {}
    hist = db.token_history()
    proven = max(filter(None, [prof.get("proven_ok_tokens"), hist["proven"]]), default=None)
    failed = min(filter(None, [prof.get("failed_tokens"), hist["failed"]]), default=None)
    return {"proven": proven, "failed": failed}


def forecast(width: int, height: int, frames: int) -> dict[str, Any]:
    tokens = latent_tokens(width, height, frames)
    lim = limits()
    proven, failed = lim["proven"], lim["failed"]
    if failed and tokens >= failed:
        level = "failed"
        message = (f"{width}×{height} at {frames} frames is as big as or bigger than a render that ran out of GPU "
                   "memory on this Mac (it came out blank). Pick Draft or Standard, or the Short length.")
    elif proven and tokens <= proven:
        level = "ok"
        message = "This size has rendered fine on this Mac before."
    else:
        level = "untested"
        more = f" ({round((tokens / proven - 1) * 100)}% bigger than anything that has rendered here)" if proven else ""
        message = (f"Untested size on this Mac{more}. It may run out of memory; if it does, the Studio marks it "
                   "failed instead of saving a blank clip.")
    return {"level": level, "tokens": tokens, "proven_tokens": proven, "failed_tokens": failed, "message": message}
