#!/usr/bin/env python3
"""Run a prompt pack through the local Studio, then hand the clips to Reelcut.

A pack (studio/packs/*.json) lists shots. For each shot the Studio makes a still from
`still` (Qwen image, landscape), then animates it with `motion` (Wan 2.2, Standard,
about 5 seconds). When every shot is done, this writes a Reelcut "prompt vs. the shot"
recipe next to the clips and prints the one command that builds the Reel.

Talks only to the Studio on 127.0.0.1. Posts nothing anywhere.

  python3 scripts/run_pack.py studio/packs/villeneuve.json
  python3 scripts/run_pack.py studio/packs/villeneuve.json --only 2      # redo shot 2
  python3 scripts/run_pack.py studio/packs/villeneuve.json --stills-only # check the looks first
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8420"
DONE = {"done", "failed", "cancelled", "deleted"}


class PackError(Exception):
    pass


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail")
        except Exception:  # noqa: BLE001
            detail = None
        raise PackError(f"The Studio said: {detail or e}") from None
    except urllib.error.URLError:
        raise PackError("The Studio isn't running. Click Watson Factor AI Studio in the Dock, "
                        "wait for four green lights, then run this again.") from None


def wait(job_id: str, label: str, poll: float) -> dict:
    last = ""
    while True:
        job = call("GET", f"/api/jobs/{job_id}")
        status = job.get("status", "?")
        live = job.get("live") or {}
        pct = live.get("percent") if isinstance(live, dict) else None
        line = f"  {label}: {status}" + (f" {pct}%" if pct is not None else "")
        if line != last:
            print(line, flush=True)
            last = line
        if status in DONE:
            if status != "done" or not job.get("output_path"):
                raise PackError(f"{label} {status}: {job.get('error') or 'no file came back'}")
            return job
        time.sleep(poll)


def main(argv: list[str] | None = None) -> int:
    global API
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pack")
    ap.add_argument("--only", help="Shot numbers to (re)make, e.g. 2 or 1,3")
    ap.add_argument("--stills-only", action="store_true", help="Make the stills, skip the animation")
    ap.add_argument("--preset", default="standard", choices=["draft", "standard"])
    ap.add_argument("--poll", type=float, default=5.0)
    ap.add_argument("--api", default="http://127.0.0.1:8420")
    a = ap.parse_args(argv)

    API = a.api.rstrip("/")
    if not API.startswith(("http://127.0.0.1", "http://localhost")):
        print("The Studio only runs on this Mac (127.0.0.1).", file=sys.stderr)
        return 2

    pack_path = Path(a.pack)
    pack = json.loads(pack_path.read_text())
    shots = pack["shots"]
    only = {int(x) for x in a.only.split(",")} if a.only else None
    project = pack.get("project", pack_path.stem)
    state_path = Path.home() / "Movies" / "Reels" / "packs" / f"{pack_path.stem}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}

    try:
        for n, shot in enumerate(shots, start=1):
            if only and n not in only:
                continue
            print(f"Shot {n} of {len(shots)}: {shot['show']}")
            img = call("POST", "/api/images", {"prompt": shot["still"], "aspect": "landscape",
                                               "project": project})
            img = wait(img["id"], "still", a.poll)
            state.setdefault(str(n), {})["still"] = img["output_path"]
            state_path.write_text(json.dumps(state, indent=2))
            if a.stills_only:
                continue
            vid = call("POST", "/api/jobs", {"input_path": img["output_path"], "prompt": shot["motion"],
                                             "project": project, "preset": a.preset, "length": "standard"})
            vid = wait(vid["id"], "clip", a.poll)
            state[str(n)]["clip"] = vid["output_path"]
            state_path.write_text(json.dumps(state, indent=2))
    except PackError as e:
        print(f"\nStopped: {e}", file=sys.stderr)
        print(f"Finished shots are saved; rerun with --only to pick up where it stopped.", file=sys.stderr)
        return 1

    if a.stills_only:
        print(f"\nStills are in the Studio Library under project '{project}'.")
        return 0
    missing = [str(n) for n in range(1, len(shots) + 1) if "clip" not in state.get(str(n), {})]
    if missing:
        print(f"\nStill to make: shot {', '.join(missing)} (rerun with --only {','.join(missing)}).")
        return 1
    recipe = {
        "hook": pack.get("hook", ""), "end_text": pack.get("end_text", ""), "music": "",
        "shots": [{"prompt": s["show"], "clip": state[str(n)]["clip"], "seconds": s.get("seconds", 5)}
                  for n, s in enumerate(shots, start=1)],
    }
    recipe_path = state_path.with_name(f"{pack_path.stem}_recipe.json")
    recipe_path.write_text(json.dumps(recipe, indent=2))
    out = Path.home() / "Movies" / "Reels" / f"{pack.get('out', pack_path.stem)}.mp4"
    print("\nAll shots done. Build the Reel with:\n")
    print(f'  python3 reelcut/reelcut.py prompt --recipe "{recipe_path}" --out "{out}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
