"""Run with: python -m wfstudio  (binds 127.0.0.1 only)."""
import uvicorn

from . import config

if __name__ == "__main__":
    s = config.settings()
    uvicorn.run("wfstudio.main:app", host="127.0.0.1", port=int(s["studio_port"]), log_level="info")
