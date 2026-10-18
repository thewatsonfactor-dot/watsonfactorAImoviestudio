"""Checks the silent-failure guards without rendering anything.

    backend/.venv/bin/python dev/test_guards.py

1. Engine-log guard, against the real logs/comfyui.log: every past successful render must come out
   clean, and the Oct 17 Final (720p) render that produced a blank video must be flagged.
2. Video guard, against short synthetic clips made with ffmpeg: flat colours flagged, real picture passes.
3. Memory forecast: a one-off failure can't block a size that has rendered fine.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from wfstudio import guards, system  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {name} {info}")


# ---- 1. engine log
log_path = ROOT / "logs" / "comfyui.log"
print(f"engine log guard on {log_path}")
data = log_path.read_bytes() if log_path.exists() else b""
starts = [m.start() for m in re.finditer(rb"got prompt", data)]
if not starts:
    print("  SKIP  no engine log on this machine")
else:
    bounds = starts + [len(data)]
    runs = [(bounds[i], bounds[i + 1]) for i in range(len(starts))]
    flagged, clean = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (a, b) in enumerate(runs):
            seg = Path(tmp) / f"run{i}.log"
            seg.write_bytes(data[a:b])
            hit = guards.engine_log_problems(seg, 0)
            (flagged if hit else clean).append((i, hit, b"Prompt executed" in data[a:b]))
        print(f"  {len(runs)} runs in the log: {len(clean)} clean, {len(flagged)} flagged")
        check("at least one past render is flagged", len(flagged) >= 1)
        check("the flagged run(s) were ones the engine called successful ('Prompt executed')",
              all(ok for _, _, ok in flagged))
        for i, hit, _ in flagged:
            print(f"        run {i}: {hit['count']} GPU error lines, e.g. {hit['example']!r}")
        check("every other past render is clean (no false positives)", len(clean) == len(runs) - len(flagged))
        # Offset handling: scanning from the start of the last flagged run finds it; from EOF finds nothing.
        i_last = flagged[-1][0]
        whole = Path(tmp) / "whole.log"
        whole.write_bytes(data)
        check("offset at that run's start finds it", guards.engine_log_problems(whole, runs[i_last][0]) is not None)
        check("offset at end of log finds nothing", guards.engine_log_problems(whole, len(data)) is None)
        check("no offset recorded means 'can't check', not a failure", guards.engine_log_problems(whole, None) is None)

# ---- 2. video guard
print("video guard on synthetic clips")
ff = system.ffmpeg()
if not ff:
    print("  SKIP  ffmpeg not found")
else:
    def clip(tmp, name, src):
        out = Path(tmp) / name
        subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-t", "3", "-pix_fmt", "yuv420p",
                        "-c:v", "libx264", str(out)], check=True)
        return out
    with tempfile.TemporaryDirectory() as tmp:
        gray = clip(tmp, "gray.mp4", "color=c=gray:s=832x480:r=16")
        noisy_gray = clip(tmp, "noisy_gray.mp4", "color=c=gray:s=832x480:r=16,noise=alls=2:allf=t")
        real = clip(tmp, "real.mp4", "testsrc2=s=832x480:r=16")
        sky = clip(tmp, "gradient.mp4", "gradients=s=832x480:r=16:c0=0x203060:c1=0xe0c070")
        check("flat gray clip is flagged", guards.video_problems(gray, ff) is not None)
        check("near-flat gray with faint noise is flagged", guards.video_problems(noisy_gray, ff) is not None)
        check("clip with real picture content passes", guards.video_problems(real, ff) is None)
        check("smooth gradient (sky-like) passes", guards.video_problems(sky, ff) is None)
        check("no ffmpeg means 'can't check', not a failure", guards.video_problems(real, None) is None)

# ---- 3. memory forecast: one failure must not block a size that has rendered fine
print("memory forecast")
from wfstudio import db as _db, forecast  # noqa: E402
real = _db.token_history
try:
    _db.token_history = lambda: {"proven": 20800, "failed": [20800, 90000]}
    lim = forecast.limits()
    check("a failure at a size that also rendered fine is ignored", lim["failed"] != 20800, str(lim))
    check("Draft size (832x480x49) is not blocked by it", forecast.forecast(832, 480, 49)["level"] == "ok")
    check("the real 720p limit still blocks Final", forecast.forecast(1280, 720, 81)["level"] == "failed")
    _db.token_history = lambda: {"proven": None, "failed": []}
    check("with no history, the seeded profile still applies", forecast.forecast(1280, 720, 81)["level"] == "failed")
finally:
    _db.token_history = real

failed = results.count(False)
print(f"\n{len(results) - failed}/{len(results)} passed")
sys.exit(1 if failed else 0)
