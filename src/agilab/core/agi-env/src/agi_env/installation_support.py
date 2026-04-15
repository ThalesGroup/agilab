"""Pure helpers for AGILAB installation marker and source discovery."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Callable


def installation_marker_path(
    *,
    os_name: str | None = None,
    home: str | Path | None = None,
    localappdata: str | Path | None = None,
) -> Path:
    """Return the persisted AGILAB marker path for the current platform."""

    active_os = os_name or os.name
    if active_os == "nt":
        root = Path(localappdata or "")
        return root / "agilab/.agilab-path"
    root = Path(home) if home is not None else Path.home()
    return root / ".local/share/agilab/.agilab-path"


def read_agilab_installation_marker(
    marker_path: Path,
    *,
    logger=None,
) -> Path | bool | None:
    """Read and validate a persisted AGILAB installation marker."""

    if not marker_path.exists():
        return False

    try:
        with marker_path.open("r", encoding="utf-8-sig") as handle:
            install_path = handle.read().strip()
        agilab_path = Path(install_path)
        if install_path and agilab_path.exists():
            return agilab_path
        raise ValueError("Installation path file is empty or invalid.")
    except FileNotFoundError:
        if logger:
            logger.error(f"File {marker_path} does not exist.")
    except PermissionError:
        if logger:
            logger.error(f"Permission denied when accessing {marker_path}.")
    except (OSError, ValueError) as exc:
        if logger:
            logger.error(f"An error occurred: {exc}")
    return None


def locate_agilab_installation_path(
    *,
    module_file: str | Path,
    find_spec: Callable[[str], object | None] = importlib.util.find_spec,
) -> Path:
    """Locate the AGILAB installation root from package metadata or source layout."""

    try:
        spec = find_spec("agilab")
    except ModuleNotFoundError:
        spec = None

    origin = getattr(spec, "origin", None) if spec is not None else None
    if origin:
        agilab_root = Path(origin).resolve().parent
        if (agilab_root / "apps").exists():
            return agilab_root

    module_path = Path(module_file).resolve()
    base_dir = module_path.parents[2] / "agi_env"
    candidate_repo = module_path.parents[4]
    if (candidate_repo / "apps").exists():
        return candidate_repo

    before, sep, _ = str(base_dir).rpartition("agilab")
    fallback = Path(before) / sep if sep else base_dir.parent
    if (fallback / "apps").exists():
        return fallback
    return base_dir.parent
