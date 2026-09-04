"""Generic optional filesystem path providers discovered through entry points."""

from __future__ import annotations

from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


OPTIONAL_PATH_ENTRY_POINT_GROUP = "agi_env.paths"
OPTIONAL_PATH_DISCOVERY_EXCEPTIONS: tuple[type[Exception], ...] = (Exception,)


def _entry_points(entry_points_fn: Callable[[], Any]) -> Iterable[Any]:
    """Return optional path entry points across supported metadata APIs."""

    try:
        entry_points = entry_points_fn()
    except OPTIONAL_PATH_DISCOVERY_EXCEPTIONS:
        return ()

    select = getattr(entry_points, "select", None)
    if callable(select):
        try:
            return tuple(select(group=OPTIONAL_PATH_ENTRY_POINT_GROUP))
        except OPTIONAL_PATH_DISCOVERY_EXCEPTIONS:
            return ()
    if isinstance(entry_points, Mapping):
        return tuple(entry_points.get(OPTIONAL_PATH_ENTRY_POINT_GROUP, ()))
    return ()


def resolve_optional_path(
    name: str,
    *,
    entry_points_fn: Callable[[], Any] = importlib_metadata.entry_points,
) -> Path | None:
    """Resolve one named path provider without importing an owning package directly."""

    provider_name = str(name or "").strip()
    if not provider_name:
        return None

    entry_points = sorted(
        _entry_points(entry_points_fn),
        key=lambda item: (
            str(getattr(item, "name", "")),
            str(getattr(item, "value", "")),
        ),
    )
    for entry_point in entry_points:
        if str(getattr(entry_point, "name", "")) != provider_name:
            continue
        try:
            value = entry_point.load()
            if callable(value):
                value = value()
            if isinstance(value, Mapping):
                value = value.get("path") or value.get("root")
            if value is not None:
                return Path(value).expanduser()
        except OPTIONAL_PATH_DISCOVERY_EXCEPTIONS:
            continue
    return None
