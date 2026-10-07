"""PROJECT diagnostics and guarded React navigation use canonical Python state."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agilab.environment.environment_health import EnvironmentHealth, EnvironmentHealthCard
from agilab.ui import react_project_workspace as ui


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    env = SimpleNamespace(app="alpha_project", active_app=tmp_path / "alpha_project")
    routes = {key: object() for key in ("project", "orchestrate", "analysis", "workflow", "project_editor", "settings")}
    st = SimpleNamespace(session_state={ui.SHELL_ACTIVE_KEY: True, ui.NAVIGATION_ROUTES_SESSION_KEY: routes}, switch_page=Mock())
    health = EnvironmentHealth(
        cards=(EnvironmentHealthCard("Manager env", "missing", "Install the environment", "incomplete"),
               EnvironmentHealthCard("Runs", "2", "Last run yesterday", "ready")),
        details=(("Private diagnostic", "DO_NOT_SEND_TO_REACT"),),
    )
    monkeypatch.setattr(ui, "build_environment_health", Mock(return_value=health))
    mount = Mock(return_value=SimpleNamespace(action=None))
    monkeypatch.setattr("agi_web.react_main_interface.render_main_interface", mount)
    return env, routes, st, health, mount


def test_payload_preserves_health_values_states_and_limits_routes(workspace):
    env, routes, _, health, _ = workspace
    data = ui.project_workspace_data(env, health, routes)
    assert [(c["label"], c["value"], c["state"]) for c in data["cards"]] == [
        ("Manager env", "missing", "incomplete"), ("Runs", "2", "ready")]
    assert "DO_NOT_SEND_TO_REACT" not in json.dumps(data)
    assert {a["id"] for a in data["actions"]} == {"orchestrate", "analysis", "workflow", "project_editor"}
    assert data["project_path"] == str(env.active_app)
    assert "settings" not in {a["id"] for a in data["actions"]}
    assert [a["id"] for a in ui.project_workspace_data(env, health, {"analysis": routes["analysis"]})["actions"]] == ["analysis"]


def test_real_health_model_keeps_api_credentials_out_of_frontend_payload(tmp_path):
    from agilab.environment.environment_health import build_environment_health

    secret = "private-api-key-not-for-the-browser"
    env = SimpleNamespace(app="alpha_project", active_app=tmp_path,
                          envars={"OPENAI_API_KEY": secret})
    health = build_environment_health(env, install_status={})
    data = ui.project_workspace_data(env, health, {})
    assert len(data["cards"]) == 8
    assert secret not in json.dumps(data)
    assert [c["label"] for c in data["cards"]] == [c.label for c in health.cards]


@pytest.mark.parametrize("card,display_state,status_label", [
    (EnvironmentHealthCard("API keys", "Optional", "no online provider key found", "incomplete"),
     "neutral", "Optional"),
    (EnvironmentHealthCard("Runs", "0", "no run logs yet", "incomplete"),
     "neutral", "No runs yet"),
    (EnvironmentHealthCard("Runs", "0", "run log directory unavailable", "incomplete"),
     "incomplete", "Needs attention"),
    (EnvironmentHealthCard("Manager env", "missing", "Install the environment", "incomplete"),
     "incomplete", "Needs attention"),
    (EnvironmentHealthCard("Runs", "2", "latest run yesterday", "ready"), "ready", "Ready"),
])
def test_card_presentation_distinguishes_onboarding_without_changing_diagnostics(
    workspace, card, display_state, status_label,
):
    env, routes, _, _, _ = workspace
    data = ui.project_workspace_data(env, EnvironmentHealth(cards=(card,), details=()), routes)
    serialized = data["cards"][0]
    assert (serialized["label"], serialized["value"], serialized["caption"], serialized["state"]) == (
        card.label, card.value, card.caption, card.state,
    )
    assert serialized["display_state"] == display_state
    assert serialized["status_label"] == status_label


def test_workspace_uses_distinct_component_key_and_returns_details_for_python(workspace):
    env, _, st, health, mount = workspace
    assert ui.render_project_workspace(st, env) is health
    assert mount.call_args.kwargs["key"] == "agilab:project-workspace"
    assert mount.call_args.args[1]["view"] == "project_workspace"
    assert st.switch_page.call_count == 0


@pytest.mark.parametrize("missing", ["shell", "route", "mapping"])
def test_standalone_or_unregistered_pages_keep_native_dashboard(workspace, missing):
    env, _, st, _, mount = workspace
    if missing == "shell":
        st.session_state[ui.SHELL_ACTIVE_KEY] = False
    elif missing == "route":
        st.session_state[ui.NAVIGATION_ROUTES_SESSION_KEY].pop("project")
    else:
        st.session_state[ui.NAVIGATION_ROUTES_SESSION_KEY] = None
    assert ui.render_project_workspace(st, env) is None
    ui.build_environment_health.assert_not_called()
    mount.assert_not_called()


@pytest.mark.parametrize("target", ["orchestrate", "analysis", "workflow", "project_editor"])
def test_actions_use_session_pages_and_preserve_full_project_path(workspace, target):
    env, routes, st, _, mount = workspace
    mount.return_value.action = {"kind": "navigate", "value": target, "project": env.app,
                                 "project_path": str(env.active_app), "route": "project"}
    ui.render_project_workspace(st, env)
    st.switch_page.assert_called_once_with(routes[target], query_params={"active_app": str(env.active_app)})


@pytest.mark.parametrize("change", [
    {"project": "beta_project"}, {"project_path": "/other/root/alpha_project"},
    {"route": "home"}, {"value": "settings"}, {"value": "/tmp/evil.py"},
    {"value": ["analysis"]}, {"kind": "project"}, {"project_path": None},
])
def test_stale_or_forged_workspace_actions_do_not_navigate(workspace, change):
    env, _, st, _, mount = workspace
    action = {"kind": "navigate", "value": "analysis", "project": env.app,
              "project_path": str(env.active_app), "route": "project"}
    mount.return_value.action = {**action, **change}
    ui.render_project_workspace(st, env)
    st.switch_page.assert_not_called()
