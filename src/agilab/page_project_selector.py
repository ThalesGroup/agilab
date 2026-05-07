"""Page-local project selector helpers for AGILAB Streamlit pages."""

from __future__ import annotations

import html
from typing import Any, Callable, Iterable
from urllib.parse import urlencode


def _project_edit_link_markup(project: str, label: str) -> str:
    """Return a same-tab PROJECT link styled as a compact button."""
    query = urlencode({"active_app": project})
    href = f"PROJECT?{query}"
    return (
        '<a class="agilab-project-edit-link" '
        f'href="{html.escape(href, quote=True)}" target="_self">'
        f"{html.escape(label)}</a>"
        "<style>"
        ".agilab-project-edit-link{"
        "display:block;text-align:center;text-decoration:none;"
        "border:1px solid rgba(49,51,63,.25);border-radius:.5rem;"
        "padding:.45rem .75rem;margin:-.2rem 0 .75rem 0;"
        "font-weight:600;color:inherit;background:rgba(255,255,255,.04);"
        "}"
        ".agilab-project-edit-link:hover{"
        "border-color:rgba(49,51,63,.45);background:rgba(49,51,63,.06);"
        "}"
        "</style>"
    )


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
    label: str = "Project name",
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
    selection = streamlit.sidebar.selectbox(
        label,
        project_names,
        index=default_index,
        key=key,
        help=help_text,
    )
    if show_edit_button:
        streamlit.sidebar.markdown(
            _project_edit_link_markup(selection, edit_label),
            unsafe_allow_html=True,
        )
    if selection != current:
        on_change(selection)
    return selection
