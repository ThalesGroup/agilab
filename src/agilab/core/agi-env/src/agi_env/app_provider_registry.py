"""Discovery helpers for installed AGILAB app project packages."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from pathlib import Path
import re
import tomllib
from typing import Any, Callable, Iterable, Mapping


APP_PROVIDER_ENTRYPOINT_GROUP = "agilab.apps"
_RUNTIME_TARGET_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PUBLIC_RUNTIME_TARGET_ALIASES: dict[str, str] = {
    "flight_telemetry": "flight",
    "mission_decision": "data_io_2026",
    "weather_forecast": "meteo_forecast",
}


@dataclass(frozen=True, slots=True)
class InstalledAppProject:
    """Resolved metadata for an installed AGILAB app project."""

    name: str
    project_root: Path
    provider: str = ""


def normalize_app_name(value: str | None) -> str:
    """Normalize app aliases for lookup while preserving ``*_project`` semantics."""

    return str(value or "").strip().replace("-", "_")


def default_app_runtime_target(app_name: str | None) -> str:
    """Return the conventional runtime target derived from an app or worker name."""

    normalized = normalize_app_name(app_name)
    if normalized.endswith("_project"):
        normalized = normalized.removesuffix("_project")
    elif normalized.endswith("_worker"):
        normalized = normalized.removesuffix("_worker")
    return normalized


def aliased_app_runtime_target(app_name: str | None) -> str:
    """Return the runtime target including known public-name aliases."""

    target = default_app_runtime_target(app_name)
    return PUBLIC_RUNTIME_TARGET_ALIASES.get(target, target)


def _coerce_runtime_target(value: object) -> str:
    target = default_app_runtime_target(str(value or ""))
    if not target or not _RUNTIME_TARGET_RE.fullmatch(target):
        raise ValueError(
            "[tool.agilab].runtime_target must be a Python identifier-like name "
            f"without path separators, got {value!r}"
        )
    return target


def _runtime_source_exists(project_root: Path, target: str) -> bool:
    if not target:
        return False
    source_root = project_root / "src" / target
    return source_root.is_dir() and (
        (source_root / f"{target}.py").is_file()
        or (source_root / "__init__.py").is_file()
    )


def resolve_app_runtime_target(project_root: Path | None, app_name: str | None) -> str:
    """Resolve the runtime target for a project, allowing public names to differ from modules."""

    fallback = default_app_runtime_target(app_name)
    if project_root is None:
        return fallback
    pyproject = Path(project_root) / "pyproject.toml"
    if not pyproject.is_file():
        return fallback
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    raw_target = data.get("tool", {}).get("agilab", {}).get("runtime_target")
    if raw_target is None:
        raw_project_name = data.get("project", {}).get("name")
        for raw_name in (raw_project_name, app_name):
            conventional_target = default_app_runtime_target(str(raw_name or ""))
            aliased_target = PUBLIC_RUNTIME_TARGET_ALIASES.get(conventional_target)
            for candidate_target in (conventional_target, aliased_target):
                if candidate_target and _runtime_source_exists(Path(project_root), candidate_target):
                    return candidate_target
        if raw_project_name:
            return default_app_runtime_target(str(raw_project_name))
        return fallback
    return _coerce_runtime_target(raw_target)


def app_name_aliases(value: str | None) -> tuple[str, ...]:
    """Return lookup aliases for app names such as ``flight`` and ``flight_telemetry_project``."""

    normalized = normalize_app_name(value)
    if not normalized:
        return ()
    aliases: list[str] = []

    def add(alias: str) -> None:
        alias = normalize_app_name(alias)
        if alias and alias not in aliases:
            aliases.append(alias)

    add(normalized)
    runtime_target = default_app_runtime_target(normalized)
    add(runtime_target)
    add(f"{runtime_target}_project")
    public_alias_target = PUBLIC_RUNTIME_TARGET_ALIASES.get(runtime_target)
    if public_alias_target:
        add(public_alias_target)
        add(f"{public_alias_target}_project")
    if normalized.endswith("_project"):
        add(normalized.removesuffix("_project"))
    else:
        add(f"{normalized}_project")
    for public_name, alias_target in PUBLIC_RUNTIME_TARGET_ALIASES.items():
        if runtime_target == alias_target:
            add(public_name)
            add(f"{public_name}_project")
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
    "PUBLIC_RUNTIME_TARGET_ALIASES",
    "aliased_app_runtime_target",
    "app_name_aliases",
    "discover_installed_app_projects",
    "default_app_runtime_target",
    "installed_app_project_paths",
    "is_app_project_root",
    "normalize_app_name",
    "resolve_app_runtime_target",
    "resolve_installed_app_project",
]
