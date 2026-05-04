"""Dask runtime dependency helpers for generated worker environments."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from shlex import quote
from typing import Any


DASK_RUNTIME_SPEC = "dask[distributed]"


def dask_mode_enabled(agi_cls: Any) -> bool:
    mode = int(getattr(agi_cls, "_mode", 0) or 0)
    dask_mode = int(getattr(agi_cls, "DASK_MODE", 0) or 0)
    return bool(dask_mode and (mode & dask_mode))


def dask_runtime_install_command(
    uv: str,
    project: Path | PurePosixPath | str,
    *,
    pyvers: str | None = None,
    offline_flag: str = "",
) -> str:
    project_value = project.as_posix() if isinstance(project, (Path, PurePosixPath)) else str(project)
    python_selector = f" -p {quote(pyvers)}" if pyvers else ""
    return (
        f"{uv} {offline_flag}--project {quote(project_value)} "
        f"add{python_selector} {quote(DASK_RUNTIME_SPEC)}"
    )
