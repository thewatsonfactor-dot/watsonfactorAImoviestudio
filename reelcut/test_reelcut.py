#!/usr/bin/env python3
"""Smoke test for reelcut: makes synthetic clips with ffmpeg and runs every command.

    python3 reelcut/test_reelcut.py           # temp folder, removed afterwards
    python3 reelcut/test_reelcut.py --keep    # keep outputs to look at them

Needs ffmpeg/ffprobe. Renders nothing from your footage.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RC = [sys.executable, str(HERE / "reelcut.py")]


def make_clip(path, seconds, w=1920, h=1080, audio=True, pattern="testsrc2"):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", f"{pattern}=size={w}x{h}:rate=24:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac"]
    subprocess.run(cmd + [str(path)], check=True)


def info(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration:stream=codec_type,width,height,r_frame_rate",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    d = json.loads(out.stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    return {"w": v["width"], "h": v["height"], "fps": v["r_frame_rate"],
            "dur": float(d["format"]["duration"]),
            "audio": any(s["codec_type"] == "audio" for s in d["streams"])}


def check(path, dur, tol=0.25):
    i = info(path)
    ok = i["w"] == 1080 and i["h"] == 1920 and i["fps"] == "30/1" and i["audio"] \
        and abs(i["dur"] - dur) <= tol
    print(f"{'PASS' if ok else 'FAIL'}  {Path(path).name}  {i}")
    return ok


def run(args):
    r = subprocess.run(RC + args, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit(f"reelcut {args[0]} failed")


def main():
    keep = "--keep" in sys.argv
    tmp = Path(tempfile.mkdtemp(prefix="reelcut_test_"))
    src = tmp / "src"
    out = tmp / "out"
    src.mkdir()
    make_clip(src / "shot.mp4", 6)
    make_clip(src / "bts.mp4", 8, w=1080, h=1920, pattern="smptebars")      # phone, vertical
    make_clip(src / "silent.mp4", 4, audio=False, pattern="testsrc")       # AI Studio clips are silent
    make_clip(src / "episode.mp4", 12)
    make_clip(src / "log.mp4", 5, pattern="rgbtestsrc")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src / "log.mp4"),
                    "-vf", "eq=contrast=1.5:saturation=1.8", "-c:a", "copy", str(src / "graded.mp4")], check=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=220:duration=30", str(src / "music.m4a")], check=True)

    results = []
    run(["stack", "--top", str(src / "shot.mp4"), "--bottom", str(src / "bts.mp4"),
         "--top-label", "THE SHOT", "--bottom-label", "THE SETUP",
         "--hook", "Same camera. No crew. Pitch black room.", "--out", str(out / "stack.mp4")])
    results.append(check(out / "stack.mp4", 6))

    recipe = {"hook": "I typed this. AI made this.", "shots": [
        {"prompt": "Slow dolly in on a balcony villa at dusk, warm practical lights, 35mm, "
                   "Colombian coast, cinematic haze", "clip": "src/shot.mp4", "seconds": 3},
        {"prompt": "Whiskey pours into a crystal glass, she watches him, shallow focus", "clip": "src/silent.mp4"},
    ]}
    (tmp / "recipe.json").write_text(json.dumps(recipe))
    run(["prompt", "--recipe", str(tmp / "recipe.json"), "--numbered",
         "--music", str(src / "music.m4a"), "--end-text", "Full prompt in comments", "--out", str(out / "prompt.mp4")])
    results.append(check(out / "prompt.mp4", 7, tol=0.4))

    run(["parts", "--input", str(src / "episode.mp4"), "--at", "0:04,0:08",
         "--hooks", "She poured his whiskey. He never checked the bottle.|He found the leak.|",
         "--end-texts", "Part 2 Saturday|Part 3 next week|", "--out-prefix", str(out / "farola")])
    for n in (1, 2, 3):
        results.append(check(out / f"farola_part{n}of3.mp4", 4))

    run(["wipe", "--before", str(src / "log.mp4"), "--after", str(src / "graded.mp4"),
         "--hook", "What the Pocket 4K actually records", "--out", str(out / "wipe.mp4")])
    results.append(check(out / "wipe.mp4", 5))

    run(["vertical", "--input", str(src / "silent.mp4"), "--fit", "blur", "--out", str(out / "vertical.mp4")])
    results.append(check(out / "vertical.mp4", 4))

    # error path: missing file gives a plain message, exit 1
    r = subprocess.run(RC + ["vertical", "--input", str(src / "nope.mp4"), "--out", str(out / "x.mp4")],
                       capture_output=True, text=True)
    ok = r.returncode == 1 and "File not found" in r.stderr
    print(f"{'PASS' if ok else 'FAIL'}  missing input -> {r.stderr.strip()}")
    results.append(ok)

    print(f"\n{sum(results)}/{len(results)} passed. Outputs: {out if keep else '(removed)'}")
    if not keep:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
