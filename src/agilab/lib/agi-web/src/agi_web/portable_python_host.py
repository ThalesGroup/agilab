"""Copy a fixed native React/Python host into a standalone application export."""

from __future__ import annotations

import hashlib
from importlib.resources import files
from pathlib import Path


PYTHON_HOST_MODULES = (
    "__init__.py", "component.py", "react_analysis.py", "react_main_interface.py",
    "python_ui.py", "python_view_session.py", "react_python_host.py", "testing.py",
    "notebook_python_view.py", "public_bind_guard.py",
)
_ASSET_DIRECTORIES = ("react_analysis_assets", "react_main_interface_assets", "react_python_host_assets")


def python_host_files() -> tuple[str, ...]:
    """Keep the module allowlist fixed while carrying each complete compiled bundle."""
    package = files("agi_web")
    assets = []
    for directory in _ASSET_DIRECTORIES:
        for asset in package.joinpath(directory).iterdir():
            if asset.is_file():
                assets.append(f"{directory}/{asset.name}")
    return (*PYTHON_HOST_MODULES, *sorted(assets))


PYTHON_HOST_FILES = python_host_files()


def export_python_host(destination: str | Path) -> dict[str, str]:
    """Write the reviewed file allowlist to a new package directory and return hashes."""
    target = Path(destination)
    if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
        raise ValueError("Native host destination must be a new or empty directory.")
    package = files("agi_web")
    payload = {name: package.joinpath(name).read_bytes() for name in python_host_files()}
    for name, content in payload.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return {name: hashlib.sha256(content).hexdigest() for name, content in payload.items()}
