"""Page-local project selector helpers for AGILAB Streamlit pages."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable


def _unique_project_names(projects: Iterable[Any]) -> list[str]:
    """Return project names once, preserving source order."""
    seen: set[str] = set()
    names: list[str] = []
    for raw_project in projects:
        project = str(raw_project or "").strip()
        if not project or project in seen:
            continue
        seen.add(project)
        names.append(project)
    return names


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
) -> str | None:
    """Render the project selector without an extra filter text field."""
    project_names = _refresh_project_names(streamlit, projects)
    current = str(current_project or "").strip()
    if current and current not in project_names:
        project_names.insert(0, current)

    streamlit.session_state.pop("project_filter", None)
    if not project_names:
        streamlit.sidebar.info("No projects available.")
        return None

    if streamlit.session_state.get(key) not in project_names:
        streamlit.session_state.pop(key, None)

    default_index = project_names.index(current) if current in project_names else 0
    selector_host = streamlit.sidebar
    edit_host = streamlit.sidebar
    if show_edit_button:
        selector_host, edit_host = streamlit.sidebar.columns([0.76, 0.24], vertical_alignment="bottom")

    selection = selector_host.selectbox(
        label,
        project_names,
        index=default_index,
        key=key,
        help=help_text,
    )
    if show_edit_button:
        if edit_host.button(edit_label, key=f"{key}__edit", help=f"Edit {selection}.", use_container_width=True):
            streamlit.query_params["active_app"] = selection
            streamlit.switch_page(Path("pages/1_PROJECT.py"))
    if selection != current:
        on_change(selection)
    return selection
