"""React PROJECT overview backed by the existing Python health diagnostics."""

from typing import Any, Mapping

from agilab.about_page.bootstrap import active_app_store_path
from agilab.environment.environment_health import build_environment_health, header_value_state
from agilab.ui.react_main_interface import (
    NAVIGATION_ROUTES_SESSION_KEY,
    SHELL_ACTIVE_KEY,
    handle_interface_action,
)


_WORKSPACE_ACTIONS = (
    ("orchestrate", "Run project", "Configure and launch an execution."),
    ("analysis", "Analysis and notebook export", "Explore results and export an app to Jupyter."),
    ("workflow", "Open pipeline", "Review and edit the project workflow."),
    ("project_editor", "Edit project files", "Edit documentation, configuration and code."),
)


def _card_data(card: Any) -> dict[str, str]:
    """Keep diagnostic state while distinguishing ordinary onboarding status."""
    value = str(card.value)
    state = header_value_state(value, card.caption, explicit=card.state)
    display_state = state
    status_label = "Needs attention" if state == "incomplete" else "Ready"
    if card.label == "API keys" and value == "Optional":
        display_state, status_label = "neutral", "Optional"
    elif card.label == "Runs" and value == "0" and card.caption == "no run logs yet":
        display_state, status_label = "neutral", "No runs yet"
    return {"label": card.label, "value": value, "caption": card.caption,
            "state": state, "display_state": display_state, "status_label": status_label}


def project_workspace_data(env: Any, health: Any, routes: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize visible diagnostics, with no credentials or detail-row payload."""
    return {
        "view": "project_workspace",
        "project": str(getattr(env, "app", "") or ""),
        "project_path": str(active_app_store_path(env)),
        "route": "project",
        "projects": [],
        "cards": [_card_data(card) for card in health.cards],
        "actions": [
            {"id": key, "label": label, "description": description}
            for key, label, description in _WORKSPACE_ACTIONS if key in routes
        ],
    }


def render_project_workspace(streamlit: Any, env: Any) -> Any | None:
    """Return health after mounting React; standalone Python pages stay native."""
    routes = streamlit.session_state.get(NAVIGATION_ROUTES_SESSION_KEY)
    if not streamlit.session_state.get(SHELL_ACTIVE_KEY) or not isinstance(routes, dict) or "project" not in routes:
        return None
    from agi_web.react_main_interface import render_main_interface

    health = build_environment_health(env)
    data = project_workspace_data(env, health, routes)
    result = render_main_interface(streamlit, data, key="agilab:project-workspace")
    action = getattr(result, "action", None)
    if isinstance(action, dict) and action.get("kind") == "navigate" and action.get("project_path") == data["project_path"]:
        allowed_routes = {item["id"]: routes[item["id"]] for item in data["actions"]}
        handle_interface_action(
            action, data=data, routes=allowed_routes,
            navigate=lambda target: streamlit.switch_page(target, query_params={"active_app": data["project_path"]}),
            select_project=lambda _: None,
        )
    return health
