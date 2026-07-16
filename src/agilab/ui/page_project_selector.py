"""Page-local project selector helpers for AGILAB Streamlit pages."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable, Iterable

from agilab.ui.ui_performance import path_stat_signature, ui_discovery_cache_enabled

NAVIGATION_PAGE_ROUTES_ATTR = "_NAVIGATION_PAGE_ROUTES"
NAVIGATION_PAGE_ROUTES_SESSION_KEY = "_agilab_navigation_page_routes"
PROJECT_EDITOR_ROUTE_ID = "project_editor"
PROJECT_EDITOR_PAGE_PATH = Path("pages/1_PROJECT.py")
PROJECT_ROUTE_ID = PROJECT_EDITOR_ROUTE_ID
PROJECT_PAGE_PATH = PROJECT_EDITOR_PAGE_PATH
MAIN_NAVIGATION_MODULES = ("__main__", "agilab.main_page")
PROJECT_SELECTBOX_KEY = "project:selectbox"
PROJECT_NAMES_CACHE_KEY = "_agilab_project_names_cache"


def _safe_resolved_path(value: Any) -> Path | None:
    try:
        return Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _path_cache_signature(value: Any, *, label: str) -> tuple[str, tuple[str, bool, int, int] | None] | None:
    path = _safe_resolved_path(value)
    if path is None:
        return None
    return (path.as_posix(), path_stat_signature(path, label=label))


def _project_cache_signature(env: Any) -> tuple[Any, ...]:
    installed_paths = getattr(env, "installed_app_project_paths", ()) or ()
    return (
        _path_cache_signature(getattr(env, "apps_path", None), label="apps"),
        _path_cache_signature(getattr(env, "builtin_apps_path", None), label="builtin"),
        tuple(
            _path_cache_signature(path, label=f"installed:{index}")
            for index, path in enumerate(installed_paths)
        ),
    )


def _cached_project_names(streamlit: Any, signature: tuple[Any, ...]) -> list[str] | None:
    cache = streamlit.session_state.get(PROJECT_NAMES_CACHE_KEY)
    if not isinstance(cache, dict) or cache.get("signature") != signature:
        return None
    cached_projects = cache.get("projects")
    if not isinstance(cached_projects, list):
        return None
    return _unique_project_names(cached_projects)


def _store_project_names_cache(streamlit: Any, signature: tuple[Any, ...], projects: Iterable[Any]) -> list[str]:
    names = _unique_project_names(projects)
    streamlit.session_state[PROJECT_NAMES_CACHE_KEY] = {
        "signature": signature,
        "projects": names,
    }
    return names


def _unique_project_names(projects: Iterable[Any]) -> list[str]:
    """Return project names once, sorted for deterministic selectbox display."""
    seen: set[str] = set()
    names: list[str] = []
    for raw_project in projects:
        project = str(raw_project or "").strip()
        if not project or project in seen:
            continue
        seen.add(project)
        names.append(project)
    return sorted(names, key=lambda name: (name.casefold(), name))


def _refresh_project_names(streamlit: Any, projects: Iterable[Any]) -> list[str]:
    """Refresh project names from the active environment when available."""
    env = streamlit.session_state.get("env")
    if env is None:
        return _unique_project_names(projects)

    cache_enabled = ui_discovery_cache_enabled()
    signature = _project_cache_signature(env) if cache_enabled else ()
    if cache_enabled:
        cached_names = _cached_project_names(streamlit, signature)
        if cached_names is not None:
            env.projects = cached_names
            return cached_names

    try:
        refreshed = env.get_projects(env.apps_path, env.builtin_apps_path)
        env.projects = refreshed
        if cache_enabled:
            return _store_project_names_cache(streamlit, signature, refreshed)
        streamlit.session_state.pop(PROJECT_NAMES_CACHE_KEY, None)
        return _unique_project_names(refreshed)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        streamlit.session_state.pop(PROJECT_NAMES_CACHE_KEY, None)
        return _unique_project_names(projects)


def _registered_navigation_page(route_id: str, streamlit: Any | None = None) -> Any | None:
    """Return a registered ``st.Page`` object from the active main navigation run."""
    session_state = getattr(streamlit, "session_state", None)
    if session_state is not None:
        try:
            session_routes = session_state.get(NAVIGATION_PAGE_ROUTES_SESSION_KEY)
        except (AttributeError, RuntimeError, TypeError):
            session_routes = None
        if isinstance(session_routes, Mapping) and session_routes.get(route_id) is not None:
            return session_routes[route_id]
    for module_name in MAIN_NAVIGATION_MODULES:
        module = sys.modules.get(module_name)
        routes = getattr(module, NAVIGATION_PAGE_ROUTES_ATTR, None)
        if isinstance(routes, Mapping) and routes.get(route_id) is not None:
            return routes[route_id]
    return None


def switch_to_project_page(streamlit: Any, *, active_app: str | None = None) -> bool:
    """Switch to PROJECT_EDITOR using the registered ``st.navigation`` page only."""
    switch_page = getattr(streamlit, "switch_page", None)
    project_page = _registered_navigation_page(PROJECT_ROUTE_ID, streamlit)
    if not callable(switch_page) or project_page is None:
        return False
    if active_app is not None:
        streamlit.query_params["active_app"] = str(active_app)
    switch_page(project_page)
    return True


def render_project_selector(
    streamlit: Any,
    projects: Iterable[Any],
    current_project: str | None,
    *,
    on_change: Callable[[str], None],
    key: str = PROJECT_SELECTBOX_KEY,
    label: str = "Project",
    help_text: str = "Project workspace used by this page. Type in the dropdown to search.",
    show_edit_button: bool = True,
    edit_label: str = "Edit",
    container: Any | None = None,
) -> str | None:
    """Render the project selector without an extra filter text field."""
    project_names = _refresh_project_names(streamlit, projects)
    current = str(current_project or "").strip()
    if current and current not in project_names:
        project_names = sorted([*project_names, current], key=lambda name: (name.casefold(), name))

    streamlit.session_state.pop("project_filter", None)
    target = container if container is not None else streamlit.sidebar
    if not project_names:
        target.info("No projects available.")
        return None

    selected_project = streamlit.session_state.get(key)
    if selected_project not in project_names or (
        current in project_names and selected_project != current
    ):
        # Drop stale widget state before render. The selectbox index below
        # supplies the current project without also assigning this widget key
        # through Session State, which Streamlit warns about.
        streamlit.session_state.pop(key, None)

    def _emit_change() -> None:
        chosen = streamlit.session_state.get(key)
        if chosen and chosen != current:
            on_change(chosen)

    default_index = project_names.index(current) if current in project_names else 0
    selector_host = target
    edit_host = target
    if show_edit_button:
        selector_host, edit_host = target.columns([0.76, 0.24], vertical_alignment="bottom")

    selection = selector_host.selectbox(
        label,
        project_names,
        index=default_index,
        key=key,
        help=help_text,
        on_change=_emit_change,
        label_visibility="collapsed",
    )
    if show_edit_button:
        project_page_available = _registered_navigation_page(PROJECT_ROUTE_ID) is not None
        if edit_host.button(
            edit_label,
            key=f"{key}__edit",
            help=f"Edit {selection}.",
            width="stretch",
            disabled=not project_page_available,
        ):
            switch_to_project_page(streamlit, active_app=selection)
    return selection
