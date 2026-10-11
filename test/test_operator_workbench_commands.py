"""Operator discovery and reviewed actions use the existing native lifecycle."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agilab.orchestrate.orchestrate_pending_actions import (
    consume_pending_execute_action,
    consume_pending_install_action,
)
from agilab.ui import react_main_interface as ui
from agilab.ui.operator_workbench import queue_workbench_execution


def host_data(*, app="alpha_project", route="home", state=None, query=None, registered=None):
    routes = {key: object() for key in (registered or ui._ROUTE_CONTENT)}
    env = SimpleNamespace(
        app=app, projects=["alpha_project", "beta_project"], apps_path=Path("."),
        builtin_apps_path=Path("."), get_projects=lambda *_: ["alpha_project", "beta_project"],
    )
    host = SimpleNamespace(session_state=state or {}, query_params=query or {})
    data = ui.interface_data(host, env, routes, routes[route], version="2026.10.11")
    return host, routes, data


def dispatch(data, routes, *, command="project-run", reviewed=None, **overrides):
    navigate, select_project, queue = Mock(), Mock(), Mock()
    action = {"kind": "workbench_command", "value": command,
              "project": data["project"], "route": data["route"], **overrides}
    if reviewed is not None:
        action["reviewed"] = reviewed
    result = ui.handle_interface_action(
        action, data=data, routes=routes, navigate=navigate,
        select_project=select_project, queue_action=queue,
    )
    return result, navigate, select_project, queue


def test_discovery_is_scoped_to_registered_routes_and_never_queues_execution():
    host, routes, data = host_data(registered=("home", "project", "workflow"))
    workbench = data["workbench"]
    assert workbench["schema_version"] == 1
    assert [profile["id"] for profile in workbench["profiles"]] == ["notebook"]
    assert {row["value"] for row in workbench["commands"] if row["kind"] == "navigate"} <= set(routes)
    assert all(row["kind"] != "orchestrate_action" for row in workbench["commands"])
    assert consume_pending_execute_action(host.session_state) is None
    assert consume_pending_install_action(host.session_state) is False


def test_seven_profiles_and_credential_free_compact_panes():
    _, _, data = host_data(
        state={"API_KEY": "sensitive", "_last_execute_failed": True},
        query={"current_notebook": "flight.ipynb", "access_token": "secret"},
    )
    workbench = data["workbench"]
    assert {profile["id"] for profile in workbench["profiles"]} == {
        "local", "cluster", "notebook", "evidence", "worker", "demo", "release",
    }
    assert {pane["id"] for pane in workbench["panes"]} == {"context", "diagnostics", "commands", "activity"}
    assert all(profile["pane_id"] in {pane["id"] for pane in workbench["panes"]} for profile in workbench["profiles"])
    assert "Failed" in next(row["value"] for row in workbench["diagnostics"] if row["id"] == "last-run")
    assert any(row["value"] == "flight.ipynb" for row in workbench["diagnostics"])
    assert "sensitive" not in repr(workbench) and "secret" not in repr(workbench)


@pytest.mark.parametrize("query", ({}, {"current_page": "main"}, {"current_notebook": ["untrusted"]}))
def test_missing_or_nontext_child_surface_is_not_serialized(query):
    _, _, data = host_data(query=query)
    assert not any(row["id"] == "child-surface" for row in data["workbench"]["diagnostics"])


@pytest.mark.parametrize("reviewed", (None, False, 1, "true"))
@pytest.mark.parametrize("command", ("project-install", "project-run", "select-project:beta_project"))
def test_mutating_command_requires_explicit_boolean_review(command, reviewed):
    _, routes, data = host_data()
    result, navigate, select, queue = dispatch(data, routes, command=command, reviewed=reviewed)
    assert result is False
    navigate.assert_not_called()
    select.assert_not_called()
    queue.assert_not_called()


@pytest.mark.parametrize("action", ("install", "run"))
def test_reviewed_execution_uses_the_existing_orchestrate_queue_once(action):
    host, routes, data = host_data()
    navigate = Mock()
    queue = Mock(side_effect=lambda value: queue_workbench_execution(host.session_state, value))
    assert ui.handle_interface_action(
        {"kind": "workbench_command", "value": f"project-{action}", "reviewed": True,
         "project": "alpha_project", "route": "home"},
        data=data, routes=routes, navigate=navigate, select_project=Mock(), queue_action=queue,
    )
    queue.assert_called_once_with(action)
    navigate.assert_called_once_with(routes["orchestrate"])
    if action == "install":
        assert consume_pending_install_action(host.session_state) is True
        assert consume_pending_install_action(host.session_state) is False
    else:
        assert consume_pending_execute_action(host.session_state) == "run"
        assert consume_pending_execute_action(host.session_state) is None


def test_reviewed_project_switch_uses_canonical_host_selection():
    _, routes, data = host_data()
    result, navigate, select, queue = dispatch(data, routes, command="select-project:beta_project", reviewed=True)
    assert result is True
    select.assert_called_once_with("beta_project")
    navigate.assert_not_called()
    queue.assert_not_called()


def test_readonly_palette_navigation_needs_no_review_and_ignores_forged_client_target():
    _, routes, data = host_data()
    result, navigate, select, queue = dispatch(data, routes, command="notebook-export", target="../../evil.py")
    assert result is True
    navigate.assert_called_once_with(routes["workflow"])
    select.assert_not_called()
    queue.assert_not_called()


@pytest.mark.parametrize("overrides", ({"project": "old_project"}, {"route": "analysis"}, {"value": "unknown"}))
def test_stale_or_unknown_commands_do_not_execute(overrides):
    _, routes, data = host_data()
    result, navigate, select, queue = dispatch(data, routes, reviewed=True, **overrides)
    assert result is False
    navigate.assert_not_called()
    select.assert_not_called()
    queue.assert_not_called()


def test_project_dependent_commands_are_disabled_until_selection():
    _, routes, data = host_data(app="")
    assert all(profile["disabled"] for profile in data["workbench"]["profiles"])
    result, navigate, select, queue = dispatch(data, routes, reviewed=True)
    assert result is False
    navigate.assert_not_called()
    queue.assert_not_called()
    assert any(command["kind"] == "project" and not command["disabled"] for command in data["workbench"]["commands"])


def test_unsupported_queue_actions_fail_before_setting_pending_state():
    state = {}
    with pytest.raises(ValueError, match="Unsupported"):
        queue_workbench_execution(state, "delete")
    assert state == {}


def test_execution_requires_a_host_queue_and_registered_orchestrate_page():
    _, routes, data = host_data()
    action = {"kind": "workbench_command", "value": "project-run", "reviewed": True,
              "project": data["project"], "route": data["route"]}
    navigate, queue = Mock(), Mock()
    assert not ui.handle_interface_action(action, data=data, routes=routes, navigate=navigate, select_project=Mock())
    restricted_routes = {key: page for key, page in routes.items() if key != "orchestrate"}
    assert not ui.handle_interface_action(
        action, data=data, routes=restricted_routes, navigate=navigate, select_project=Mock(), queue_action=queue,
    )
    navigate.assert_not_called()
    queue.assert_not_called()


@pytest.mark.parametrize("action", ("install", "run"))
@pytest.mark.parametrize(
    "reviewed,source_project,accepted",
    ((True, "alpha_project", True), (False, "alpha_project", False), (True, "old_project", False)),
)
def test_native_render_adapter_queues_only_reviewed_current_project_actions(
    monkeypatch, tmp_path, action, reviewed, source_project, accepted,
):
    """Exercise the real render adapter and pending queue, faking only the widget event."""
    from agi_web import react_main_interface as react_host

    routes = {key: object() for key in ui._ROUTE_CONTENT}
    env = SimpleNamespace(
        app="alpha_project", projects=["alpha_project"], apps_path=tmp_path,
        builtin_apps_path=tmp_path, get_projects=lambda *_: ["alpha_project"],
    )
    host = SimpleNamespace(session_state={}, query_params={}, switch_page=Mock())
    select_project = Mock()
    event = {
        "kind": "workbench_command", "value": f"project-{action}",
        "reviewed": reviewed, "project": source_project, "route": "home",
    }
    monkeypatch.setattr(react_host, "render_main_interface", lambda *_: SimpleNamespace(action=event))

    ui.render_interface(host, env, routes, routes["home"], select_project=select_project)

    select_project.assert_not_called()
    if accepted:
        host.switch_page.assert_called_once_with(
            routes["orchestrate"], query_params={"active_app": str(tmp_path / "alpha_project")},
        )
    else:
        host.switch_page.assert_not_called()
    assert consume_pending_install_action(host.session_state) is (accepted and action == "install")
    assert consume_pending_execute_action(host.session_state) == ("run" if accepted and action == "run" else None)
    assert consume_pending_install_action(host.session_state) is False
    assert consume_pending_execute_action(host.session_state) is None
