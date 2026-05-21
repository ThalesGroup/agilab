from __future__ import annotations

import hashlib
import importlib.util
import sys
import tomllib
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

APP_SURFACE_SECTION = "app_surface"


def _read_app_settings(active_app: Path) -> dict[str, Any]:
    settings_path = active_app / "src" / "app_settings.toml"
    try:
        with settings_path.open("rb") as stream:
            payload = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def app_surface_config(
    active_app: str | Path | None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the declared app-owned UI surface configuration, if present."""
    configured_surface = config.get(APP_SURFACE_SECTION) if isinstance(config, Mapping) else None
    if isinstance(configured_surface, Mapping) and configured_surface.get("entrypoint"):
        return dict(configured_surface)
    if active_app is None:
        return {}
    seed_surface = _read_app_settings(Path(active_app).expanduser()).get(APP_SURFACE_SECTION)
    if isinstance(seed_surface, Mapping) and seed_surface.get("entrypoint"):
        return dict(seed_surface)
    return {}


def app_surface_title(config: Mapping[str, Any] | None) -> str:
    if not isinstance(config, Mapping):
        return "App Surface"
    title = config.get("title")
    return str(title).strip() or "App Surface"


def resolve_app_surface_entrypoint(
    active_app: str | Path | None,
    entrypoint: object,
) -> Path | None:
    """Resolve an app-owned Streamlit surface entrypoint inside the active app."""
    if active_app is None or not isinstance(entrypoint, (str, Path)):
        return None
    app_path = Path(active_app).expanduser().resolve()
    entrypoint_path = Path(entrypoint).expanduser()
    candidates: list[Path]
    if entrypoint_path.is_absolute():
        candidates = [entrypoint_path]
    else:
        candidates = [
            app_path / "src" / entrypoint_path,
            app_path / entrypoint_path,
        ]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            continue
        if not resolved.is_file():
            continue
        try:
            resolved.relative_to(app_path)
        except ValueError:
            continue
        return resolved
    return None


def configured_app_surface_entrypoint(
    active_app: str | Path | None,
    config: Mapping[str, Any] | None = None,
) -> Path | None:
    surface_config = app_surface_config(active_app, config)
    return resolve_app_surface_entrypoint(active_app, surface_config.get("entrypoint"))


@contextmanager
def _temporary_sys_path(paths: list[Path]):
    previous = list(sys.path)
    try:
        for path in reversed(paths):
            entry = str(path)
            sys.path[:] = [existing for existing in sys.path if existing != entry]
            sys.path.insert(0, entry)
        yield
    finally:
        sys.path[:] = previous


@contextmanager
def _temporary_argv(entrypoint: Path, active_app: Path):
    previous = list(sys.argv)
    sys.argv = [str(entrypoint), "--active-app", str(active_app)]
    try:
        yield
    finally:
        sys.argv = previous


def _load_module_from_path(entrypoint: Path) -> ModuleType:
    digest = hashlib.sha1(str(entrypoint).encode("utf-8")).hexdigest()[:12]
    module_name = f"_agilab_app_surface_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, entrypoint)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"Unable to load app surface from {entrypoint}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def render_app_surface(
    active_app: str | Path | None,
    *,
    mode: str,
    config: Mapping[str, Any] | None = None,
    env: Any | None = None,
    container: Any | None = None,
    streamlit: Any | None = None,
) -> bool:
    """Render an app-owned surface inline when its module exposes a render() hook."""
    if active_app is None:
        return False
    active_app_path = Path(active_app).expanduser().resolve()
    surface_config = app_surface_config(active_app_path, config)
    entrypoint = resolve_app_surface_entrypoint(active_app_path, surface_config.get("entrypoint"))
    if entrypoint is None:
        return False
    with _temporary_sys_path([active_app_path / "src", entrypoint.parent]), _temporary_argv(entrypoint, active_app_path):
        module = _load_module_from_path(entrypoint)
        render = getattr(module, "render", None)
        if not callable(render):
            return False
        kwargs: dict[str, Any] = {
            "mode": mode,
            "active_app": active_app_path,
        }
        if env is not None:
            kwargs["env"] = env
        if container is not None:
            kwargs["container"] = container
        if streamlit is not None:
            kwargs["streamlit"] = streamlit
        render(**kwargs)
    return True
