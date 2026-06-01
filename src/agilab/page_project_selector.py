"""Page-local project selector helpers for AGILAB Streamlit pages."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Iterable

NAVIGATION_PAGE_ROUTES_ATTR = "_NAVIGATION_PAGE_ROUTES"
PROJECT_ROUTE_ID = "project"
PROJECT_PAGE_PATH = Path("pages/1_PROJECT.py")
MAIN_NAVIGATION_MODULES = ("__main__", "agilab.main_page")


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

    try:
        refreshed = env.get_projects(env.apps_path, env.builtin_apps_path)
        env.projects = refreshed
        return _unique_project_names(refreshed)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return _unique_project_names(projects)


def _registered_navigation_page(route_id: str) -> Any | None:
    """Return a registered ``st.Page`` object from the active main navigation run."""
    for module_name in MAIN_NAVIGATION_MODULES:
        module = sys.modules.get(module_name)
        routes = getattr(module, NAVIGATION_PAGE_ROUTES_ATTR, None)
        if isinstance(routes, dict) and routes.get(route_id) is not None:
            return routes[route_id]
    return None


def switch_to_project_page(streamlit: Any, *, active_app: str | None = None) -> bool:
    """Switch to PROJECT using the active ``st.navigation`` page when available."""
    switch_page = getattr(streamlit, "switch_page", None)
    if not callable(switch_page):
        return False
    if active_app is not None:
        streamlit.query_params["active_app"] = str(active_app)
    switch_page(_registered_navigation_page(PROJECT_ROUTE_ID) or PROJECT_PAGE_PATH)
    return True


def render_project_selector(
    streamlit: Any,
    projects: Iterable[Any],
    current_project: str | None,
    *,
    on_change: Callable[[str], None],
    key: str = "project_selectbox",
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

    if streamlit.session_state.get(key) not in project_names:
        streamlit.session_state.pop(key, None)

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
        label_visibility="collapsed",
    )
    if show_edit_button:
        if edit_host.button(edit_label, key=f"{key}__edit", help=f"Edit {selection}.", width="stretch"):
            switch_to_project_page(streamlit, active_app=selection)
    if selection != current:
        on_change(selection)
    return selection
