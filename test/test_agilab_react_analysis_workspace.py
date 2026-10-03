"""Validate the React analysis boundary against stale and forged UI actions."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from agilab.ui.react_analysis_workspace import (
    analysis_workspace_data, handle_analysis_action, render_analysis_workspace,
)
from agilab.ui.react_main_interface import NAVIGATION_ROUTES_SESSION_KEY, SHELL_ACTIVE_KEY


@pytest.fixture
def workspace(tmp_path):
    env = SimpleNamespace(app="alpha_project", active_app=tmp_path / "alpha_project", apps_path=tmp_path)
    kwargs = dict(
        overview={"cards": [], "evidence": "", "message": ""},
        view_options={"map": "Coordinates", "geo": "Specialized Python map", "missing": "Missing view"},
        view_routes={"map": {"current_page": "/views/map.py"}, "geo": {"current_page": "/views/geo.py"}},
        notebook_routes={"lab.ipynb": {"current_notebook": "/alpha/lab.ipynb"}},
        selected_views=["map"], selected_notebooks=["lab.ipynb"],
    )
    routes = {"analysis": object(), "workflow": object()}
    return env, kwargs, routes


def _data(workspace):
    env, kwargs, _ = workspace
    return analysis_workspace_data(env, **kwargs, export_available=True)


def _action(data, kind, **values):
    return {key: data[key] for key in ("project", "project_path", "route", "context")} | {"kind": kind, **values}


def _handle(workspace, action, data=None):
    _, kwargs, routes = workspace
    navigate = Mock()
    result = handle_analysis_action(
        action, data=data or _data(workspace), view_routes=kwargs["view_routes"],
        notebook_routes=kwargs["notebook_routes"], routes=routes, navigate=navigate,
    )
    return result, navigate


@pytest.mark.parametrize("views,notebooks", [(["geo"], []), ([], []), (["map", "geo"], ["lab.ipynb"])])
def test_selection_accepts_discovered_choices_and_explicit_empty(workspace, views, notebooks):
    data = _data(workspace)
    result, navigate = _handle(workspace, _action(data, "select", views=views, notebooks=notebooks))
    assert result == {"views": views, "notebooks": notebooks}
    navigate.assert_not_called()


@pytest.mark.parametrize("values", [
    {"views": ["/outside/evil.py"], "notebooks": []},
    {"views": ["map", "map"], "notebooks": []},
    {"views": [True], "notebooks": []},
    {"views": [{"id": "map"}], "notebooks": []},
    {"views": "map", "notebooks": []},
    {"views": [], "notebooks": ["outside.ipynb"]},
    {"views": [], "notebooks": None},
])
def test_invalid_selection_is_rejected_atomically(workspace, values):
    result, navigate = _handle(workspace, _action(_data(workspace), "select", **values))
    assert result == {}
    navigate.assert_not_called()


@pytest.mark.parametrize("key,value", [
    ("project", "beta_project"), ("project_path", "/another/alpha_project"),
    ("route", "project"), ("context", "stale"),
])
def test_stale_project_route_or_selection_cannot_act(workspace, key, value):
    action = _action(_data(workspace), "export_notebook")
    action[key] = value
    result, navigate = _handle(workspace, action)
    assert result == {}
    navigate.assert_not_called()


def test_revision_tracks_selection_and_discovered_destinations(workspace):
    env, kwargs, _ = workspace
    data = _data(workspace)
    for change in ({"selected_views": []}, {"selected_notebooks": []},
                   {"view_routes": {"map": {"current_page": "/new/map.py"}}}):
        current = analysis_workspace_data(env, **(kwargs | change), export_available=True)
        assert current["context"] != data["context"]
        result, navigate = _handle(workspace, _action(data, "select", views=[], notebooks=[]), current)
        assert result == {}
        navigate.assert_not_called()


@pytest.mark.parametrize("kind,value,param", [
    ("open_view", "map", {"current_page": "/views/map.py"}),
    ("open_notebook", "lab.ipynb", {"current_notebook": "/alpha/lab.ipynb"}),
])
def test_open_uses_saved_choices_registered_page_and_server_target(workspace, kind, value, param):
    data = _data(workspace)
    result, navigate = _handle(workspace, _action(data, kind, value=value, url="https://example.invalid"))
    assert result == {}
    navigate.assert_called_once_with(workspace[2]["analysis"], param | {"active_app": data["project_path"]})


@pytest.mark.parametrize("kind,value", [
    ("open_view", "geo"), ("open_view", "missing"), ("open_view", "/outside.py"),
    ("open_notebook", "outside.ipynb"), ("open_view", []), ("navigate", "settings"),
])
def test_unselected_missing_or_arbitrary_destinations_do_not_launch(workspace, kind, value):
    result, navigate = _handle(workspace, _action(_data(workspace), kind, value=value))
    assert result == {}
    navigate.assert_not_called()


def test_export_reuses_python_workflow_without_child_view_params(workspace):
    data = _data(workspace)
    _, navigate = _handle(workspace, _action(data, "export_notebook", current_page="/outside.py"))
    navigate.assert_called_once_with(workspace[2]["workflow"], {"active_app": data["project_path"]})
    data["export_available"] = False
    _, navigate = _handle(workspace, _action(data, "export_notebook"), data)
    navigate.assert_not_called()


def test_failed_draft_can_be_discarded_without_changing_saved_choices(workspace):
    env, kwargs, _ = workspace
    data = analysis_workspace_data(env, **kwargs, export_available=True,
                                   pending_selection={"views": ["geo"], "notebooks": [], "error": "Try again"})
    result, navigate = _handle(workspace, _action(data, "discard"), data)
    assert result == {"discard": True}
    assert data["selected_views"] == ["map"]
    assert data["selected_notebooks"] == ["lab.ipynb"]
    navigate.assert_not_called()


@pytest.mark.parametrize("state", [{}, {SHELL_ACTIVE_KEY: True},
    {SHELL_ACTIVE_KEY: True, NAVIGATION_ROUTES_SESSION_KEY: {"project": object()}}])
def test_standalone_page_keeps_native_controls(workspace, state):
    env, kwargs, _ = workspace
    with patch("agi_web.react_main_interface.render_main_interface") as mount:
        assert render_analysis_workspace(SimpleNamespace(session_state=state), env, **kwargs) is None
    mount.assert_not_called()


def test_mount_uses_distinct_key_and_session_registered_page(workspace):
    env, kwargs, routes = workspace
    st = SimpleNamespace(session_state={SHELL_ACTIVE_KEY: True, NAVIGATION_ROUTES_SESSION_KEY: routes}, switch_page=Mock())

    def emit(_streamlit, data, *, key):
        assert key == "agilab:analysis-workspace"
        assert data["view"] == "analysis_workspace"
        return SimpleNamespace(action=_action(data, "export_notebook"))

    with patch("agi_web.react_main_interface.render_main_interface", side_effect=emit):
        assert render_analysis_workspace(st, env, **kwargs) == {}
    st.switch_page.assert_called_once_with(routes["workflow"], query_params={"active_app": str(env.active_app.resolve())})
