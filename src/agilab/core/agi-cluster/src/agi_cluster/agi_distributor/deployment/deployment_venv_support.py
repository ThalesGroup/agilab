"""Project virtualenv path helpers for local deployment flows."""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path

from agi_env.process_support import project_virtualenv_root, project_virtualenv_script_path


PYTHON_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def project_venv_python(project: Path, *, os_name: str = os.name) -> Path:
    """Return the Python executable path for a project's managed virtualenv."""

    return project_virtualenv_script_path(project, "python", os_name=os_name)


def project_venv_root(project: Path) -> Path:
    """Return the managed virtualenv root for a project."""

    return project_virtualenv_root(project)


def python_version_tuple(value: str | None) -> tuple[int, ...] | None:
    """Parse a Python version-like string into an integer tuple."""

    if not value:
        return None
    match = PYTHON_VERSION_RE.search(value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def project_venv_cfg_version(project: Path) -> tuple[int, ...] | None:
    """Read the Python version recorded in a project's ``pyvenv.cfg``."""

    cfg = project_venv_root(project) / "pyvenv.cfg"
    try:
        lines = cfg.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for line in lines:
        key, separator, raw_value = line.partition("=")
        if not separator:
            continue
        if key.strip().lower() not in {"version", "version_info"}:
            continue
        parsed = python_version_tuple(raw_value.strip())
        if parsed:
            return parsed
    return None


def project_venv_matches(
    project: Path,
    *,
    os_name: str = os.name,
    python_version: str | None = None,
) -> bool:
    """Return whether the project virtualenv exists and matches a requested version."""

    if not project_venv_python(project, os_name=os_name).exists():
        return False

    requested = python_version_tuple(python_version)
    if not requested:
        return True

    actual = project_venv_cfg_version(project)
    if not actual:
        return False
    return actual[: len(requested)] == requested


def project_site_packages_dir(
    project: Path,
    *,
    os_name: str = os.name,
    python_version: str | None = None,
) -> Path:
    """Return the site-packages directory for a project's managed virtualenv."""

    venv_root = project_venv_root(project)
    if os_name == "nt":
        return venv_root / "Lib" / "site-packages"

    if python_version:
        python_parts = str(python_version).split(".")
        if len(python_parts) >= 2 and python_parts[-1].endswith("t"):
            python_dir = f"{python_parts[0]}.{python_parts[1].removesuffix('t')}t"
            return venv_root / "lib" / f"python{python_dir}" / "site-packages"

    requested = python_version_tuple(python_version)
    version = requested or project_venv_cfg_version(project)
    if version and len(version) >= 2:
        return venv_root / "lib" / f"python{version[0]}.{version[1]}" / "site-packages"

    lib_root = venv_root / "lib"
    try:
        candidates = sorted(lib_root.glob("python*/site-packages"))
    except OSError:
        candidates = []
    if candidates:
        return candidates[0]

    fallback = python_version_tuple(platform.python_version()) or (3, 13)
    return venv_root / "lib" / f"python{fallback[0]}.{fallback[1]}" / "site-packages"
