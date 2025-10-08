#!/usr/bin/env python3
"""
Lightweight smoke runner for Apps-Pages.

Launches each Streamlit view in headless mode with a provided --active-app,
waits for a healthy startup message, then terminates. Intended to catch
import/arg‑parsing regressions quickly without manual interaction.

Usage:
  uv run python tools/smoke_apps_pages.py \
      --active-app src/agilab/apps/flight_project \
      --timeout 20
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable


PAGES: tuple[tuple[str, str], ...] = (
    ("view_maps", "src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py"),
    ("view_maps_3d", "src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py"),
    ("view_maps_network", "src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py"),
    ("view_barycentric", "src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py"),
    (
        "view_autoencoder_latentspace",
        "src/agilab/apps-pages/view_autoencoder_latenspace/src/view_autoencoder_latentspace/view_autoencoder_latentspace.py",
    ),
)


def _iter_lines(stream) -> Iterable[str]:
    while True:
        line = stream.readline()
        if not line:
            return
        try:
            yield line.decode("utf-8", errors="replace").rstrip()
        except Exception:
            yield str(line).rstrip()


def smoke_one(page_name: str, page_path: Path, active_app: Path, timeout: int) -> None:
    if not page_path.exists():
        raise FileNotFoundError(f"Missing page script: {page_path}")
    cmd = [
        "uv",
        "run",
        "streamlit",
        "run",
        "--server.headless",
        "true",
        "--server.port",
        "0",
        "--browser.gatherUsageStats",
        "false",
        str(page_path),
        "--",
        "--active-app",
        str(active_app),
    ]
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    print(f"[smoke] launching {page_name}: {' '.join(cmd)}")
    start = time.time()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(Path.cwd()),
        env=env,
    )
    try:
        for line in _iter_lines(proc.stdout):  # type: ignore[arg-type]
            print(f"[{page_name}] {line}")
            if (
                "You can now view your Streamlit app in your browser." in line
                or "Network URL:" in line
                or "Local URL:" in line
            ):
                print(f"[smoke] {page_name} started OK — stopping...")
                break
            if time.time() - start > timeout:
                raise TimeoutError(f"Timed out waiting for {page_name} to start")
    finally:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test for Apps-Pages")
    parser.add_argument(
        "--active-app",
        dest="active_app",
        type=str,
        default="src/agilab/apps/flight_project",
        help="Path to an active app (e.g. src/agilab/apps/flight_project)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Seconds to wait for each page to start",
    )
    args = parser.parse_args()

    active_app = Path(args.active_app).resolve()
    if not active_app.exists():
        print(f"[error] --active-app not found: {active_app}", file=sys.stderr)
        return 2

    failures: list[str] = []
    for name, rel in PAGES:
        page_path = Path(rel)
        try:
            smoke_one(name, page_path, active_app, args.timeout)
        except Exception as e:
            print(f"[FAIL] {name}: {e}", file=sys.stderr)
            failures.append(f"{name}: {e}")

    if failures:
        print("\nSmoke failures:", file=sys.stderr)
        for f in failures:
            print(f" - {f}", file=sys.stderr)
        return 1

    print("\nAll apps-pages started successfully (smoke).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

