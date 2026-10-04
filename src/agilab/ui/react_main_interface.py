"""Main React interface backed by the existing Streamlit routes and AgiEnv."""

from pathlib import Path
from typing import Any, Mapping

from agilab.ui.page_project_selector import _refresh_project_names


SHELL_ACTIVE_KEY = "_agilab_react_shell_active"
NAVIGATION_ROUTES_SESSION_KEY = "_agilab_navigation_page_routes"

# IDs resolve to Page objects registered by main_page; never to client paths.
_ROUTE_CONTENT = {
    "home": ("HOME", True, ""),
    "project": ("PROJECT", True, "Inspect project status, data and execution evidence."),
    "orchestrate": ("ORCHESTRATE", True, "Configure and launch your project execution."),
    "workflow": ("WORKFLOW", True, "Edit and run your project's pipeline."),
    "analysis": ("ANALYSIS", True, "Explore results, maps and curves. Export an app to a notebook."),
    "agent_demo": ("AGENT DEMO", True, ""),
    "project_editor": ("PROJECT EDITOR", False, ""),
    "settings": ("SETTINGS", False, ""),
}


def interface_data(streamlit: Any, env: Any, routes: Mapping[str, Any], page: Any, *, version: str = "") -> dict[str, Any]:
    """Use canonical server state on every rerun, including URL-driven changes."""
    project = str(getattr(env, "app", "") or "")
    projects = _refresh_project_names(streamlit, getattr(env, "projects", ()) or ())
    if project and project not in projects:
        projects = sorted([*projects, project], key=lambda name: (name.casefold(), name))
    route = next((key for key in _ROUTE_CONTENT if routes.get(key) is page), "home")
    return {
        "brand": "AGILAB",
        "welcome_title": "Run a project, explore its results",
        "project": project,
        "projects": projects,
        "route": route,
        "has_child_surface": bool(
            streamlit.query_params.get("current_notebook")
            or streamlit.query_params.get("current_page") not in (None, "", "main")
        ),
        "version": version,
        "routes": [
            {"id": key, "label": label, "primary": primary, "description": description}
            for key, (label, primary, description) in _ROUTE_CONTENT.items()
            if key in routes
        ],
    }


def handle_interface_action(
    action: Any, *, data: Mapping[str, Any], routes: Mapping[str, Any],
    navigate: Any, select_project: Any,
) -> bool:
    """Reject stale or forged actions before invoking existing Python lifecycle."""
    if not isinstance(action, dict) or action.get("project") != data["project"] or action.get("route") != data["route"]:
        return False
    kind, value = action.get("kind"), action.get("value")
    if not isinstance(value, str):
        return False
    if kind == "navigate" and value in _ROUTE_CONTENT and value in routes:
        if value == data["route"] and not data.get("has_child_surface"):
            return False
        navigate(routes[value])
        return True
    if kind == "project" and value in data["projects"] and value != data["project"]:
        select_project(value)
        return True
    return False


def select_interface_project(streamlit: Any, env: Any, project: str) -> None:
    """Request the established cold switch; clear inputs once bootstrap succeeds."""
    from agilab.about_page.bootstrap import resolve_active_app_query_target, sync_active_app_from_query

    target = resolve_active_app_query_target(env, project)
    if target is None:
        streamlit.warning(f"Project '{project}' is no longer available. Refresh the project list.")
        return
    streamlit.query_params["active_app"] = str(target)
    sync_active_app_from_query(env, streamlit=streamlit)


def sync_interface_project_state(streamlit: Any, env: Any) -> None:
    """Clear native widget inputs in the run that renders the new environment.

    Popping keys just before st.rerun() lets the browser's old widget values
    return with the next request. Do this after bootstrap and before mounting
    any page widgets, including switches initiated by a deep link or Python.
    """
    from agi_env.ui.pagelib_session_support import clear_project_session_state, reset_project_sections
    from agilab.about_page.bootstrap import active_app_store_path

    key = "_agilab_react_project_path"
    current_path = str(active_app_store_path(env))
    previous_path = streamlit.session_state.get(key)
    if previous_path is not None and previous_path != current_path:
        clear_project_session_state(streamlit.session_state)
        reset_project_sections(streamlit.session_state)
        # Keep the derived sidebar/export fields used by the legacy project
        # callback. Calling that callback here would change_app a second time
        # after the authorized cold bootstrap has already selected this env.
        module = Path(env.target)
        datadir = env.AGILAB_EXPORT_ABS / module
        streamlit.session_state["module_rel"] = module
        streamlit.session_state["datadir"] = datadir
        streamlit.session_state["datadir_str"] = str(datadir)
        streamlit.session_state["df_export_file"] = str(datadir / "export.csv")
        streamlit.session_state["switch_to_select"] = False
        streamlit.session_state["project_changed"] = True
    streamlit.session_state[key] = current_path


def render_interface(streamlit: Any, env: Any, routes: Mapping[str, Any], page: Any, *, version: str = "", select_project: Any) -> None:
    from agi_web.react_main_interface import render_main_interface
    from agilab.about_page.bootstrap import active_app_store_path

    sync_interface_project_state(streamlit, env)
    data = interface_data(streamlit, env, routes, page, version=version)
    result = render_main_interface(streamlit, data)
    streamlit.session_state[SHELL_ACTIVE_KEY] = True
    handle_interface_action(
        getattr(result, "action", None), data=data, routes=routes,
        navigate=lambda target: streamlit.switch_page(target, query_params={"active_app": str(active_app_store_path(env))}),
        select_project=select_project,
    )
