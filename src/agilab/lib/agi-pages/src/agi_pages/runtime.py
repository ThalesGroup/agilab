"""Shared runtime helpers for AGILAB analysis page bundles."""

from __future__ import annotations

import argparse
import json
import math
import os
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
) -> None:
    """Configure a Streamlit analysis page with consistent defaults."""

    config: dict[str, Any] = {
        "page_title": page_title or title,
        "layout": layout,
    }
    if initial_sidebar_state is not None:
        config["initial_sidebar_state"] = initial_sidebar_state
    streamlit.set_page_config(**config)


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
