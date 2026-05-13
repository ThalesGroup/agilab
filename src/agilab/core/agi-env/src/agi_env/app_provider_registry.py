"""Discovery helpers for installed AGILAB app project packages."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


APP_PROVIDER_ENTRYPOINT_GROUP = "agilab.apps"


@dataclass(frozen=True, slots=True)
class InstalledAppProject:
    """Resolved metadata for an installed AGILAB app project."""

    name: str
    project_root: Path
    provider: str = ""


def normalize_app_name(value: str | None) -> str:
    """Normalize app aliases for lookup while preserving ``*_project`` semantics."""

    return str(value or "").strip().replace("-", "_")


def app_name_aliases(value: str | None) -> tuple[str, ...]:
    """Return lookup aliases for app names such as ``flight`` and ``flight_project``."""

    normalized = normalize_app_name(value)
    if not normalized:
        return ()
    aliases: list[str] = []

    def add(alias: str) -> None:
        alias = normalize_app_name(alias)
        if alias and alias not in aliases:
            aliases.append(alias)

    add(normalized)
    if normalized.endswith("_project"):
        add(normalized.removesuffix("_project"))
    else:
        add(f"{normalized}_project")
    return tuple(aliases)


def is_app_project_root(path: Path) -> bool:
    """Return whether ``path`` looks like an AGILAB app project root."""

    try:
        return path.is_dir() and (
            (path / "pyproject.toml").is_file()
            or (path / "src" / "app_settings.toml").is_file()
        )
    except OSError:
        return False


def _entry_points(entry_points_fn: Callable[[], Any]) -> Iterable[Any]:
    try:
        entry_points = entry_points_fn()
    except Exception:
        return ()
    select = getattr(entry_points, "select", None)
    if callable(select):
        try:
            return tuple(select(group=APP_PROVIDER_ENTRYPOINT_GROUP))
        except Exception:
            return ()
    if isinstance(entry_points, Mapping):
        return tuple(entry_points.get(APP_PROVIDER_ENTRYPOINT_GROUP, ()))
    return ()


def _coerce_project_root(value: Any) -> Path | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        value = value.get("project_root") or value.get("path") or value.get("root")
    if callable(value):
        try:
            value = value()
        except Exception:
            return None
    try:
        path = Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return path if is_app_project_root(path) else None


def discover_installed_app_projects(
    *,
    entry_points_fn: Callable[[], Any] = importlib_metadata.entry_points,
) -> tuple[InstalledAppProject, ...]:
    """Discover installed app project roots advertised through entry points."""

    projects: list[InstalledAppProject] = []
    seen: set[str] = set()
    for entry_point in sorted(_entry_points(entry_points_fn), key=lambda item: str(getattr(item, "name", ""))):
        try:
            loaded = entry_point.load()
        except Exception:
            continue
        root = _coerce_project_root(loaded)
        if root is None:
            continue
        root_key = root.as_posix()
        if root_key in seen:
            continue
        seen.add(root_key)
        projects.append(
            InstalledAppProject(
                name=root.name,
                project_root=root,
                provider=str(getattr(entry_point, "name", "") or ""),
            )
        )
    return tuple(projects)


def installed_app_project_paths(
    *,
    entry_points_fn: Callable[[], Any] = importlib_metadata.entry_points,
) -> tuple[Path, ...]:
    """Return installed app project paths in deterministic order."""

    return tuple(project.project_root for project in discover_installed_app_projects(entry_points_fn=entry_points_fn))


def resolve_installed_app_project(
    app_name: str | None,
    *,
    projects: Iterable[InstalledAppProject] | None = None,
    entry_points_fn: Callable[[], Any] = importlib_metadata.entry_points,
) -> Path | None:
    """Resolve one installed app project by app or project name."""

    aliases = set(app_name_aliases(app_name))
    if not aliases:
        return None
    discovered = tuple(projects) if projects is not None else discover_installed_app_projects(entry_points_fn=entry_points_fn)
    for project in discovered:
        names = set(app_name_aliases(project.name))
        names.update(app_name_aliases(project.provider))
        if aliases & names:
            return project.project_root
    return None


__all__ = [
    "APP_PROVIDER_ENTRYPOINT_GROUP",
    "InstalledAppProject",
    "app_name_aliases",
    "discover_installed_app_projects",
    "installed_app_project_paths",
    "is_app_project_root",
    "normalize_app_name",
    "resolve_installed_app_project",
]
