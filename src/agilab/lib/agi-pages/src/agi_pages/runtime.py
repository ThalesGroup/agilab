"""Shared runtime helpers for AGILAB analysis page bundles."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tomllib
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode


def ensure_repo_on_path(anchor: str | Path) -> None:
    """Add the AGILAB source and repository roots for direct source launches."""

    here = Path(anchor).resolve()
    for parent in here.parents:
        candidate = parent / "agilab"
        if candidate.is_dir():
            src_root = candidate.parent
            repo_root = src_root.parent
            for entry in (str(src_root), str(repo_root)):
                if entry not in sys.path:
                    sys.path.insert(0, entry)
            # ``agilab`` can already be imported from another checkout or an
            # installed namespace package when a source page is launched.
            # Extend that package in place so later ``agilab.*`` imports use
            # the source tree selected by the page anchor as well.
            package = sys.modules.get("agilab")
            package_path = str(candidate)
            package_paths = getattr(package, "__path__", None)
            if package_paths is not None and package_path not in list(package_paths):
                try:
                    package_paths.append(package_path)
                except AttributeError:
                    package.__path__ = [*package_paths, package_path]
            break


def resolve_active_app_path(
    argv: list[str] | None = None,
    *,
    use_environment: bool = True,
    query_params: Any | None = None,
    query_param_keys: tuple[str, ...] = (),
    missing_message: str = "Missing --active-app argument.",
    not_found_message: str = "Provided --active-app path not found: {path}",
    error_fn: Callable[[str], Any] | None = None,
    missing_fn: Callable[[str], Any] | None = None,
    stop_fn: Callable[[], Any] | None = None,
    not_found_stop_fn: Callable[[], Any] | None = None,
) -> Path:
    """Resolve an active app from page CLI, environment, or query arguments."""

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--active-app", dest="active_app", type=str)
    args, _ = parser.parse_known_args(argv)
    active_app_value = args.active_app
    if not active_app_value and use_environment:
        active_app_value = os.environ.get("AGILAB_ACTIVE_APP")
    if not active_app_value and query_params is not None:
        for key in query_param_keys:
            value = query_params.get(key, "")
            if isinstance(value, (list, tuple)):
                value = value[0] if value else ""
            if value is not None and str(value).strip():
                active_app_value = str(value).strip()
                break
    if not active_app_value:
        reporter = missing_fn or error_fn
        if reporter is not None:
            reporter(missing_message)
        if stop_fn is not None:
            stop_fn()
        raise ValueError(missing_message)
    active_app_path = Path(active_app_value).expanduser().resolve()
    if active_app_path.exists():
        return active_app_path

    message = not_found_message.format(path=active_app_path)
    if error_fn is not None:
        error_fn(message)
    failure_stop_fn = not_found_stop_fn or stop_fn
    if failure_stop_fn is not None:
        failure_stop_fn()
    raise FileNotFoundError(message)


def analysis_return_url(app: str) -> str:
    """Return the standard ANALYSIS URL for an app-owned page."""

    return f"/ANALYSIS?{urlencode({'active_app': app})}"


def render_app_page_context(streamlit: Any, app: str, active_app: str | Path) -> None:
    """Render the shared active-app caption, return link, and path details."""

    columns = streamlit.columns(2)
    with columns[0]:
        streamlit.caption(f"`{app}`")
    with columns[1]:
        link_button = getattr(streamlit, "link_button", None)
        url = analysis_return_url(app)
        if callable(link_button):
            link_button("Back to ANALYSIS", url, type="secondary", width="content")
        else:
            streamlit.caption(f"Back to ANALYSIS: {url}")
    with streamlit.expander("Runtime context", expanded=False):
        streamlit.code(str(active_app), language="text")


def ensure_app_settings_loaded(
    session_state: Any,
    env: Any,
    *,
    key: str = "app_settings",
) -> Any:
    """Load mutable workspace app settings into session state once."""

    if key in session_state:
        return session_state[key]

    settings: dict[str, Any] = {}
    try:
        path = Path(env.app_settings_file)
    except (AttributeError, TypeError, ValueError):
        path = None
    if path is not None and path.exists():
        try:
            with path.open("rb") as handle:
                payload = tomllib.load(handle)
            if isinstance(payload, dict):
                settings = payload
        except (OSError, tomllib.TOMLDecodeError):
            pass
    session_state[key] = settings
    return settings


def active_app_scope_value(active_app: str | Path) -> str:
    """Return the stable session-scope key for an active app path."""

    return str(Path(active_app).expanduser().resolve())


def env_app_scope_value(env: Any) -> str | None:
    """Infer the active-app session-scope key from an AGILAB environment object."""

    app_path = getattr(env, "app_path", None)
    if app_path:
        return active_app_scope_value(app_path)
    active_app = getattr(env, "active_app", None)
    if active_app:
        return active_app_scope_value(active_app)
    apps_path = getattr(env, "apps_path", None)
    app = getattr(env, "app", None)
    if apps_path and app:
        return active_app_scope_value(Path(apps_path) / str(app))
    return None


def ensure_app_scoped_env(
    session_state: Any,
    active_app: str | Path,
    *,
    scope_key: str,
    env_factory: Callable[[Path], Any],
    env_key: str = "env",
    keys: tuple[str, ...] = (),
    prefixes: tuple[str, ...] = (),
) -> Any:
    """Return an environment aligned with the active app session scope.

    Page bundles share one Streamlit session while users switch projects.  A
    cached environment is reusable only when the recorded page scope and, when
    available, the environment's own app path both match the requested app.
    Unknown unscoped environments are rebuilt instead of being trusted.
    """

    active_app_path = Path(active_app).expanduser().resolve()
    active_scope = active_app_scope_value(active_app_path)
    cached_env = session_state.get(env_key)
    recorded_scope = session_state.get(scope_key)
    cached_scope = env_app_scope_value(cached_env) if cached_env is not None else None

    scope_matches = recorded_scope == active_scope
    env_matches = cached_env is not None and cached_scope in {None, active_scope}
    if scope_matches and env_matches:
        return cached_env

    # A warm environment can predate the page-specific scope marker.  Preserve
    # it only when its own app identity proves that it belongs to this app.
    if recorded_scope is None and cached_env is not None and cached_scope == active_scope:
        session_state[scope_key] = active_scope
        return cached_env

    reset_keys = tuple(dict.fromkeys((env_key, *keys)))
    reset_scoped_session_state(
        session_state,
        scope_key,
        active_app_path,
        keys=reset_keys,
        prefixes=prefixes,
    )
    env = env_factory(active_app_path)
    session_state[env_key] = env
    session_state[scope_key] = active_scope
    return env


def reset_scoped_session_state(
    session_state: Any,
    scope_key: str,
    scope_value: str | Path,
    *,
    keys: tuple[str, ...] = (),
    prefixes: tuple[str, ...] = (),
    clear_on_first_scope: bool = True,
    normalize_scope: bool = True,
) -> bool:
    """Clear page-owned session state when the active app scope changes."""

    normalized_scope = active_app_scope_value(scope_value) if normalize_scope else str(scope_value)
    previous_scope = session_state.get(scope_key)
    if previous_scope == normalized_scope:
        return False

    should_clear = clear_on_first_scope or previous_scope is not None
    if should_clear:
        exact_keys = set(keys)
        for key in list(session_state.keys()):
            if key == scope_key:
                continue
            key_text = str(key)
            if key in exact_keys or any(key_text.startswith(prefix) for prefix in prefixes):
                session_state.pop(key, None)

    session_state[scope_key] = normalized_scope
    return True


def artifact_root(env: Any, page_subdir: str) -> Path:
    """Return the conventional export root for one page bundle."""

    return Path(env.AGILAB_EXPORT_ABS) / env.target / page_subdir


def discover_files(base: Path, pattern: str) -> list[Path]:
    """Return matching files in deterministic order, swallowing invalid glob roots."""

    try:
        return sorted([path for path in base.glob(pattern) if path.is_file()], key=lambda path: path.as_posix())
    except (OSError, RuntimeError, TypeError, ValueError):
        return []


def load_json_object(path: Path | None) -> dict[str, Any]:
    """Read a JSON object from disk, returning an empty object for missing or non-object payloads."""

    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def relative_label(path: Path, artifact_root_path: Path) -> str:
    """Return a stable label relative to an artifact root when possible."""

    try:
        return str(path.relative_to(artifact_root_path))
    except (RuntimeError, TypeError, ValueError):
        return path.name


def safe_float(value: Any) -> float | None:
    """Coerce a value to float for page metrics."""

    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def safe_metric(value: Any, *, digits: int = 3) -> str:
    """Format a numeric page metric or return ``n/a``."""

    numeric = safe_float(value)
    if numeric is None:
        return "n/a"
    return f"{numeric:.{digits}f}"


def configure_streamlit_page(
    streamlit: Any,
    *,
    title: str,
    page_title: str | None = None,
    layout: str = "wide",
    initial_sidebar_state: str | None = None,
    menu_items: dict[str, str] | None = None,
) -> None:
    """Configure a Streamlit analysis page with consistent defaults."""

    config: dict[str, Any] = {
        "page_title": page_title or title,
        "layout": layout,
    }
    if initial_sidebar_state is not None:
        config["initial_sidebar_state"] = initial_sidebar_state
    if menu_items is not None:
        config["menu_items"] = menu_items
    try:
        from agilab.ui.page_bootstrap import configure_page_config
    except (ImportError, ModuleNotFoundError):
        getattr(streamlit, "set_page_config")(**config)
    else:
        configure_page_config(streamlit, **config)


def render_streamlit_page_header(
    streamlit: Any,
    *,
    title: str,
    logo_title: str | None = None,
    caption: str | None = None,
    show_logo: bool = True,
    show_title: bool = True,
    render_logo_fn: Callable[..., Any] | None = None,
) -> None:
    """Render the common AGILAB analysis-page logo, title, and optional caption."""

    if show_logo:
        if render_logo_fn is None:
            from agi_gui.pagelib import render_logo as _render_logo

            render_logo_fn = _render_logo
        if logo_title is None:
            render_logo_fn()
        else:
            render_logo_fn(logo_title)
    if show_title:
        streamlit.title(title)
    if caption:
        streamlit.caption(caption)
