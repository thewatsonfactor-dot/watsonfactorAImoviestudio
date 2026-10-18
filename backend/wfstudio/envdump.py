"""Print resolved settings as shell assignments for the launch scripts.

    eval "$(backend/.venv/bin/python -m wfstudio.envdump)"
"""
import shlex

from . import config

if __name__ == "__main__":
    s = config.settings()
    for key in ("ssd_root", "ssd_image", "engine_flags", "models_dir", "output_dir", "inputs_dir", "comfy_url", "comfy_dir", "studio_port"):
        print(f"WF_{key.upper()}={shlex.quote(str(s[key]))}")
