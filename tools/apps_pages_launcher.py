#!/usr/bin/env python3
"""
Apps-Pages Launcher (user‑friendly)

Pick an apps-page to launch and we’ll start Streamlit for you.

Usage examples:
  uv run python tools/apps_pages_launcher.py \
      --active-app src/agilab/apps/builtin/flight_project \
      --page view_maps

  uv run python tools/apps_pages_launcher.py --active-app src/agilab/apps/builtin/flight_project
  (then pick from the menu)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Tuple

PAGES: Dict[str, str] = {
    "view_maps": "src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py",
    "view_maps_3d": "src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py",
    "view_maps_network": "src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py",
    "view_barycentric": "src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py",
    "view_autoencoder_latentspace": (
        "src/agilab/apps-pages/view_autoencoder_latenspace/src/"
        "view_autoencoder_latentspace/view_autoencoder_latentspace.py"
    ),
}


def run_streamlit(page: str, page_script: Path, active_app: Path, *, port: int | None = None) -> int:
    cmd = [
        "uv",
        "run",
        "streamlit",
        "run",
        str(page_script),
        "--",
        "--active-app",
        str(active_app),
    ]
    if port is not None:
        cmd[5:5] = ["--server.port", str(port)]

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    print(f"[launcher] {page}: {' '.join(cmd)}")
    return subprocess.call(cmd, env=env)


def pick_from_menu(active_app: Path) -> int:
    names = list(PAGES.keys())
    print("\nAvailable apps-pages:\n")
    for i, name in enumerate(names, start=1):
        print(f"  {i}. {name}")
    print("\nSelect a number (or 0 to quit): ", end="", flush=True)
    try:
        choice = int(sys.stdin.readline().strip())
    except Exception:
        print("Invalid input.")
        return 2
    if choice <= 0 or choice > len(names):
        print("Bye.")
        return 0
    name = names[choice - 1]
    page_script = Path(PAGES[name])
    if not page_script.exists():
        print(f"Missing page script: {page_script}", file=sys.stderr)
        return 2
    return run_streamlit(name, page_script, active_app)


def main() -> int:
    # Surface a concise pointer to install logs for troubleshooting
    print(
        "[hint] If launch fails, check latest installer log. "
        "See 'Install Error Check (at Codex startup)' in AGENTS.md."
    )
    parser = argparse.ArgumentParser(description="Apps-Pages Launcher")
    parser.add_argument(
        "--active-app",
        dest="active_app",
        type=str,
        default="src/agilab/apps/builtin/flight_project",
        help="Path to an active app (e.g. src/agilab/apps/builtin/flight_project)",
    )
    parser.add_argument(
        "--page",
        choices=sorted(PAGES.keys()),
        help="Page to launch (omit to pick from menu)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Optional server port (let Streamlit choose if omitted)",
    )
    args = parser.parse_args()

    active_app = Path(args.active_app).resolve()
    if not active_app.exists():
        print(f"[error] --active-app not found: {active_app}", file=sys.stderr)
        return 2

    if args.page:
        page_script = Path(PAGES[args.page])
        if not page_script.exists():
            print(f"Missing page script: {page_script}", file=sys.stderr)
            return 2
        return run_streamlit(args.page, page_script, active_app, port=args.port)
    else:
        return pick_from_menu(active_app)


if __name__ == "__main__":
    raise SystemExit(main())
