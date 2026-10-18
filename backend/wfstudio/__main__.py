"""Run with: python -m wfstudio  (binds 127.0.0.1 only)."""
import uvicorn

from . import config

if __name__ == "__main__":
    s = config.settings()
    # An open dashboard tab keeps a websocket open; without a timeout, shutdown waits for it forever.
    uvicorn.run("wfstudio.main:app", host="127.0.0.1", port=int(s["studio_port"]), log_level="info",
                timeout_graceful_shutdown=5)
