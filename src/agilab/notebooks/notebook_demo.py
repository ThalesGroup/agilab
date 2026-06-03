"""Small helpers for AGILAB tutorial notebooks.

The helpers keep notebook cells compact while leaving the AGILAB flow visible:
build an app environment, build a run request, optionally install the worker,
then call ``AGI.run(...)`` in the notebook.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agilab.notebooks.notebook_colab_support import (
    install_if_needed as _install_if_needed_with_agi,
    worker_env_ready,
    worker_venv_path,
)

DEFAULT_NOTEBOOK_APP = "minimal_app_project"
DEFAULT_LOCAL_SCHEDULER = "127.0.0.1"
DEFAULT_LOCAL_WORKERS = {DEFAULT_LOCAL_SCHEDULER: 1}
DEFAULT_LOCAL_MODE = 0


@dataclass(frozen=True)
class NotebookAgiCoreContext:
    """Visible notebook context for an ``AGI.run(...)`` core handoff."""

    app: str
    app_env: Any
    request: Any
    log_root: Path


def _normalise_project_app(app: str | None) -> str:
    value = str(app or DEFAULT_NOTEBOOK_APP).strip().replace("-", "_")
    if not value:
        value = DEFAULT_NOTEBOOK_APP
    if not value.endswith(("_project", "_worker")):
        value = f"{value}_project"
    return value


def _app_aliases(app: str | None) -> tuple[str, ...]:
    project_app = _normalise_project_app(app)
    aliases = [project_app]
    if project_app.endswith("_project"):
        aliases.append(project_app.removesuffix("_project"))
    return tuple(dict.fromkeys(aliases))


def _is_app_project(path: Path) -> bool:
    try:
        return path.is_dir() and (
            (path / "pyproject.toml").is_file()
            or (path / "src" / "app_settings.toml").is_file()
        )
    except OSError:
        return False


def _root_for_app(root: Path, app: str) -> Path | None:
    root = Path(root).expanduser()
    aliases = _app_aliases(app)
    if _is_app_project(root) and root.name in aliases:
        return root.parent
    for alias in aliases:
        candidate = root / alias
        if _is_app_project(candidate):
            return root
        builtin_candidate = root / "builtin" / alias
        if _is_app_project(builtin_candidate):
            return root / "builtin"
    return None


def _package_dir(package: str) -> Path | None:
    try:
        spec = importlib.util.find_spec(package)
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    if spec is None:
        return None
    locations = getattr(spec, "submodule_search_locations", None)
    if locations:
        for location in locations:
            if location:
                return Path(location).resolve()
    origin = getattr(spec, "origin", None)
    if origin:
        return Path(origin).resolve().parent
    return None


def _installed_app_project_root(app: str) -> Path | None:
    try:
        from agi_env.app_provider_registry import resolve_installed_app_project
    except ImportError:
        return None
    try:
        return resolve_installed_app_project(app)
    except Exception:
        return None


def resolve_notebook_apps_path(
    app: str | None = DEFAULT_NOTEBOOK_APP,
    *,
    apps_path: str | Path | None = None,
    start: str | Path | None = None,
) -> Path:
    """Resolve the apps root used by demo notebooks.

    The lookup supports source checkouts, the ``agi-apps`` package layout, and
    app-provider entry points. Pass ``apps_path=...`` to make the root explicit.
    """

    project_app = _normalise_project_app(app)
    explicit_roots = [Path(apps_path).expanduser()] if apps_path is not None else []
    for root in explicit_roots:
        resolved = _root_for_app(root, project_app)
        if resolved is not None:
            return resolved

    search_start = Path(start).expanduser() if start is not None else Path.cwd()
    try:
        search_start = search_start.resolve()
    except OSError:
        pass
    source_candidates = [search_start, *search_start.parents]
    for candidate in source_candidates:
        for root in (
            candidate / "src" / "agilab" / "apps" / "builtin",
            candidate / "src" / "agilab" / "apps",
            candidate / "agilab" / "apps" / "builtin",
            candidate / "agilab" / "apps",
        ):
            resolved = _root_for_app(root, project_app)
            if resolved is not None:
                return resolved

    for package in ("agilab.apps", "agilab"):
        package_dir = _package_dir(package)
        if package_dir is None:
            continue
        roots = [package_dir]
        if package == "agilab":
            roots.append(package_dir / "apps")
        for root in roots:
            resolved = _root_for_app(root, project_app)
            if resolved is not None:
                return resolved

    installed_project = _installed_app_project_root(project_app)
    if installed_project is not None:
        resolved = _root_for_app(installed_project, project_app)
        if resolved is not None:
            return resolved
        return installed_project.parent

    raise FileNotFoundError(
        "Could not find AGILAB demo app "
        f"{project_app!r}. Install 'agilab[examples]' or 'agi-apps', "
        "or pass apps_path=... to notebook_app_env(...)."
    )


def _import_agi_env() -> type:
    from agi_env import AgiEnv

    return AgiEnv


def _import_run_request() -> type:
    from agi_cluster.agi_distributor import RunRequest

    return RunRequest


def _import_agi() -> Any:
    from agi_cluster.agi_distributor import AGI

    return AGI


def notebook_app_env(
    app: str | None = DEFAULT_NOTEBOOK_APP,
    *,
    apps_path: str | Path | None = None,
    verbose: int = 0,
    start: str | Path | None = None,
    **kwargs: Any,
) -> Any:
    """Create the ``AgiEnv`` used by the notebook demo cells."""

    project_app = _normalise_project_app(app)
    resolved_apps_path = resolve_notebook_apps_path(project_app, apps_path=apps_path, start=start)
    AgiEnv = _import_agi_env()
    return AgiEnv(apps_path=resolved_apps_path, app=project_app, verbose=verbose, **kwargs)


def notebook_local_request(
    *,
    scheduler: str = DEFAULT_LOCAL_SCHEDULER,
    workers: Mapping[str, int] | None = None,
    mode: int | list[int] | str | None = DEFAULT_LOCAL_MODE,
    params: Mapping[str, Any] | None = None,
    **app_params: Any,
) -> Any:
    """Create a small local ``RunRequest`` for notebook demos."""

    if params is not None and app_params:
        raise ValueError("Pass either params=... or keyword app parameters, not both.")
    RunRequest = _import_run_request()
    request_params = dict(params if params is not None else app_params)
    worker_map = dict(DEFAULT_LOCAL_WORKERS if workers is None else workers)
    return RunRequest(
        params=request_params,
        scheduler=scheduler,
        workers=worker_map,
        mode=mode,
    )


def notebook_agi_core_context(
    app: str | None = DEFAULT_NOTEBOOK_APP,
    *,
    apps_path: str | Path | None = None,
    verbose: int = 0,
    start: str | Path | None = None,
    env_kwargs: Mapping[str, Any] | None = None,
    scheduler: str = DEFAULT_LOCAL_SCHEDULER,
    workers: Mapping[str, int] | None = None,
    mode: int | list[int] | str | None = DEFAULT_LOCAL_MODE,
    params: Mapping[str, Any] | None = None,
    **app_params: Any,
) -> NotebookAgiCoreContext:
    """Create the compact notebook context while keeping ``AGI.run`` visible."""

    project_app = _normalise_project_app(app)
    app_env = notebook_app_env(
        project_app,
        apps_path=apps_path,
        verbose=verbose,
        start=start,
        **dict(env_kwargs or {}),
    )
    request = notebook_local_request(
        scheduler=scheduler,
        workers=workers,
        mode=mode,
        params=params,
        **app_params,
    )
    return NotebookAgiCoreContext(
        app=project_app,
        app_env=app_env,
        request=request,
        log_root=notebook_log_root(app_env),
    )


def _scheduler_from_request(request: Any | None, fallback: str | None) -> str:
    return str(fallback or getattr(request, "scheduler", None) or DEFAULT_LOCAL_SCHEDULER)


def _workers_from_request(
    request: Any | None,
    fallback: Mapping[str, int] | None,
) -> dict[str, int]:
    if fallback is not None:
        return dict(fallback)
    request_workers = getattr(request, "workers", None)
    if request_workers is not None:
        return dict(request_workers)
    return dict(DEFAULT_LOCAL_WORKERS)


def _modes_from_request(request: Any | None, fallback: int | None) -> int:
    if fallback is not None:
        return int(fallback)
    request_mode = getattr(request, "mode", None)
    return request_mode if isinstance(request_mode, int) else DEFAULT_LOCAL_MODE


async def install_if_needed(
    app_env: Any,
    *,
    request: Any | None = None,
    scheduler: str | None = None,
    workers: Mapping[str, int] | None = None,
    modes_enabled: int | None = None,
    print_fn=print,
) -> bool:
    """Install the local notebook worker only when its venv is missing or stale."""

    AGI = _import_agi()
    return await _install_if_needed_with_agi(
        AGI,
        app_env,
        scheduler=_scheduler_from_request(request, scheduler),
        workers=_workers_from_request(request, workers),
        modes_enabled=_modes_from_request(request, modes_enabled),
        print_fn=print_fn,
    )


def notebook_log_root(app_env_or_app: Any = DEFAULT_NOTEBOOK_APP) -> Path:
    """Return the default execute log root used by the notebook examples."""

    target = getattr(app_env_or_app, "share_target_name", None) or getattr(
        app_env_or_app,
        "target",
        None,
    )
    if not target:
        target = _normalise_project_app(str(app_env_or_app)).removesuffix("_project")
    return Path.home() / "log" / "execute" / str(target)


__all__ = [
    "DEFAULT_LOCAL_MODE",
    "DEFAULT_LOCAL_SCHEDULER",
    "DEFAULT_LOCAL_WORKERS",
    "DEFAULT_NOTEBOOK_APP",
    "NotebookAgiCoreContext",
    "install_if_needed",
    "notebook_agi_core_context",
    "notebook_app_env",
    "notebook_local_request",
    "notebook_log_root",
    "resolve_notebook_apps_path",
    "worker_env_ready",
    "worker_venv_path",
]
