#!/usr/bin/env python3
"""Reelcut: turn finished footage into vertical Reels / Shorts with ffmpeg.

Standalone. Needs only Python 3.9+ and ffmpeg/ffprobe on PATH
(on the Mac: `brew install ffmpeg`). Nothing here talks to the network,
posts, or uploads; it only writes mp4 files to the path you give it.

Commands (run `python3 reelcut.py <command> -h` for every option):

  stack   Two clips, one above the other (setup vs. the shot).
  prompt  Prompt vs. the shot: the prompt types out on top, the shot plays below.
          Takes several prompt/clip pairs and joins them into one Reel.
  parts   Cut one video into N parts (or at timestamps), reframed to 9:16,
          each labelled "PART 1 / 3" with an optional end card.
  wipe    LOG vs. graded: a wipe from one clip to the other.
  vertical  One clip reframed to 9:16 (crop or blurred fill).
  scan    List the video files in a folder (e.g. your external drive) with
          length, size and codec, and flag the ones that need exporting first.

Every export is 1080x1920, 30 fps, H.264 + AAC, faststart: one clean file
that works as an Instagram Reel and a YouTube Short (no platform watermark).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

W, H = 1080, 1920
HALF_H = H // 2
FPS = 30

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]
MONO_CANDIDATES = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
]


# Camera RAW formats ffmpeg can't decode. Export these from Resolve first.
RAW_FORMATS = {
    ".braw": "Blackmagic RAW",
    ".r3d": "RED RAW",
    ".ari": "ARRIRAW",
    ".arx": "ARRIRAW",
    ".crm": "Canon Cinema RAW Light",
    ".dng": "CinemaDNG",
}
RAW_CODECS = {"prores_raw": "ProRes RAW"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mxf", ".mkv", ".avi", ".mts", ".m2ts", *RAW_FORMATS}
EXPORT_HINT = ("export it from DaVinci Resolve first (Deliver page, H.264 or ProRes 422, "
               "same in and out points) and point Reelcut at the export")

# Where macOS mounts external drives. Overridable only so the tests can fake it.
VOLUMES_ROOT = os.environ.get("REELCUT_VOLUMES_ROOT", "/Volumes")
ALLOW_SOURCE_DRIVE = False
SOURCES: set[str] = set()   # every clip probed in this run, for the source-drive guard


class ReelcutError(Exception):
    pass


# ---------------------------------------------------------------- helpers

def need_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise ReelcutError(f"{tool} not found. On the Mac: brew install ffmpeg")


def pick_font(explicit: str | None, candidates: list[str]) -> str:
    if explicit:
        if not Path(explicit).exists():
            raise ReelcutError(f"Font not found: {explicit}")
        return explicit
    for c in candidates:
        if Path(c).exists():
            return c
    raise ReelcutError("No usable font found. Pass one with --font /path/to/font.ttf")


def probe(path: str) -> dict:
    if not Path(path).exists():
        hint = ""
        if str(path).startswith(VOLUMES_ROOT + "/"):
            hint = (" (is the external drive plugged in? `ls /Volumes` shows the drives "
                    "that are mounted)")
        raise ReelcutError(f"File not found: {path}{hint}")
    SOURCES.add(str(path))
    raw = RAW_FORMATS.get(Path(path).suffix.lower())
    if raw:
        raise ReelcutError(f"{path} is {raw}, which ffmpeg can't read: {EXPORT_HINT}.")
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
         "-of", "json", path],
        capture_output=True, text=True)
    if out.returncode != 0:
        raise ReelcutError(f"ffprobe could not read {path}: {out.stderr.strip()}. "
                           f"If it's camera RAW, {EXPORT_HINT}.")
    data = json.loads(out.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ReelcutError(f"No video stream in {path}")
    codec = video.get("codec_name") or "unknown"
    if codec in RAW_CODECS:
        raise ReelcutError(f"{path} is {RAW_CODECS[codec]}, which ffmpeg can't read: {EXPORT_HINT}.")
    return {
        "duration": float(data.get("format", {}).get("duration") or 0.0),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "audio": any(s.get("codec_type") == "audio" for s in streams),
        "codec": codec,
        "fps": video.get("r_frame_rate", ""),
    }


def drive_of(path: str) -> str | None:
    """/Volumes/<drive> for a path on an external drive, else None."""
    try:
        parts = Path(path).expanduser().resolve().parts
    except OSError:
        parts = Path(path).expanduser().absolute().parts
    root = Path(VOLUMES_ROOT).resolve().parts
    if len(parts) > len(root) and parts[:len(root)] == root:
        return str(Path(*parts[:len(root) + 1]))
    return None


def guard_output(ffmpeg_args: list[str], out: str) -> None:
    """Refuse to write onto the drive the footage is read from, unless allowed."""
    if ALLOW_SOURCE_DRIVE:
        return
    out_drive = drive_of(out)
    if out_drive is None:
        return
    sources = SOURCES | {ffmpeg_args[i + 1] for i, a in enumerate(ffmpeg_args[:-1])
                         if a == "-i" and Path(ffmpeg_args[i + 1]).exists()}
    if any(drive_of(src) == out_drive for src in sources):
        raise ReelcutError(
            f"{out} is on the same drive as your footage ({out_drive}). Write the Reel "
            f"somewhere else, e.g. ~/Movies/Reels/, or add --allow-source-drive if you "
            f"really want it there.")


def esc_path(p: str) -> str:
    """Escape a path for use inside an ffmpeg filter option value."""
    return p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def fill(w: int, h: int) -> str:
    """Scale to cover w x h, then center-crop. Keeps aspect, no bars."""
    return (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,fps={FPS}")


def blur_fit(label_in: str, label_out: str, w: int = W, h: int = H) -> str:
    """Fit the whole frame to width over a blurred, filled copy of itself."""
    return (f"[{label_in}]split=2[bf_a{label_out}][bf_b{label_out}];"
            f"[bf_a{label_out}]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},boxblur=40:4,eq=brightness=-0.08[bg{label_out}];"
            f"[bf_b{label_out}]scale={w}:{h}:force_original_aspect_ratio=decrease,setsar=1[fg{label_out}];"
            f"[bg{label_out}][fg{label_out}]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS}[{label_out}]")


class TextFiles:
    """drawtext reads text from files so nothing needs filter escaping."""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="reelcut_"))
        self.n = 0

    def make(self, text: str) -> str:
        self.n += 1
        p = self.dir / f"t{self.n}.txt"
        p.write_text(text, encoding="utf-8")
        return esc_path(str(p))

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def wrap(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(" ".join(text.split()), width=width)) or " "


def caption(tf: TextFiles, font: str, text: str, *, size: int, y: str,
            start: float | None = None, end: float | None = None,
            box: bool = True, wrap_at: int = 22) -> str:
    """A centered caption, optionally limited to a time window."""
    opts = [
        f"fontfile='{esc_path(font)}'",
        f"textfile='{tf.make(wrap(text, wrap_at))}'",
        "fontcolor=white", f"fontsize={size}",
        "x=(w-text_w)/2", f"y={y}", "line_spacing=12",
        "borderw=3", "bordercolor=black@0.6",
    ]
    if box:
        opts += ["box=1", "boxcolor=black@0.55", "boxborderw=24"]
    if start is not None or end is not None:
        a = 0.0 if start is None else start
        b = 1e9 if end is None else end
        opts.append(f"enable='between(t,{a:.3f},{b:.3f})'")
    return "drawtext=" + ":".join(opts)


def run_ffmpeg(args: list[str], out: str, dry: bool) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args,
           "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-preset", "medium", "-crf", "18", "-maxrate", "20M", "-bufsize", "40M",
           "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
           "-movflags", "+faststart", out]
    guard_output(args, out)
    if dry:
        print(" ".join(f"'{c}'" if " " in c or ";" in c else c for c in cmd))
        return
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise ReelcutError(f"ffmpeg failed for {out}:\n{res.stderr.strip()}")
    print(f"wrote {out}")


def audio_graph(inputs: list[str], src_index: int | None, music_index: int | None,
                duration: float, has_audio: bool, music_vol: float) -> tuple[str, list[str]]:
    """Returns (filter fragment producing [aout], extra input args)."""
    extra: list[str] = []
    if music_index is not None:
        frag = (f"[{music_index}:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
                f"volume={music_vol},afade=t=out:st={max(duration - 0.6, 0):.3f}:d=0.6[aout]")
    elif src_index is not None and has_audio:
        frag = f"[{src_index}:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[aout]"
    else:
        silent_index = inputs.count("-i")  # next input index, counted from the args
        extra = ["-f", "lavfi", "-t", f"{duration:.3f}",
                 "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        frag = f"[{silent_index}:a]anull[aout]"
    return frag, extra


def hook_and_end(tf: TextFiles, font: str, duration: float, hook: str | None,
                 hook_secs: float, end_text: str | None, end_secs: float,
                 hook_y: str = "230") -> list[str]:
    parts = []
    if hook:
        parts.append(caption(tf, font, hook, size=62, y=hook_y, start=0, end=hook_secs))
    if end_text:
        parts.append(caption(tf, font, end_text, size=72, y="(h-text_h)/2",
                             start=max(duration - end_secs, 0), end=duration + 1))
    return parts


# ---------------------------------------------------------------- commands

def cmd_stack(a: argparse.Namespace) -> None:
    font = pick_font(a.font, FONT_CANDIDATES)
    top, bottom = probe(a.top), probe(a.bottom)
    duration = a.duration or min(top["duration"] - a.top_start, bottom["duration"] - a.bottom_start)
    if duration <= 0:
        raise ReelcutError("Nothing left to use after the start offsets.")
    tf = TextFiles()
    try:
        inputs = ["-ss", f"{a.top_start}", "-t", f"{duration}", "-i", a.top,
                  "-ss", f"{a.bottom_start}", "-t", f"{duration}", "-i", a.bottom]
        music_index = None
        if a.music:
            inputs += ["-i", a.music]
            music_index = 2
        audio_src = 0 if a.audio == "top" else 1
        has_audio = (top if a.audio == "top" else bottom)["audio"]
        afrag, extra = audio_graph(inputs, audio_src, music_index, duration, has_audio, a.music_volume)
        overlays = [f"drawbox=x=0:y={HALF_H - 3}:w={W}:h=6:color=white@0.9:t=fill"]
        if a.top_label:
            overlays.append(caption(tf, font, a.top_label, size=44, y=f"{HALF_H - 110}", box=True))
        if a.bottom_label:
            overlays.append(caption(tf, font, a.bottom_label, size=44, y=f"{HALF_H + 40}", box=True))
        overlays += hook_and_end(tf, font, duration, a.hook, a.hook_secs, a.end_text, a.end_secs)
        vf = (f"[0:v]{fill(W, HALF_H)}[t];[1:v]{fill(W, HALF_H)}[b];"
              f"[t][b]vstack=inputs=2," + ",".join(overlays) + f",trim=0:{duration:.3f}[vout];{afrag}")
        run_ffmpeg([*inputs, *extra, "-filter_complex", vf, "-map", "[vout]", "-map", "[aout]",
                    "-t", f"{duration:.3f}"], a.out, a.dry_run)
    finally:
        tf.cleanup()


def typed_prompt_filters(tf: TextFiles, mono: str, prompt: str, type_secs: float,
                         total: float, wrap_at: int) -> list[str]:
    """Reveal the prompt word by word over type_secs, then hold it."""
    words = prompt.split()
    if not words:
        return []
    step = type_secs / len(words)
    filters = []
    for i in range(len(words)):
        shown = " ".join(words[: i + 1])
        start = i * step
        end = (i + 1) * step if i < len(words) - 1 else total + 1
        cursor = "_" if i < len(words) - 1 else ""
        filters.append(
            "drawtext=" + ":".join([
                f"fontfile='{esc_path(mono)}'",
                f"textfile='{tf.make(wrap(shown, wrap_at) + cursor)}'",
                "fontcolor=0xE8E8E8", "fontsize=40", "line_spacing=14",
                "x=70", "y=200",
                f"enable='between(t,{start:.3f},{end:.3f})'",
            ]))
    return filters


def cmd_prompt(a: argparse.Namespace) -> None:
    font = pick_font(a.font, FONT_CANDIDATES)
    mono = pick_font(a.mono_font, MONO_CANDIDATES)
    pairs = load_pairs(a)
    tf = TextFiles()
    work = Path(tempfile.mkdtemp(prefix="reelcut_prompt_"))
    try:
        segments = []
        for idx, (prompt, clip, secs) in enumerate(pairs, start=1):
            info = probe(clip)
            dur = min(secs or info["duration"], info["duration"])
            type_secs = min(a.type_secs, dur * 0.7)
            seg = str(work / f"seg{idx}.mp4")
            label = a.top_label or "PROMPT"
            panel = [
                f"drawtext=fontfile='{esc_path(font)}':textfile='{tf.make(label)}':fontcolor=0x9A9A9A:"
                f"fontsize=30:x=70:y=130",
                *typed_prompt_filters(tf, mono, prompt, type_secs, dur, a.wrap),
            ]
            if a.numbered:
                panel.append(f"drawtext=fontfile='{esc_path(font)}':textfile='{tf.make(str(idx))}':fontcolor=white:"
                             f"fontsize=90:x=w-text_w-60:y=50")
            vf = (f"color=c=0x0B0B0B:s={W}x{HALF_H}:r={FPS}:d={dur:.3f},"
                  + ",".join(panel) + "[t];"
                  f"[0:v]{fill(W, HALF_H)}[b];"
                  f"[t][b]vstack=inputs=2,drawbox=x=0:y={HALF_H - 2}:w={W}:h=4:color=white@0.8:t=fill,"
                  f"trim=0:{dur:.3f},setpts=PTS-STARTPTS[vout]")
            afrag, extra = audio_graph(["-i"], 0, None, dur, info["audio"], 1.0)
            run_ffmpeg(["-t", f"{dur:.3f}", "-i", clip, *extra, "-filter_complex", f"{vf};{afrag}",
                        "-map", "[vout]", "-map", "[aout]", "-t", f"{dur:.3f}"], seg, a.dry_run)
            segments.append((seg, dur))
        if a.dry_run:
            return
        total = sum(d for _, d in segments)
        joined = str(work / "joined.mp4")
        concat_list = work / "list.txt"
        concat_list.write_text("".join(f"file '{s}'\n" for s, _ in segments))
        res = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                              "-safe", "0", "-i", str(concat_list), "-c", "copy", joined],
                             capture_output=True, text=True)
        if res.returncode != 0:
            raise ReelcutError(f"Joining segments failed:\n{res.stderr.strip()}")
        inputs = ["-i", joined]
        music_index = None
        if a.music:
            inputs += ["-i", a.music]
            music_index = 1
        afrag, extra = audio_graph(inputs, 0, music_index, total, True, a.music_volume)
        # the prompt types out at the top, so the hook sits low in the top panel
        over = hook_and_end(tf, font, total, a.hook, a.hook_secs, a.end_text, a.end_secs,
                            hook_y=f"{HALF_H - 260}")
        vchain = "[0:v]" + (",".join(over) if over else "null") + "[vout]"
        run_ffmpeg([*inputs, *extra, "-filter_complex", f"{vchain};{afrag}",
                    "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.3f}"], a.out, False)
    finally:
        tf.cleanup()
        shutil.rmtree(work, ignore_errors=True)


def load_pairs(a: argparse.Namespace) -> list[tuple[str, str, float | None]]:
    pairs: list[tuple[str, str, float | None]] = []
    if a.recipe:
        data = json.loads(Path(a.recipe).read_text())
        base = Path(a.recipe).parent
        for item in data.get("shots", []):
            clip = item["clip"]
            if not Path(clip).is_absolute():
                clip = str(base / clip)
            pairs.append((item["prompt"], clip, item.get("seconds")))
        for key in ("hook", "end_text", "music"):
            if data.get(key) and not getattr(a, key):
                val = data[key]
                if key == "music" and not Path(val).is_absolute():
                    val = str(base / val)
                setattr(a, key, val)
    for raw in a.pair or []:
        if "::" not in raw:
            raise ReelcutError('--pair takes "prompt text::/path/to/clip.mp4[::seconds]"')
        bits = raw.split("::")
        pairs.append((bits[0], bits[1], float(bits[2]) if len(bits) > 2 and bits[2] else None))
    if not pairs:
        raise ReelcutError("Give at least one --pair or a --recipe file.")
    for prompt, _, _ in pairs:
        if prompt.strip().upper().startswith("PASTE"):
            raise ReelcutError("The recipe still has a placeholder prompt. Paste the real prompt first.")
    return pairs


def parse_time(s: str) -> float:
    total = 0.0
    for part in s.split(":"):
        total = total * 60 + float(part)
    return total


def cmd_parts(a: argparse.Namespace) -> None:
    font = pick_font(a.font, FONT_CANDIDATES)
    info = probe(a.input)
    if a.at:
        cuts = [parse_time(t) for t in a.at.split(",")]
        bounds = [0.0, *cuts, info["duration"]]
    else:
        n = a.count
        seg = info["duration"] / n
        bounds = [round(i * seg, 3) for i in range(n)] + [info["duration"]]
    n = len(bounds) - 1
    stem = Path(a.out_prefix)
    for i in range(n):
        start, end = bounds[i], bounds[i + 1]
        dur = end - start
        if dur <= 0.2:
            raise ReelcutError(f"Part {i + 1} is too short ({dur:.2f}s). Check --at.")
        tf = TextFiles()
        try:
            over = []
            if not a.no_label:
                over.append(caption(tf, font, f"PART {i + 1} / {n}", size=46, y="140", box=True))
            hook = None
            if a.hooks:
                hooks = a.hooks.split("|")
                hook = hooks[i] if i < len(hooks) else None
            end_text = None
            if a.end_texts:
                ends = a.end_texts.split("|")
                end_text = ends[i] if i < len(ends) and ends[i] else None
            over += hook_and_end(tf, font, dur, hook, a.hook_secs, end_text, a.end_secs)
            if a.fit == "blur":
                vf = blur_fit("0:v", "fit") + ";[fit]" + (",".join(over) if over else "null") + "[vout]"
            else:
                vf = f"[0:v]{fill(W, H)}" + ("," + ",".join(over) if over else "") + "[vout]"
            afrag, extra = audio_graph(["-i"], 0, None, dur, info["audio"], 1.0)
            out = f"{stem}_part{i + 1}of{n}.mp4"
            run_ffmpeg(["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", a.input, *extra,
                        "-filter_complex", f"{vf};{afrag}", "-map", "[vout]", "-map", "[aout]",
                        "-t", f"{dur:.3f}"], out, a.dry_run)
        finally:
            tf.cleanup()


def cmd_wipe(a: argparse.Namespace) -> None:
    font = pick_font(a.font, FONT_CANDIDATES)
    before, after = probe(a.before), probe(a.after)
    dur = a.duration or min(before["duration"], after["duration"])
    hold, wipe = a.hold, a.wipe_secs
    if hold + wipe > dur:
        raise ReelcutError(f"--hold + --wipe-secs ({hold + wipe}s) is longer than the clip ({dur:.2f}s).")
    t0, t1 = hold, hold + wipe
    pos = f"clip((T-{t0})/{wipe},0,1)"
    tf = TextFiles()
    try:
        prep = (lambda idx, lab: f"[{idx}:v]{fill(W, H)},format=yuv420p[{lab}]") if a.fit == "crop" else \
               (lambda idx, lab: blur_fit(f"{idx}:v", f"{lab}x") + f";[{lab}x]format=yuv420p[{lab}]")
        over = []
        if a.before_label:
            over.append(caption(tf, font, a.before_label, size=44, y="h-420", start=0, end=t1))
        if a.after_label:
            over.append(caption(tf, font, a.after_label, size=44, y="h-420", start=t1, end=dur + 1))
        over += hook_and_end(tf, font, dur, a.hook, a.hook_secs, a.end_text, a.end_secs)
        edge = f"lt(abs(X-W*{pos}),W*0.003)*between(T,{t0},{t1})"
        blend = (f"blend=c0_expr='if({edge},235,if(lt(X,W*{pos}),B,A))'"
                 f":c1_expr='if({edge},128,if(lt(X,W*{pos}),B,A))'"
                 f":c2_expr='if({edge},128,if(lt(X,W*{pos}),B,A))'")
        vf = (prep(0, "a") + ";" + prep(1, "b") + ";"
              f"[a][b]{blend}"
              + ("," + ",".join(over) if over else "") + f",trim=0:{dur:.3f}[vout]")
        inputs = ["-t", f"{dur:.3f}", "-i", a.before, "-t", f"{dur:.3f}", "-i", a.after]
        music_index = None
        if a.music:
            inputs += ["-i", a.music]
            music_index = 2
        afrag, extra = audio_graph(inputs, 1, music_index, dur, after["audio"], a.music_volume)
        run_ffmpeg([*inputs, *extra, "-filter_complex", f"{vf};{afrag}", "-map", "[vout]",
                    "-map", "[aout]", "-t", f"{dur:.3f}"], a.out, a.dry_run)
    finally:
        tf.cleanup()


def cmd_vertical(a: argparse.Namespace) -> None:
    font = pick_font(a.font, FONT_CANDIDATES)
    info = probe(a.input)
    dur = a.duration or (info["duration"] - a.start)
    tf = TextFiles()
    try:
        over = hook_and_end(tf, font, dur, a.hook, a.hook_secs, a.end_text, a.end_secs)
        if a.fit == "blur":
            vf = blur_fit("0:v", "fit") + ";[fit]" + (",".join(over) if over else "null") + "[vout]"
        else:
            vf = f"[0:v]{fill(W, H)}" + ("," + ",".join(over) if over else "") + "[vout]"
        inputs = ["-ss", f"{a.start}", "-t", f"{dur:.3f}", "-i", a.input]
        music_index = None
        if a.music:
            inputs += ["-i", a.music]
            music_index = 1
        afrag, extra = audio_graph(inputs, 0, music_index, dur, info["audio"], a.music_volume)
        run_ffmpeg([*inputs, *extra, "-filter_complex", f"{vf};{afrag}", "-map", "[vout]",
                    "-map", "[aout]", "-t", f"{dur:.3f}"], a.out, a.dry_run)
    finally:
        tf.cleanup()


# ---------------------------------------------------------------- CLI

def fmt_secs(sec: float) -> str:
    m, s_ = divmod(int(round(sec)), 60)
    return f"{m}:{s_:02d}"


def fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def cmd_scan(a: argparse.Namespace) -> None:
    root = Path(a.folder).expanduser()
    if not root.exists():
        hint = ""
        if str(root).startswith(VOLUMES_ROOT):
            mounted = sorted(p.name for p in Path(VOLUMES_ROOT).iterdir()) \
                if Path(VOLUMES_ROOT).is_dir() else []
            hint = f". Drives mounted now: {', '.join(mounted) or 'none'}"
        raise ReelcutError(f"Folder not found: {root}{hint}")
    if not root.is_dir():
        raise ReelcutError(f"Not a folder: {root}")

    def wanted(p: Path) -> bool:
        rel = p.relative_to(root).parts
        # skip hidden folders and the "._" sidecar files macOS writes on exFAT drives
        return (p.suffix.lower() in VIDEO_EXTS and not any(x.startswith(".") for x in rel)
                and p.is_file() and len(rel) <= a.depth + 1)

    files = sorted((p for p in root.rglob("*") if wanted(p)), key=lambda p: str(p).lower())
    if a.name:
        files = [p for p in files if a.name.lower() in p.name.lower()]
    if not files:
        print(f"No video files under {root}")
        return
    ready = need_export = 0
    for f in files:
        size = fmt_size(f.stat().st_size)
        try:
            i = probe(str(f))
            ready += 1
            print(f"ok      {fmt_secs(i['duration']):>6}  {i['width']}x{i['height']:<5} "
                  f"{i['codec']:<9} {size:>9}  {f}")
        except ReelcutError as e:
            need_export += 1
            why = RAW_FORMATS.get(f.suffix.lower()) or "can't read"
            if "ProRes RAW" in str(e):
                why = "ProRes RAW"
            print(f"EXPORT  {'':>6}  {why:<20} {size:>9}  {f}")
    print(f"\n{ready} ready to use, {need_export} need exporting from Resolve first.")


def common(p: argparse.ArgumentParser, music: bool = True) -> None:
    p.add_argument("--hook", help="On-screen hook shown for the first seconds")
    p.add_argument("--hook-secs", type=float, default=2.5)
    p.add_argument("--end-text", help='End card text, e.g. "Part 2 Saturday"')
    p.add_argument("--end-secs", type=float, default=1.5)
    p.add_argument("--font", help="Path to a .ttf/.ttc font for captions")
    p.add_argument("--dry-run", action="store_true", help="Print the ffmpeg command, write nothing")
    p.add_argument("--allow-source-drive", action="store_true",
                   help="Allow writing onto the same external drive the footage is on")
    if music:
        p.add_argument("--music", help="Audio file to use instead of the clip's sound")
        p.add_argument("--music-volume", type=float, default=1.0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="reelcut", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("stack", help="Two clips stacked: setup vs. the shot")
    s.add_argument("--top", required=True, help="Clip for the top half (the finished shot)")
    s.add_argument("--bottom", required=True, help="Clip for the bottom half (the setup / BTS)")
    s.add_argument("--top-start", type=float, default=0.0)
    s.add_argument("--bottom-start", type=float, default=0.0)
    s.add_argument("--duration", type=float, help="Seconds (default: shorter clip)")
    s.add_argument("--top-label", help='e.g. "THE SHOT"')
    s.add_argument("--bottom-label", help='e.g. "THE SETUP"')
    s.add_argument("--audio", choices=["top", "bottom"], default="top")
    s.add_argument("--out", required=True)
    common(s)
    s.set_defaults(func=cmd_stack)

    p = sub.add_parser("prompt", help="Prompt vs. the shot, one or more pairs")
    p.add_argument("--pair", action="append",
                   help='"prompt text::/path/clip.mp4[::seconds]" (repeat for each shot)')
    p.add_argument("--recipe", help="JSON file with shots (see recipes/prompt-vs-shot-template.json)")
    p.add_argument("--type-secs", type=float, default=2.2, help="How long the prompt takes to type out")
    p.add_argument("--wrap", type=int, default=38, help="Characters per prompt line")
    p.add_argument("--top-label", help='Small label over the prompt (default "PROMPT")')
    p.add_argument("--numbered", action="store_true", help="Put 1, 2, 3 on each shot")
    p.add_argument("--mono-font", help="Font for the prompt text")
    p.add_argument("--out", required=True)
    common(p)
    p.set_defaults(func=cmd_prompt)

    t = sub.add_parser("parts", help="Cut one video into labelled vertical parts")
    t.add_argument("--input", required=True)
    g = t.add_mutually_exclusive_group()
    g.add_argument("--count", type=int, default=3, help="Equal parts (default 3)")
    g.add_argument("--at", help='Cut points, e.g. "0:34,1:08" (better: end each part on a tense frame)')
    t.add_argument("--fit", choices=["blur", "crop"], default="blur",
                   help="blur keeps the whole 16:9 frame over a blurred fill; crop fills the screen")
    t.add_argument("--no-label", action="store_true", help='Skip the "PART 1 / 3" label')
    t.add_argument("--hooks", help='One hook per part, separated by |')
    t.add_argument("--end-texts", help='One end card per part, separated by | (blank = none)')
    t.add_argument("--hook-secs", type=float, default=2.5)
    t.add_argument("--end-secs", type=float, default=1.5)
    t.add_argument("--font")
    t.add_argument("--dry-run", action="store_true")
    t.add_argument("--allow-source-drive", action="store_true")
    t.add_argument("--out-prefix", required=True, help="e.g. ~/Movies/Reels/twisted_fate  ->  twisted_fate_part1of3.mp4")
    t.set_defaults(func=cmd_parts)

    w = sub.add_parser("wipe", help="LOG vs. graded wipe")
    w.add_argument("--before", required=True, help="Flat / LOG clip")
    w.add_argument("--after", required=True, help="Graded clip (same shot, same length)")
    w.add_argument("--duration", type=float)
    w.add_argument("--hold", type=float, default=1.0, help="Seconds on the flat image before the wipe")
    w.add_argument("--wipe-secs", type=float, default=1.5)
    w.add_argument("--before-label", default="STRAIGHT OUT OF CAMERA")
    w.add_argument("--after-label", default="GRADED")
    w.add_argument("--fit", choices=["blur", "crop"], default="crop")
    w.add_argument("--out", required=True)
    common(w)
    w.set_defaults(func=cmd_wipe)

    v = sub.add_parser("vertical", help="One clip reframed to 9:16")
    v.add_argument("--input", required=True)
    v.add_argument("--start", type=float, default=0.0)
    v.add_argument("--duration", type=float)
    v.add_argument("--fit", choices=["blur", "crop"], default="crop")
    v.add_argument("--out", required=True)
    common(v)
    v.set_defaults(func=cmd_vertical)

    sc = sub.add_parser("scan", help="List video files in a folder and flag ones to export first")
    sc.add_argument("folder", help='e.g. "/Volumes/Watson dev/Movies"  (run `ls /Volumes` to see drive names)')
    sc.add_argument("--depth", type=int, default=6, help="How many folders deep to look (default 6)")
    sc.add_argument("--name", help="Only files whose name contains this, e.g. A001")
    sc.set_defaults(func=cmd_scan)

    args = ap.parse_args(argv)
    global ALLOW_SOURCE_DRIVE
    ALLOW_SOURCE_DRIVE = getattr(args, "allow_source_drive", False)
    try:
        need_tools()
        args.func(args)
    except ReelcutError as e:
        print(f"reelcut: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
