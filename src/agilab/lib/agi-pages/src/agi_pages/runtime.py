"""Shared runtime helpers for AGILAB analysis page bundles."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable


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
            break


def resolve_active_app_path(
    argv: list[str] | None = None,
    *,
    error_fn: Callable[[str], Any] | None = None,
    stop_fn: Callable[[], Any] | None = None,
) -> Path:
    """Resolve ``--active-app`` from page CLI arguments."""

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--active-app", dest="active_app", type=str)
    args, _ = parser.parse_known_args(argv)
    active_app_value = args.active_app or os.environ.get("AGILAB_ACTIVE_APP")
    if not active_app_value:
        message = "Missing --active-app argument."
        if error_fn is not None:
            error_fn(message)
        if stop_fn is not None:
            stop_fn()
        raise ValueError(message)
    active_app_path = Path(active_app_value).expanduser().resolve()
    if active_app_path.exists():
        return active_app_path

    message = f"Provided --active-app path not found: {active_app_path}"
    if error_fn is not None:
        error_fn(message)
    if stop_fn is not None:
        stop_fn()
    raise FileNotFoundError(message)


def active_app_scope_value(active_app: str | Path) -> str:
    """Return the stable session-scope key for an active app path."""

    return str(Path(active_app).expanduser().resolve())


def _env_concrete_app_scope_value(env: Any) -> str | None:
    """Return the established primary live app identity for an environment."""

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


def _env_matches_active_app_scope(env: Any, active_scope: str) -> bool:
    """Return whether live environment fields prove the requested app scope.

    ``AgiEnv`` can intentionally resolve an app to its bundled implementation
    under its configured ``builtin_apps_path`` (or the legacy
    ``apps_path / 'builtin'`` location). Those are the sole accepted
    alternatives to the requested ``apps_path / app`` location. Conflicting
    live fields are not interchangeable: a stale marker or an ``apps_path`` /
    ``app`` pair cannot override a different concrete ``active_app``.
    """

    app_path = getattr(env, "app_path", None)
    if app_path:
        return active_app_scope_value(app_path) == active_scope

    active_app = getattr(env, "active_app", None)
    if active_app:
        env_active_scope = active_app_scope_value(active_app)
        if env_active_scope == active_scope:
            return True
        apps_path = getattr(env, "apps_path", None)
        app = getattr(env, "app", None)
        if not apps_path or not app:
            return False
        requested_scope = active_app_scope_value(Path(apps_path) / str(app))
        builtin_roots = [getattr(env, "builtin_apps_path", None)]
        builtin_roots.append(Path(apps_path) / "builtin")
        builtin_scopes = {
            active_app_scope_value(Path(root) / str(app))
            for root in builtin_roots
            if root
        }
        return active_scope == requested_scope and env_active_scope in builtin_scopes

    apps_path = getattr(env, "apps_path", None)
    app = getattr(env, "app", None)
    return (
        bool(apps_path and app)
        and active_app_scope_value(Path(apps_path) / str(app)) == active_scope
    )


def env_app_scope_value(env: Any) -> str | None:
    """Infer the active-app session-scope key from an AGILAB environment object."""

    concrete_scope = _env_concrete_app_scope_value(env)
    if concrete_scope is not None:
        return concrete_scope
    bound_scope = getattr(env, "_agilab_active_app_scope", None)
    if bound_scope:
        return active_app_scope_value(bound_scope)
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
    """Return an environment whose app identity matches the active page scope.

    Streamlit pages share one session-state mapping. A page-local scope marker
    therefore cannot prove that the shared cached environment still belongs to
    the same app: another page may have replaced it since the marker was set.
    Reuse is allowed only when the environment exposes a matching app identity.
    Page-owned state is cleared whenever its recorded scope changes or an
    unscoped/stale environment must be replaced.
    """

    active_app_path = Path(active_app).expanduser().resolve()
    active_scope = active_app_scope_value(active_app_path)
    cached_env = session_state.get(env_key)
    cached_matches = cached_env is not None and _env_matches_active_app_scope(
        cached_env,
        active_scope,
    )

    if cached_env is not None and cached_matches:
        try:
            cached_env._agilab_active_app_scope = active_scope
        except (AttributeError, TypeError):
            pass
        reset_scoped_session_state(
            session_state,
            scope_key,
            active_app_path,
            keys=keys,
            prefixes=prefixes,
        )
        session_state[env_key] = cached_env
        return cached_env

    replacement = env_factory(active_app_path)
    replacement_scope = env_app_scope_value(replacement)
    if not _env_matches_active_app_scope(replacement, active_scope):
        raise ValueError(
            "Environment factory returned an app scope that does not match "
            f"the requested app: expected {active_scope!r}, got {replacement_scope!r}"
        )
    try:
        replacement._agilab_active_app_scope = active_scope
    except (AttributeError, TypeError):
        pass
    exact_keys = set((env_key, *keys))
    for key in list(session_state.keys()):
        if key == scope_key:
            continue
        key_text = str(key)
        if key in exact_keys or any(key_text.startswith(prefix) for prefix in prefixes):
            session_state.pop(key, None)
    session_state[scope_key] = active_scope
    session_state[env_key] = replacement
    return replacement


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

    normalized_scope = (
        active_app_scope_value(scope_value) if normalize_scope else str(scope_value)
    )
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
            if key in exact_keys or any(
                key_text.startswith(prefix) for prefix in prefixes
            ):
                session_state.pop(key, None)

    session_state[scope_key] = normalized_scope
    return True


def artifact_root(env: Any, page_subdir: str) -> Path:
    """Return the conventional export root for one page bundle."""

    return Path(env.AGILAB_EXPORT_ABS) / env.target / page_subdir


def discover_files(base: Path, pattern: str) -> list[Path]:
    """Return matching files in deterministic order, swallowing invalid glob roots."""

    try:
        return sorted(
            [path for path in base.glob(pattern) if path.is_file()],
            key=lambda path: path.as_posix(),
        )
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


def _page_title_from_header(title: str) -> str:
    """Derive a clean browser-tab title from a visible page header."""

    text = str(title or "").strip()
    if not text:
        return "AGILab"
    cleaned = re.sub(r"^:[^:]+:\s*", "", text).strip()
    return cleaned or text


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

    configure_streamlit_page(
        streamlit,
        title=_page_title_from_header(title),
        layout="wide",
    )
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
