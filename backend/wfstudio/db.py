"""SQLite store for jobs and projects. Every finished render also gets a JSON
sidecar next to its mp4, so the library can be rebuilt if this file is lost."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from . import config

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

JOB_COLUMNS = [
    "id", "created_at", "started_at", "finished_at", "status", "project",
    "prompt", "negative", "preset", "length", "seed", "width", "height",
    "frames", "steps", "split", "cfg", "shift", "input_path", "prompt_id",
    "output_path", "thumb_path", "sidecar_path", "error", "error_detail",
    "render_seconds", "favorite", "tags", "queue_pos", "parent_id",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    created_at REAL, started_at REAL, finished_at REAL,
    status TEXT,                 -- queued | running | done | failed | cancelled | deleted
    project TEXT, prompt TEXT, negative TEXT,
    preset TEXT, length TEXT, seed INTEGER,
    width INTEGER, height INTEGER, frames INTEGER,
    steps INTEGER, split INTEGER, cfg REAL, shift REAL,
    input_path TEXT, prompt_id TEXT,
    output_path TEXT, thumb_path TEXT, sidecar_path TEXT,
    error TEXT, error_detail TEXT,
    render_seconds REAL,
    favorite INTEGER DEFAULT 0,
    tags TEXT DEFAULT '[]',
    queue_pos REAL,
    parent_id TEXT
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS projects (name TEXT PRIMARY KEY, created_at REAL);
"""


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.ensure_dirs()
        _conn = sqlite3.connect(config.DATA_DIR / "studio.db", check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        _conn.execute("INSERT OR IGNORE INTO projects VALUES (?, ?)",
                      (config.settings()["default_project"], time.time()))
        _conn.commit()
    return _conn


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    if r is None:
        return None
    d = dict(r)
    d["tags"] = json.loads(d.get("tags") or "[]")
    d["favorite"] = bool(d.get("favorite"))
    return d


def insert_job(job: dict[str, Any]) -> dict[str, Any]:
    cols = [c for c in JOB_COLUMNS if c in job]
    vals = [json.dumps(job[c]) if c == "tags" else job[c] for c in cols]
    with _lock:
        conn().execute(
            f"INSERT INTO jobs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
        conn().commit()
        ensure_project(job.get("project") or config.settings()["default_project"])
    return get_job(job["id"])  # type: ignore[return-value]


def update_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    if not fields:
        return get_job(job_id)
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    if "favorite" in fields:
        fields["favorite"] = 1 if fields["favorite"] else 0
    sets = ",".join(f"{k}=?" for k in fields)
    with _lock:
        conn().execute(f"UPDATE jobs SET {sets} WHERE id=?", [*fields.values(), job_id])
        conn().commit()
    return get_job(job_id)


def claim(job_id: str) -> bool:
    """queued -> running, atomically. False if it was cancelled in the meantime."""
    with _lock:
        cur = conn().execute("UPDATE jobs SET status='running', started_at=? WHERE id=? AND status='queued'",
                             (time.time(), job_id))
        conn().commit()
        return cur.rowcount == 1


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        return _row(conn().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def jobs(where: str = "1=1", params: tuple = (), order: str = "created_at DESC",
         limit: int | None = None) -> list[dict[str, Any]]:
    q = f"SELECT * FROM jobs WHERE {where} ORDER BY {order}"
    if limit:
        q += f" LIMIT {int(limit)}"
    with _lock:
        return [_row(r) for r in conn().execute(q, params).fetchall()]  # type: ignore[misc]


def queued() -> list[dict[str, Any]]:
    return jobs("status='queued'", order="queue_pos ASC, created_at ASC")


def running() -> dict[str, Any] | None:
    r = jobs("status='running'", order="started_at ASC", limit=1)
    return r[0] if r else None


def next_queue_pos() -> float:
    with _lock:
        v = conn().execute("SELECT MAX(queue_pos) FROM jobs WHERE status='queued'").fetchone()[0]
    return (v or 0) + 1


def avg_render_seconds(preset: str, length: str, n: int = 5) -> float | None:
    with _lock:
        rows = conn().execute(
            # Deleted renders still count (people delete good takes too), but never ones marked with an
            # error: a render the engine botched must not teach the Studio that a setting is fast.
            "SELECT render_seconds FROM jobs WHERE status IN ('done','deleted') AND error IS NULL "
            "AND preset=? AND length=? AND render_seconds IS NOT NULL ORDER BY finished_at DESC LIMIT ?",
            (preset, length, n)).fetchall()
    vals = [r[0] for r in rows]
    return sum(vals) / len(vals) if vals else None


def token_history() -> dict[str, Any]:
    """Largest size (in latent tokens) that has rendered cleanly here, and every size that ran out of memory."""
    tok = "(width/16)*(height/16)*((frames-1)/4+1)"
    with _lock:
        c = conn()
        proven = c.execute(f"SELECT MAX({tok}) FROM jobs WHERE status IN ('done','deleted') AND error IS NULL "
                           "AND render_seconds IS NOT NULL AND width AND height AND frames").fetchone()[0]
        failed = [r[0] for r in c.execute(
            f"SELECT DISTINCT {tok} FROM jobs WHERE error IS NOT NULL AND width AND height AND frames "
            "AND (LOWER(error) LIKE '%out of memory%' OR LOWER(error) LIKE '%blank%')")]
    return {"proven": proven, "failed": failed}


def ensure_project(name: str) -> None:
    with _lock:
        conn().execute("INSERT OR IGNORE INTO projects VALUES (?, ?)", (name, time.time()))
        conn().commit()


def projects() -> list[dict[str, Any]]:
    with _lock:
        rows = conn().execute(
            "SELECT p.name, p.created_at, "
            "(SELECT COUNT(*) FROM jobs j WHERE j.project=p.name AND j.status='done') AS renders "
            "FROM projects p ORDER BY p.name COLLATE NOCASE").fetchall()
    return [dict(r) for r in rows]


def stats() -> dict[str, Any]:
    import datetime as _dt
    day_start = time.mktime(_dt.date.today().timetuple())  # local midnight
    with _lock:
        c = conn()
        today = c.execute("SELECT COUNT(*) FROM jobs WHERE status='done' AND finished_at>=?",
                          (day_start,)).fetchone()[0]
        total = c.execute("SELECT COUNT(*) FROM jobs WHERE status='done'").fetchone()[0]
        avg = c.execute("SELECT AVG(render_seconds) FROM (SELECT render_seconds FROM jobs "
                        "WHERE status='done' AND render_seconds IS NOT NULL "
                        "ORDER BY finished_at DESC LIMIT 10)").fetchone()[0]
    return {"renders_today": today, "renders_total": total, "avg_render_seconds": avg}
