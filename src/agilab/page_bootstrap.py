"""Shared bootstrap helpers for AGILAB Streamlit pages."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any, Callable

PAGE_ENV_REALIGNED_STATE_KEY = "_agilab_page_env_realigned"


def _default_page_title(page_label: str) -> str:
    clean_label = str(page_label or "").strip()
    if not clean_label:
        return "AGILab"
    return f"AGILab {clean_label}"


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
        for_app = getattr(type(env), "for_app", None)
        if callable(for_app):
            env = for_app(
                apps_path=expected_apps_path,
                app=page_app.name,
                verbose=getattr(env, "verbose", None),
            )
            session_state[env_key] = env
        else:
            init_kwargs = {
                "apps_path": expected_apps_path,
                "app": page_app.name,
                "verbose": getattr(env, "verbose", None),
            }
            try:
                type(env).__init__(
                    env,
                    **init_kwargs,
                    _agilab_reinitialize=True,
                )
            except TypeError:
                type(env).__init__(env, **init_kwargs)
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
        if realign_session_env_with_page_root(streamlit.session_state, current_file):
            streamlit.session_state[PAGE_ENV_REALIGNED_STATE_KEY] = True
        else:
            streamlit.session_state.pop(PAGE_ENV_REALIGNED_STATE_KEY, None)
        return streamlit.session_state["env"]

    about_page = load_about_page_module(current_file, load_module=load_module)
    about_page.main()
    streamlit.rerun()
    return None


def configure_page_chrome(
    streamlit: Any,
    *,
    page_label: str,
    docs_html_file: str,
    resources_path: str | Path | None = None,
    layout: str = "wide",
    page_title: str | None = None,
    get_docs_menu_items: Callable[..., dict[str, str]] | None = None,
    inject_theme: Callable[[Any], Any] | None = None,
) -> None:
    """Apply the common AGILAB Streamlit page configuration and theme."""
    if get_docs_menu_items is None:
        from agilab.page_docs import get_docs_menu_items as _get_docs_menu_items

        get_docs_menu_items = _get_docs_menu_items
    if inject_theme is None:
        from agi_gui.pagelib import inject_theme as _inject_theme

        inject_theme = _inject_theme

    streamlit.set_page_config(
        page_title=page_title or _default_page_title(page_label),
        layout=layout,
        menu_items=get_docs_menu_items(html_file=docs_html_file),
    )
    if resources_path is not None:
        inject_theme(resources_path)


def _active_project_label(env: Any | None) -> str:
    """Return the display label for the currently selected project."""
    if env is None:
        return ""
    for attr_name in ("app", "target", "active_app"):
        value = getattr(env, attr_name, None)
        text = str(value or "").strip()
        if not text:
            continue
        label = Path(text).name
        if label.endswith("_project"):
            label = label[: -len("_project")]
        return label.replace("_", " ").title().replace("Pytorch", "PyTorch")
    return ""


def render_active_project_chip(streamlit: Any, *, env: Any | None = None) -> bool:
    """Render a compact selected-project label using the historical page-chrome path."""
    project_label = _active_project_label(env)
    if not project_label:
        return False
    sidebar = getattr(streamlit, "sidebar", None)
    markdown = getattr(sidebar, "markdown", None)
    if not callable(markdown):
        return False
    markdown(f"**{project_label}**")
    return True


def render_page_header(
    streamlit: Any,
    *,
    page_label: str,
    env: Any | None = None,
    show_project_context: bool = False,
    render_logo: Callable[[], Any] | None = None,
    render_pinned_expanders: Callable[[Any], Any] | None = None,
    render_page_context: Callable[..., Any] | None = None,
) -> None:
    """Render the shared AGILAB sidebar/header affordances for first-party pages."""
    if render_logo is None:
        from agi_gui.pagelib import render_logo as _render_logo

        render_logo = _render_logo
    if render_pinned_expanders is None:
        from agilab.pinned_expander import (
            render_pinned_expanders as _render_pinned_expanders,
        )

        render_pinned_expanders = _render_pinned_expanders
    if show_project_context and render_page_context is None:
        from agilab.workflow_ui import render_page_context as _render_page_context

        render_page_context = _render_page_context

    render_logo()
    render_pinned_expanders(streamlit)
    render_active_project_chip(streamlit, env=env)
    if show_project_context and render_page_context is not None:
        render_page_context(streamlit, page_label=page_label, env=env)


def render_page_chrome(
    streamlit: Any,
    *,
    env: Any,
    page_label: str,
    docs_html_file: str,
    resources_path: str | Path | None = None,
    layout: str = "wide",
    page_title: str | None = None,
    show_project_context: bool = False,
    get_docs_menu_items: Callable[..., dict[str, str]] | None = None,
    inject_theme: Callable[[Any], Any] | None = None,
    render_logo: Callable[[], Any] | None = None,
    render_pinned_expanders: Callable[[Any], Any] | None = None,
    render_page_context: Callable[..., Any] | None = None,
) -> None:
    """Configure and render common AGILAB Streamlit page chrome."""
    resolved_resources_path = resources_path
    if resolved_resources_path is None:
        resolved_resources_path = getattr(env, "st_resources", None)
    configure_page_chrome(
        streamlit,
        page_label=page_label,
        docs_html_file=docs_html_file,
        resources_path=resolved_resources_path,
        layout=layout,
        page_title=page_title,
        get_docs_menu_items=get_docs_menu_items,
        inject_theme=inject_theme,
    )
    render_page_header(
        streamlit,
        page_label=page_label,
        env=env,
        show_project_context=show_project_context,
        render_logo=render_logo,
        render_pinned_expanders=render_pinned_expanders,
        render_page_context=render_page_context,
    )
