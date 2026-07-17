"""Shared confinement checks for recursive filesystem deletion."""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from typing import Iterable


def _resolved_path(value: Path | str) -> Path:
    try:
        return Path(value).expanduser().resolve(strict=False)
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid filesystem path {value!r}: {exc}") from exc


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        pass
    else:
        return True

    # Existing case aliases on case-insensitive filesystems must follow the
    # same confinement decision as their canonical spelling.
    try:
        if not parent.exists():
            return False
    except OSError:
        return False
    candidate = path
    while True:
        try:
            if candidate.exists() and candidate.samefile(parent):
                return True
        except (OSError, ValueError):
            pass
        next_candidate = candidate.parent
        if next_candidate == candidate:
            return False
        candidate = next_candidate


def safe_destructive_path(
    path: Path | str,
    *,
    roots: Iterable[Path | str],
    label: str = "destructive operation",
    protected_paths: Iterable[Path | str] = (),
) -> Path:
    """Resolve ``path`` and prove it is a non-root descendant of a trusted root."""

    try:
        raw_value = os.fspath(path)
    except TypeError as exc:
        raise ValueError(f"{label} target must be a filesystem path") from exc
    if not isinstance(raw_value, str) or not raw_value.strip() or "\x00" in raw_value:
        raise ValueError(f"{label} target is empty or malformed")

    raw_path = Path(raw_value).expanduser()
    windows_path = PureWindowsPath(raw_value)
    if raw_path in (Path("."), Path("..")) or ".." in (
        raw_path.parts + windows_path.parts
    ):
        raise ValueError(f"{label} target must not contain parent traversal")
    if windows_path.drive and not windows_path.root:
        raise ValueError(f"{label} target must not be drive-relative")

    target = _resolved_path(raw_path)
    if target == Path(target.anchor):
        raise ValueError(f"{label} target must not be the filesystem root")

    resolved_roots = [_resolved_path(root) for root in roots]
    if not resolved_roots:
        raise ValueError(f"{label} requires a trusted confinement root")
    for root in resolved_roots:
        if _path_is_relative_to(target, root) and _path_is_relative_to(root, target):
            raise ValueError(f"{label} target must not be the confinement root")
    if not any(_path_is_relative_to(target, root) for root in resolved_roots):
        roots_text = ", ".join(str(root) for root in resolved_roots)
        raise ValueError(
            f"{label} target must stay under a trusted root ({roots_text}), got {target}"
        )

    for protected_path in protected_paths:
        protected = _resolved_path(protected_path)
        if target == protected:
            raise ValueError(f"{label} target must not be protected path {protected}")
    return target


def safe_worker_runtime_cleanup_path(
    path: Path | str,
    *,
    roots: Iterable[Path | str],
    home_path: Path | str | None = None,
    cwd_path: Path | str | None = None,
) -> Path:
    """Validate an AGILAB worker-runtime target before recursive deletion."""

    protected = tuple(
        item for item in (home_path, cwd_path) if item is not None
    )
    return safe_destructive_path(
        path,
        roots=roots,
        label="worker runtime cleanup",
        protected_paths=protected,
    )
