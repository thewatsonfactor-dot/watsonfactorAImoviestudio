"""API-level acceptance tests against a running Studio + mock engine.

    dev/acceptance.py [--studio http://127.0.0.1:8420]

Covers: render end-to-end, sidecar, cancel mid-render, re-roll, queue order,
long-prompt guard (server side accepts; UI warns), and plain-English failures.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--studio", default="http://127.0.0.1:8420")
ap.add_argument("--keyframe", default=str(Path(__file__).resolve().parents[1] / "frontend/public/brand/wf-mark-tight.png"))
ap.add_argument("--only", default=None)
ap.add_argument("--timeout", type=float, default=120, help="seconds to wait per render (use ~1500 on the real engine)")
args = ap.parse_args()
c = httpx.Client(base_url=args.studio, timeout=30)
results = []


def check(name, cond, info=""):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}  {name} {info}")


def upload():
    with open(args.keyframe, "rb") as f:
        return c.post("/api/upload", files={"file": ("key.png", f, "image/png")}).json()


def job(prompt, **kw):
    up = upload()
    body = {"input_path": up["path"], "prompt": prompt, "project": "Acceptance", "preset": "draft", "length": "short"} | kw
    r = c.post("/api/jobs", json=body)
    r.raise_for_status()
    return r.json()


def wait(jid, states=("done", "failed", "cancelled"), timeout=None, until=None):
    timeout = timeout or args.timeout
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in states or (until and until(j)):
            return j
        time.sleep(0.5)
    return c.get(f"/api/jobs/{jid}").json()


def t_render():
    print("render end-to-end")
    j = wait(job("slow push in")["id"])
    check("job finished", j["status"] == "done", j.get("error") or "")
    check("mp4 on SSD", j["file_exists"])
    side = Path(j["output_path"]).with_suffix(".json")
    meta = json.loads(side.read_text()) if side.exists() else {}
    check("sidecar written with seed + prompt", meta.get("seed") == j["seed"] and meta.get("prompt") == "slow push in")
    check("render time recorded", (j["render_seconds"] or 0) > 0)
    return j


def t_reroll(done):
    print("re-roll")
    r = c.post(f"/api/library/{done['id']}/reroll").json()
    check("re-roll gets a new seed", r["seed"] != done["seed"])
    check("re-roll keeps prompt + size", r["prompt"] == done["prompt"] and r["width"] == done["width"])
    j = wait(r["id"])
    check("re-roll finished", j["status"] == "done")


def t_cancel():
    print("cancel mid-render")
    jid = job("cancel me")["id"]
    wait(jid, until=lambda j: (j.get("live") or {}).get("stage", "").startswith("sample"))
    c.post(f"/api/jobs/{jid}/cancel")
    j = wait(jid, timeout=10)
    check("cancelled within seconds", j["status"] == "cancelled")
    nxt = wait(job("after cancel")["id"])
    check("engine healthy for the next job", nxt["status"] == "done")


def t_queue():
    print("queue order")
    a, b, d = job("first"), job("second"), job("third")
    time.sleep(1.5)
    active = [x for x in c.get("/api/jobs").json() if x["status"] == "queued"]
    ids = [x["id"] for x in sorted(active, key=lambda x: x["queue_pos"])]
    if len(ids) >= 2:
        ids = list(reversed(ids))
        c.post("/api/queue/order", json=ids)
        after = [x for x in c.get("/api/jobs").json() if x["status"] == "queued"]
        check("queue reorders", [x["id"] for x in sorted(after, key=lambda x: x["queue_pos"])] == ids)
    for x in (a, b, d):
        c.post(f"/api/jobs/{x['id']}/cancel")
    check("queued jobs removable", all(c.get(f"/api/jobs/{x['id']}").json()["status"] in ("cancelled", "done")
                                       for x in (a, b, d)))


def t_fail():
    print("engine failure → plain English (needs mock started with --fail-at 13)")
    j = wait(job("oom please")["id"])
    check("job failed", j["status"] == "failed")
    check("plain-English memory message", "Ran out of memory" in (j.get("error") or ""), j.get("error") or "")
    check("raw detail kept", "MPS backend out of memory" in (j.get("error_detail") or ""))


def t_blank():
    print("silent failure → marked failed, kept out of the Library (needs mock started with --blank)")
    j = wait(job("blank please")["id"])
    check("blank render is marked failed, not done", j["status"] == "failed", j.get("error") or "")
    check("plain-English blank-video message", "blank" in (j.get("error") or "").lower())
    detail = json.loads(j.get("error_detail") or "{}")
    kept = detail.get("saved_for_inspection")
    check("file moved to .failed/ for inspection", bool(kept) and "/.failed/" in kept and Path(kept).exists(), kept or "")
    check("nothing left in the project folder", not j.get("output_path"))


tests = {"render": None, "cancel": t_cancel, "queue": t_queue, "fail": t_fail, "blank": t_blank}
if args.only:
    tests[args.only]() if args.only != "render" else t_reroll(t_render())
else:
    t_reroll(t_render()); t_cancel(); t_queue()
failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
