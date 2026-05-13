"""Pure bootstrap helpers for AgiEnv initialisation."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

from .app_provider_registry import resolve_installed_app_project


@dataclass(frozen=True)
class ActiveAppSelection:
    app: str
    active_app: Path


def coerce_active_app_request(
    app: str | None,
    kwargs: dict[str, Any],
    *,
    path_cls=Path,
) -> tuple[str | None, Path | None]:
    """Support the legacy ``active_app=...`` alias while keeping the app name explicit."""
    if app is None and "active_app" in kwargs:
        value = kwargs.pop("active_app")
        try:
            active_app_override = path_cls(value)
        except (TypeError, ValueError):
            active_app_override = None
        try:
            app = path_cls(value).name
        except (TypeError, ValueError):
            app = str(value) if value is not None else None
        return app, active_app_override
    return app, None


def resolve_install_type(
    apps_path: Path | None,
    *,
    active_app_override: Path | None = None,
) -> tuple[int, bool]:
    """Infer the legacy install type and whether a worker env was detected."""
    try:
        if active_app_override is not None and apps_path is None:
            return 1, False
        if apps_path is None or "wenv" in set(apps_path.resolve().parts):
            return 2, True
        if apps_path.parents[1].name == "src":
            return 1, False
    except (AttributeError, IndexError, OSError, RuntimeError, TypeError, ValueError):
        pass
    return 0, False


def resolve_package_dir(package: str, *, find_spec_fn=None, path_cls=Path) -> Path:
    """Locate an installed package directory from its import spec."""
    if find_spec_fn is None:
        find_spec_fn = importlib.util.find_spec
    try:
        spec = find_spec_fn(package)
    except (ModuleNotFoundError, ValueError):
        spec = None

    if spec:
        search_locations = getattr(spec, "submodule_search_locations", None)
        if search_locations:
            for location in search_locations:
                if location:
                    path = path_cls(location)
                    if path.exists():
                        return path.resolve()

        origin = getattr(spec, "origin", None)
        if origin:
            path = path_cls(origin).parent
            if path.exists():
                return path.resolve()

    raise ModuleNotFoundError(f"Package '{package}' is not installed in the current environment.")


def resolve_requested_apps_path(
    *,
    env_apps_path: str,
    explicit_apps_path: Path | None,
    active_app_override: Path | None,
    path_cls=Path,
) -> tuple[Path | None, Path | None]:
    """Resolve the effective apps root and any builtin root implied by an override path."""
    if explicit_apps_path is not None:
        apps_path = path_cls(explicit_apps_path).expanduser()
        try:
            apps_path = apps_path.resolve()
        except FileNotFoundError:
            pass
        return apps_path, None

    def _is_absolute_path(value: Path) -> bool:
        try:
            return bool(value.is_absolute())
        except AttributeError:
            try:
                return bool(path_cls(value).expanduser().is_absolute())
            except (TypeError, ValueError):
                return False

    def _apps_path_from_active_override(value: Path) -> tuple[Path | None, Path | None]:
        try:
            candidate_parent = value.parent.resolve()
        except OSError:
            candidate_parent = value.parent
        if candidate_parent.name == "builtin" and candidate_parent.parent.name == "apps":
            return candidate_parent.parent, candidate_parent
        return candidate_parent, None

    if active_app_override is not None and _is_absolute_path(active_app_override):
        return _apps_path_from_active_override(active_app_override)

    if env_apps_path:
        apps_path = path_cls(env_apps_path).expanduser()
        try:
            apps_path = apps_path.resolve()
        except OSError:
            pass
        return apps_path, None

    if active_app_override is not None:
        return _apps_path_from_active_override(active_app_override)

    return None, None


def resolve_builtin_apps_path(
    *,
    apps_path: Path | None,
    repo_root: Path,
    agilab_pck: Path,
) -> Path | None:
    """Return the first builtin apps root that exists."""
    candidates = [
        apps_path if apps_path and apps_path.name == "builtin" else None,
        apps_path / "builtin" if apps_path else None,
        repo_root / "apps" / "builtin",
        agilab_pck / "apps" / "builtin",
    ]
    return next((candidate for candidate in candidates if candidate and candidate.exists()), None)


def resolve_default_apps_path(
    *,
    apps_path: Path | None,
    is_worker_env: bool,
    default_apps_root: Path,
    apps_repository_root: Path | None,
) -> tuple[Path | None, Path | None]:
    """Fill in the apps root for manager/source installs when the caller did not supply one."""
    if is_worker_env or apps_path is not None:
        return apps_path, apps_repository_root
    if apps_repository_root is not None:
        chosen = default_apps_root if default_apps_root.exists() else apps_repository_root
        return chosen, apps_repository_root
    return default_apps_root, None


def resolve_active_app_selection(
    *,
    app: str | None,
    active_app_override: Path | None,
    apps_path: Path | None,
    builtin_apps_path: Path | None,
    installed_app_projects: Sequence[Path] = (),
    home_abs: Path,
    is_worker_env: bool,
    default_app: str,
    path_cls=Path,
) -> ActiveAppSelection:
    """Resolve the selected app name and filesystem root."""
    if is_worker_env:
        if not app:
            raise ValueError("app is required when self.is_worker_env")
        return ActiveAppSelection(app=app, active_app=home_abs / "wenv" / app)

    if app is None:
        app = str(default_app or "").strip() or "flight_project"

    if active_app_override is not None and path_cls(active_app_override).exists():
        active_app = path_cls(active_app_override)
    else:
        base_dir = apps_path if apps_path is not None else path_cls()
        try:
            base_dir = base_dir.resolve()
        except OSError:
            pass
        active_app = base_dir / app
        active_app_exists = False
        try:
            active_app_exists = active_app.exists()
        except OSError:
            active_app_exists = False
        if builtin_apps_path:
            candidate_builtin = builtin_apps_path / app
            try:
                if candidate_builtin.exists():
                    active_app = candidate_builtin
                    active_app_exists = True
            except OSError:
                pass
        if not active_app_exists:
            installed_app = resolve_installed_app_project(
                app,
                projects=[
                    SimpleNamespace(name=project.name, project_root=project, provider=project.name)
                    for project in installed_app_projects
                ],
            )
            if installed_app is not None:
                active_app = installed_app

    return ActiveAppSelection(app=app, active_app=active_app)


def can_link_repo_apps(
    *,
    apps_path: Path | None,
    active_app: Path,
    builtin_apps_path: Path | None,
    is_worker_env: bool,
    skip_repo_links: bool,
) -> bool:
    """Return whether repository apps may be linked into the chosen apps root."""
    if apps_path is None or is_worker_env or skip_repo_links:
        return False

    is_builtin_app = False
    try:
        if builtin_apps_path and active_app.resolve().is_relative_to(builtin_apps_path.resolve()):
            is_builtin_app = True
    except (OSError, ValueError):
        is_builtin_app = False
    if is_builtin_app:
        return False

    try:
        apps_root_candidate = apps_path.resolve(strict=False)
    except OSError:
        apps_root_candidate = apps_path
    try:
        active_parent = active_app.parent.resolve(strict=False)
    except OSError:
        active_parent = active_app.parent

    if apps_root_candidate != active_parent:
        return False

    normalized_name = apps_root_candidate.name.lower()
    return not (
        normalized_name.endswith("_project") or normalized_name.endswith("_worker")
    )
