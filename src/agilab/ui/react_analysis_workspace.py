"""React analysis controls backed by the existing page selection and routing."""

from hashlib import sha256
import json
from typing import Any, Mapping

from agilab.about_page.bootstrap import active_app_store_path
from agilab.ui.react_main_interface import NAVIGATION_ROUTES_SESSION_KEY, SHELL_ACTIVE_KEY


def analysis_workspace_data(
    env: Any, *, overview: Mapping[str, Any], view_options: Mapping[str, str],
    view_routes: Mapping[str, Mapping[str, str]], notebook_routes: Mapping[str, Mapping[str, str]],
    selected_views: list[str], selected_notebooks: list[str], export_available: bool,
    pending_selection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep the server's discovered choices and saved selections authoritative."""
    data = {
        "view": "analysis_workspace", "route": "analysis",
        "project": str(getattr(env, "app", "") or ""),
        "project_path": str(active_app_store_path(env)),
        "overview": dict(overview),
        "views": [{"id": key, "label": label, "available": key in view_routes}
                  for key, label in view_options.items()],
        "notebooks": [{"id": key, "label": key, "available": True} for key in notebook_routes],
        "selected_views": list(selected_views), "selected_notebooks": list(selected_notebooks),
        "export_available": export_available,
    }
    pending = pending_selection or {}
    valid_draft = (_valid_selection(pending.get("views"), set(view_options))
                   and _valid_selection(pending.get("notebooks"), set(notebook_routes)))
    data.update(
        draft_views=pending["views"] if valid_draft else list(selected_views),
        draft_notebooks=pending["notebooks"] if valid_draft else list(selected_notebooks),
        save_error=str(pending.get("error", "")) if valid_draft else "",
    )
    # Reject queued actions from an older project, selection or discovery result.
    context = {key: value for key, value in data.items() if key != "overview"}
    context.update(view_routes=view_routes, notebook_routes=notebook_routes)
    data["context"] = sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    return data


def _valid_selection(value: Any, options: set[str]) -> bool:
    return (isinstance(value, list) and all(isinstance(item, str) for item in value)
            and len(value) == len(set(value)) and set(value).issubset(options))


def handle_analysis_action(
    action: Any, *, data: Mapping[str, Any], view_routes: Mapping[str, Mapping[str, str]],
    notebook_routes: Mapping[str, Mapping[str, str]], routes: Mapping[str, Any], navigate: Any,
) -> dict[str, Any]:
    """Return validated selection edits, or dispatch a saved server-side route."""
    if not isinstance(action, dict) or any(
        action.get(key) != data[key] for key in ("project", "project_path", "route", "context")
    ):
        return {}
    kind = action.get("kind")
    if kind == "discard":
        return {"discard": True}
    if kind == "select":
        views, notebooks = action.get("views"), action.get("notebooks")
        if not _valid_selection(views, {item["id"] for item in data["views"]}):
            return {}
        if not _valid_selection(notebooks, {item["id"] for item in data["notebooks"]}):
            return {}
        if views != data["selected_views"] or notebooks != data["selected_notebooks"]:
            return {"views": views, "notebooks": notebooks}
    elif kind == "export_notebook" and data["export_available"] and "workflow" in routes:
        navigate(routes["workflow"], {"active_app": data["project_path"]})
    elif kind in ("open_view", "open_notebook") and "analysis" in routes:
        value = action.get("value")
        saved = data["selected_views"] if kind == "open_view" else data["selected_notebooks"]
        targets = view_routes if kind == "open_view" else notebook_routes
        if isinstance(value, str) and value in saved and value in targets:
            navigate(routes["analysis"], {**targets[value], "active_app": data["project_path"]})
    return {}


def render_analysis_workspace(
    streamlit: Any, env: Any, *, overview: Mapping[str, Any], view_options: Mapping[str, str],
    view_routes: Mapping[str, Mapping[str, str]], notebook_routes: Mapping[str, Mapping[str, str]],
    selected_views: list[str], selected_notebooks: list[str],
    pending_selection: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Mount only in the main React host; standalone Python pages stay native."""
    routes = streamlit.session_state.get(NAVIGATION_ROUTES_SESSION_KEY)
    if not streamlit.session_state.get(SHELL_ACTIVE_KEY) or not isinstance(routes, dict) or "analysis" not in routes:
        return None
    from agi_web.react_main_interface import render_main_interface

    data = analysis_workspace_data(
        env, overview=overview, view_options=view_options, view_routes=view_routes,
        notebook_routes=notebook_routes, selected_views=selected_views,
        selected_notebooks=selected_notebooks, export_available="workflow" in routes,
        pending_selection=pending_selection,
    )
    result = render_main_interface(streamlit, data, key="agilab:analysis-workspace")
    return handle_analysis_action(
        getattr(result, "action", None), data=data, view_routes=view_routes,
        notebook_routes=notebook_routes, routes=routes,
        navigate=lambda target, params: streamlit.switch_page(target, query_params=params),
    )
