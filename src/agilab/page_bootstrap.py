"""Shared bootstrap helpers for AGILAB Streamlit pages."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any, Callable


def _safe_resolved_path(value: Any) -> Path | None:
    try:
        return Path(value).expanduser().resolve(strict=False)
    except (TypeError, RuntimeError, ValueError, OSError):
        return None


def _page_apps_path(current_file: str | Path) -> Path | None:
    current_path = _safe_resolved_path(current_file)
    if current_path is None:
        return None
    try:
        apps_path = current_path.parents[1] / "apps"
    except IndexError:
        return None
    return apps_path if apps_path.exists() else None


def _is_agi_space_path(path: Path | None) -> bool:
    return path is not None and "agi-space" in path.parts


def _find_page_app(expected_apps_path: Path, requested_name: str) -> Path | None:
    name = Path(str(requested_name)).name
    if not name:
        return None
    variants = [name]
    if name.endswith("_project"):
        variants.append(name.removesuffix("_project"))
    else:
        variants.append(f"{name}_project")

    for variant in variants:
        for candidate in (
            expected_apps_path / variant,
            expected_apps_path / "builtin" / variant,
        ):
            if candidate.exists():
                return candidate
    return None


def _should_realign_session_env(
    *,
    env_apps_path: Path | None,
    env_active_app_path: Path | None,
    recorded_apps_path: Path | None,
    expected_apps_path: Path,
) -> bool:
    if env_apps_path == expected_apps_path:
        return _is_agi_space_path(env_active_app_path)
    if recorded_apps_path == expected_apps_path:
        return True
    return any(
        _is_agi_space_path(path)
        for path in (env_apps_path, env_active_app_path, recorded_apps_path)
    )


def session_env_ready(
    session_state: Any,
    *,
    env_key: str = "env",
    init_done_default: bool = True,
) -> bool:
    """Return whether the Streamlit session already has a usable AGILAB env."""
    if env_key not in session_state:
        return False
    return bool(getattr(session_state[env_key], "init_done", init_done_default))


def realign_session_env_with_page_root(
    session_state: Any,
    current_file: str | Path,
    *,
    env_key: str = "env",
) -> bool:
    """Repair a stale page session env that belongs to a different AGILAB launch root."""
    if env_key not in session_state:
        return False
    expected_apps_path = _page_apps_path(current_file)
    if expected_apps_path is None:
        return False

    env = session_state[env_key]
    env_apps_path = _safe_resolved_path(getattr(env, "apps_path", None))
    recorded_apps_path = _safe_resolved_path(session_state.get("apps_path"))
    env_active_app_path = _safe_resolved_path(getattr(env, "active_app", None))
    if not _should_realign_session_env(
        env_apps_path=env_apps_path,
        env_active_app_path=env_active_app_path,
        recorded_apps_path=recorded_apps_path,
        expected_apps_path=expected_apps_path,
    ):
        return False

    app_name = Path(str(getattr(env, "app", "") or "")).name
    if not app_name:
        app_name = env_active_app_path.name if env_active_app_path else ""
    page_app = _find_page_app(expected_apps_path, app_name)
    if page_app is None and env_active_app_path is not None:
        page_app = _find_page_app(expected_apps_path, env_active_app_path.name)
    if page_app is None:
        return False

    previous_init_done = getattr(env, "init_done", None)
    try:
        type(env).__init__(
            env,
            apps_path=expected_apps_path,
            app=page_app.name,
            verbose=getattr(env, "verbose", None),
        )
        if previous_init_done is not None:
            env.init_done = previous_init_done
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return False
    session_state["apps_path"] = str(expected_apps_path)
    return True


def load_about_page_module(
    current_file: str | Path,
    *,
    load_module: Callable[..., Any] | None = None,
) -> Any:
    """Load the main page module from the active checkout or packaged install."""
    current_path = Path(current_file).resolve()
    about_path = current_path.parents[1] / "main_page.py"
    if load_module is not None:
        return load_module(
            "agilab.main_page",
            current_file=current_file,
            fallback_path=about_path,
            fallback_name="agilab_about_fallback",
        )

    try:
        module = importlib.import_module("agilab.main_page")
        if hasattr(module, "main"):
            return module
    except (ImportError, ModuleNotFoundError):
        pass

    spec = importlib.util.spec_from_file_location("agilab_about_fallback", about_path)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"Unable to load main_page page module from {about_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "main"):
        raise ModuleNotFoundError("Unable to import main_page page module.")
    return module


def ensure_page_env(
    streamlit: Any,
    current_file: str | Path,
    *,
    init_done_default: bool = True,
    load_module: Callable[..., Any] | None = None,
) -> Any | None:
    """Ensure the page has a bootstrapped env, delegating cold starts to the main page."""
    if session_env_ready(
        streamlit.session_state,
        init_done_default=init_done_default,
    ):
        realign_session_env_with_page_root(streamlit.session_state, current_file)
        return streamlit.session_state["env"]

    about_page = load_about_page_module(current_file, load_module=load_module)
    about_page.main()
    streamlit.rerun()
    return None
