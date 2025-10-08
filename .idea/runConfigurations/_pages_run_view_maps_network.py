#!/usr/bin/env python3
"""Auto-generated runner for apps-page 'view_maps_network'."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict

PROJECT_DIR = Path(__file__).resolve().parents[2]
PROJECT_SRC = PROJECT_DIR / "src"
PAGE_DIR = PROJECT_SRC / "agilab" / "apps-pages" / "view_maps_network"
ENTRY_SCRIPT = PAGE_DIR / "src" / "view_maps_network" / "view_maps_network.py"
DEFAULT_ACTIVE_APP = Path(r"/Users/example/agilab/src/agilab/apps/flight_project") if True else None
PYTHON_CANDIDATES = (
    PAGE_DIR / ".venv" / "bin" / "python3.exe",
    PAGE_DIR / ".venv" / "bin" / "python3",
    PAGE_DIR / ".venv" / "bin" / "python",
    PAGE_DIR / ".venv" / "Scripts" / "python.exe",
    PAGE_DIR / ".venv" / "Scripts" / "python3.exe",
)


def _select_python() -> str:
    for candidate in PYTHON_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _enhance_pythonpath(env: Dict[str, str]) -> None:
    extra_paths = [str(PROJECT_SRC), str(PROJECT_DIR)]
    existing = env.get("PYTHONPATH")
    if existing:
        env["PYTHONPATH"] = os.pathsep.join(extra_paths + [existing])
    else:
        env["PYTHONPATH"] = os.pathsep.join(extra_paths)


def main() -> None:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("UV_NO_SYNC", "1")
    _enhance_pythonpath(env)
    env.setdefault("AGILAB_INSTALL_TYPE", "1")
    if DEFAULT_ACTIVE_APP is not None:
        env.setdefault("AGILAB_ACTIVE_APP", str(DEFAULT_ACTIVE_APP))

    cmd = [_select_python(), "-m", "streamlit", "run", str(ENTRY_SCRIPT)]
    subprocess.run(cmd, check=True, cwd=PROJECT_DIR, env=env)


if __name__ == "__main__":
    main()
