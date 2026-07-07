"""Page-bundle launcher for the NetworkSim TRI/GTIA visibility view."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from agi_pages.runtime import ensure_repo_on_path as _page_ensure_repo_on_path


def _active_app_path() -> Path | None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--active-app")
    args, _ = parser.parse_known_args()
    if not args.active_app:
        return None
    return Path(args.active_app).expanduser().resolve(strict=False)


def _ensure_active_app_src_on_path() -> None:
    active_app = _active_app_path()
    if active_app is None:
        return
    src_path = active_app / "src"
    if src_path.is_dir() and str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))


def _ensure_repo_on_path() -> None:
    _page_ensure_repo_on_path(__file__)


_ensure_repo_on_path()
_ensure_active_app_src_on_path()

from network_sim.tri_gtia_view import main as _network_sim_main  # noqa: E402


def main() -> None:
    _network_sim_main()


if __name__ == "__main__":
    main()
