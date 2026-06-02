from __future__ import annotations

import hashlib
import importlib.util
import sys
import tomllib
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

APP_SURFACE_SECTION = "app_surface"
APP_SURFACE_BACKENDS_KEY = "backends"
DEFAULT_SURFACE_NAME = "streamlit"


@dataclass(frozen=True, slots=True)
class AppSurfaceSpec:
    """One launchable app-owned UI surface.

    The app runtime contract remains outside the UI.  A surface is only an
    adapter that knows how a user can interact with the app.
    """

    name: str
    backend: str
    title: str
    entrypoint: str = ""
    url: str = ""
    default: bool = False
    capabilities: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "backend": self.backend,
            "title": self.title,
            "default": self.default,
        }
        if self.entrypoint:
            payload["entrypoint"] = self.entrypoint
        if self.url:
            payload["url"] = self.url
        if self.capabilities:
            payload["capabilities"] = list(self.capabilities)
        return payload


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
    if isinstance(configured_surface, Mapping) and _has_surface_declaration(configured_surface):
        return dict(configured_surface)
    if active_app is None:
        return {}
    seed_surface = _read_app_settings(Path(active_app).expanduser()).get(APP_SURFACE_SECTION)
    if isinstance(seed_surface, Mapping) and _has_surface_declaration(seed_surface):
        return dict(seed_surface)
    return {}


def _has_surface_declaration(surface: Mapping[str, Any]) -> bool:
    if surface.get("entrypoint") or surface.get("url"):
        return True
    backends = surface.get(APP_SURFACE_BACKENDS_KEY)
    return isinstance(backends, Mapping) and any(
        isinstance(value, Mapping) and (value.get("entrypoint") or value.get("url"))
        for value in backends.values()
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        cleaned = value.strip()
        return (cleaned,) if cleaned else ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _surface_spec_from_mapping(
    name: str,
    payload: Mapping[str, Any],
    *,
    root: Mapping[str, Any],
    root_default_name: str,
    inherited_entrypoint: str = "",
) -> AppSurfaceSpec | None:
    backend = str(payload.get("backend") or name or DEFAULT_SURFACE_NAME).strip().lower()
    title = str(payload.get("title") or root.get("title") or "App Surface").strip()
    entrypoint = str(payload.get("entrypoint") or inherited_entrypoint or "").strip()
    url = str(payload.get("url") or "").strip()
    if not entrypoint and not url:
        return None
    default = bool(payload.get("default") is True or name == root_default_name)
    return AppSurfaceSpec(
        name=name,
        backend=backend,
        title=title or "App Surface",
        entrypoint=entrypoint,
        url=url,
        default=default,
        capabilities=_string_tuple(payload.get("capabilities")),
    )


def app_surface_specs(
    active_app: str | Path | None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, AppSurfaceSpec]:
    """Return named UI surfaces declared by an app.

    Backward compatibility:
    - legacy ``[app_surface] entrypoint = ...`` is exposed as the default
      ``streamlit`` surface.
    - optional ``[app_surface.backends.<name>]`` entries add explicit named
      surfaces without changing the existing ANALYSIS/ORCHESTRATE behavior.
    """

    root = app_surface_config(active_app, config)
    if not root:
        return {}

    root_default_name = str(root.get("default") or DEFAULT_SURFACE_NAME).strip()
    if not root_default_name:
        root_default_name = DEFAULT_SURFACE_NAME

    specs: dict[str, AppSurfaceSpec] = {}
    root_entrypoint = str(root.get("entrypoint") or "").strip()
    root_url = str(root.get("url") or "").strip()
    if root_entrypoint or root_url:
        legacy_spec = _surface_spec_from_mapping(
            DEFAULT_SURFACE_NAME,
            root,
            root=root,
            root_default_name=root_default_name,
        )
        if legacy_spec is not None:
            specs[legacy_spec.name] = legacy_spec

    backends = root.get(APP_SURFACE_BACKENDS_KEY)
    if isinstance(backends, Mapping):
        for name, payload in backends.items():
            if not isinstance(payload, Mapping):
                continue
            surface_name = str(name).strip()
            if not surface_name:
                continue
            inherited_entrypoint = (
                root_entrypoint if surface_name == DEFAULT_SURFACE_NAME else ""
            )
            spec = _surface_spec_from_mapping(
                surface_name,
                payload,
                root=root,
                root_default_name=root_default_name,
                inherited_entrypoint=inherited_entrypoint,
            )
            if spec is not None:
                specs[surface_name] = spec

    if specs and not any(spec.default for spec in specs.values()):
        default_name = root_default_name if root_default_name in specs else sorted(specs)[0]
        selected = specs[default_name]
        specs[default_name] = AppSurfaceSpec(
            name=selected.name,
            backend=selected.backend,
            title=selected.title,
            entrypoint=selected.entrypoint,
            url=selected.url,
            default=True,
            capabilities=selected.capabilities,
        )
    return specs


def select_app_surface_spec(
    active_app: str | Path | None,
    *,
    name: str | None = None,
    backend: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> AppSurfaceSpec | None:
    specs = app_surface_specs(active_app, config)
    if not specs:
        return None
    cleaned_name = str(name or "").strip()
    if cleaned_name:
        if cleaned_name in specs:
            return specs[cleaned_name]
        cleaned_name_backend = cleaned_name.lower()
        for spec in specs.values():
            if spec.backend == cleaned_name_backend:
                return spec
        return None
    cleaned_backend = str(backend or "").strip().lower()
    if cleaned_backend:
        for spec in specs.values():
            if spec.backend == cleaned_backend:
                return spec
        return None
    for spec in specs.values():
        if spec.default:
            return spec
    return specs[sorted(specs)[0]]


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
    *,
    surface: str | None = None,
) -> Path | None:
    spec = select_app_surface_spec(active_app, name=surface, config=config)
    if spec is None:
        return None
    return resolve_app_surface_entrypoint(active_app, spec.entrypoint)


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
    surface: str | None = None,
    env: Any | None = None,
    container: Any | None = None,
    streamlit: Any | None = None,
) -> bool:
    """Render an app-owned surface inline when its module exposes a render() hook."""
    if active_app is None:
        return False
    active_app_path = Path(active_app).expanduser().resolve()
    selected = select_app_surface_spec(active_app_path, name=surface, config=config)
    if selected is None or selected.backend != "streamlit":
        return False
    entrypoint = resolve_app_surface_entrypoint(active_app_path, selected.entrypoint)
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
