"""Shared Python contract helpers for AGILAB deployment projects."""

from __future__ import annotations

from pathlib import Path

import tomlkit

from agi_env.runtime.atomic_write_support import atomic_write_text


MIN_WORKER_REQUIRES_PYTHON = ">=3.12"
PYPROJECT_PARSE_EXCEPTIONS = (OSError, tomlkit.exceptions.ParseError)  # ty: ignore[possibly-missing-submodule]


def _python_version_prefix_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in version.strip().split("."):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts)


def _raise_requires_python_floor(
    requires_python: str | None,
    *,
    minimum_spec: str = MIN_WORKER_REQUIRES_PYTHON,
) -> str | None:
    if not requires_python:
        return minimum_spec

    minimum_version = minimum_spec.removeprefix(">=")
    minimum_tuple = _python_version_prefix_tuple(minimum_version)
    parts = [part.strip() for part in str(requires_python).split(",") if part.strip()]
    if not parts:
        return minimum_spec

    changed = False
    has_floor = False
    normalized: list[str] = []
    for part in parts:
        if part.startswith(">="):
            has_floor = True
            current_tuple = _python_version_prefix_tuple(part.removeprefix(">="))
            if current_tuple and current_tuple < minimum_tuple:
                normalized.append(minimum_spec)
                changed = True
            else:
                normalized.append(part)
        else:
            normalized.append(part)

    if not has_floor:
        if any(part.startswith(("==", "===", "~=")) for part in parts):
            return requires_python
        normalized.insert(0, minimum_spec)
        changed = True

    result = ",".join(normalized)
    return result if changed else requires_python


def _normalize_worker_requires_python_floor(
    pyproject_file: Path,
    *,
    minimum_spec: str = MIN_WORKER_REQUIRES_PYTHON,
    raise_on_parse_error: bool = False,
) -> bool:
    try:
        data = tomlkit.parse(pyproject_file.read_text())
    except PYPROJECT_PARSE_EXCEPTIONS:
        if raise_on_parse_error:
            raise
        return False

    project_tbl = data.get("project")
    if not (
        hasattr(project_tbl, "get") and hasattr(project_tbl, "__setitem__")
    ):
        project_tbl = tomlkit.table()

    current = project_tbl.get("requires-python")
    updated = _raise_requires_python_floor(
        str(current) if current is not None else None,
        minimum_spec=minimum_spec,
    )
    if updated is None or updated == current:
        return False

    project_tbl["requires-python"] = updated
    data["project"] = project_tbl
    atomic_write_text(pyproject_file, tomlkit.dumps(data))
    return True
