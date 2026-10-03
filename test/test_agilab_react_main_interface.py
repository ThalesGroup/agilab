"""Real routing, project lifecycle and import boundaries for the React main UI."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agilab.ui import react_main_interface as ui
from agilab.ui.page_project_selector import render_project_selector
from agi_web import react_main_interface as host


def fixture_data():
    pages = {key: object() for key in ui._ROUTE_CONTENT}
    env = SimpleNamespace(app="alpha_project", target="alpha", AGILAB_EXPORT_ABS=Path("exports"), projects=["beta_project", "alpha_project"],
                          get_projects=lambda *_: ["beta_project", "alpha_project"], apps_path=Path("."), builtin_apps_path=Path("."))
    st = SimpleNamespace(session_state={"env": env}, query_params={})
    return st, env, pages


def test_route_identity_and_projects_follow_server_state():
    st, env, pages = fixture_data()
    data = ui.interface_data(st, env, pages, pages["analysis"])
    assert data["route"] == "analysis"
    assert data["project"] == "alpha_project"
    assert data["projects"] == ["alpha_project", "beta_project"]
    assert {r["id"] for r in data["routes"]} == set(pages)
    env.app = "beta_project"
    assert ui.interface_data(st, env, pages, pages["home"])["project"] == "beta_project"
    # Never resolve a Page registered in another session by a shared title.
    assert ui.interface_data(st, env, pages, object())["route"] == "home"


@pytest.mark.parametrize("kind,value,project,route", [
    ("navigate", "../../evil.py", "alpha_project", "home"),
    ("navigate", "settings", "old_project", "home"),
    ("navigate", "settings", "alpha_project", "analysis"),
    ("project", "unknown_project", "alpha_project", "home"),
    ("project", "alpha_project", "alpha_project", "home"),
    ("navigate", [], "alpha_project", "home"),
])
def test_invalid_or_stale_actions_do_not_change_routes_or_projects(kind, value, project, route):
    st, env, pages = fixture_data()
    data = ui.interface_data(st, env, pages, pages["home"])
    navigate, select = Mock(), Mock()
    assert not ui.handle_interface_action(dict(kind=kind, value=value, project=project, route=route),
        data=data, routes=pages, navigate=navigate, select_project=select)
    navigate.assert_not_called()
    select.assert_not_called()


def test_actions_use_registered_pages_and_allowlisted_projects():
    st, env, pages = fixture_data()
    data = ui.interface_data(st, env, pages, pages["home"])
    navigate, select = Mock(), Mock()
    for kind, value in (("navigate", "workflow"), ("project", "beta_project")):
        assert ui.handle_interface_action(dict(kind=kind, value=value, project=data["project"], route=data["route"]),
            data=data, routes=pages, navigate=navigate, select_project=select)
    navigate.assert_called_once_with(pages["workflow"])
    select.assert_called_once_with("beta_project")


@pytest.mark.parametrize("child_params", [{"current_page": "/views/map.py"}, {"current_notebook": "/lab.ipynb"}])
def test_active_analysis_navigation_returns_from_child_to_overview(child_params):
    st, env, pages = fixture_data()
    st.query_params.update(child_params)
    data = ui.interface_data(st, env, pages, pages["analysis"])
    navigate = Mock()
    assert ui.handle_interface_action(
        dict(kind="navigate", value="analysis", project=env.app, route="analysis"),
        data=data, routes=pages, navigate=navigate, select_project=Mock(),
    )
    navigate.assert_called_once_with(pages["analysis"])
    st.query_params.clear()
    data = ui.interface_data(st, env, pages, pages["analysis"])
    navigate.reset_mock()
    assert not ui.handle_interface_action(
        dict(kind="navigate", value="analysis", project=env.app, route="analysis"),
        data=data, routes=pages, navigate=navigate, select_project=Mock(),
    )
    navigate.assert_not_called()


def test_project_switch_schedules_existing_cold_bootstrap(monkeypatch, tmp_path):
    from agilab.about_page import bootstrap

    target = tmp_path / "beta_project"
    target.mkdir()
    monkeypatch.setattr(bootstrap, "resolve_active_app_query_target", lambda *_: target)
    st, env, _ = fixture_data()
    st.session_state.update(loaded_df="old data", pipeline_config_snapshot="old pipeline", first_run=False)
    st.query_params, st.rerun = {}, Mock()
    ui.select_interface_project(st, env, "beta_project")
    assert st.session_state["first_run"] is True
    assert st.session_state["loaded_df"] == "old data"
    assert st.query_params["active_app"] == str(target)
    st.rerun.assert_called_once()
    assert env.app == "alpha_project"  # replaced by the bootstrap on the next run


def test_native_state_clears_only_after_successful_project_bootstrap(tmp_path):
    st, env, _ = fixture_data()
    env.active_app = tmp_path / "alpha_project"
    ui.sync_interface_project_state(st, env)
    st.session_state["pipeline_config_snapshot"] = "alpha pipeline"
    ui.sync_interface_project_state(st, env)
    assert st.session_state["pipeline_config_snapshot"] == "alpha pipeline"
    env.app, env.active_app, env.target = "beta_project", tmp_path / "beta_project", "beta"
    ui.sync_interface_project_state(st, env)
    assert "pipeline_config_snapshot" not in st.session_state
    assert st.session_state["project_changed"] is True


def test_project_switch_reseeds_paths_before_orchestrate_export_defaults(tmp_path):
    from agilab.orchestrate.orchestrate_page_support import init_session_state

    st, env, _ = fixture_data()
    env.active_app, env.target = tmp_path / "alpha_project", "alpha"
    env.AGILAB_EXPORT_ABS = tmp_path / "exports"
    ui.sync_interface_project_state(st, env)
    st.session_state.update(df_export_file=str(tmp_path / "exports/alpha/export.csv"),
        datadir=tmp_path / "exports/alpha", datadir_str=str(tmp_path / "exports/alpha"),
        module_rel=Path("alpha"), **{"ARGS-UI": True})
    env.active_app, env.target, env.app = tmp_path / "beta_project", "beta", "beta_project"
    ui.sync_interface_project_state(st, env)
    # The real ORCHESTRATE initializer only fills absent keys. Verify its
    # eventual export destination cannot remain attached to the old project.
    beta_export = tmp_path / "exports/beta/export.csv"
    init_session_state(st.session_state, {"df_export_file": str(beta_export)})
    assert st.session_state["df_export_file"] == str(beta_export)
    assert st.session_state["datadir"] == beta_export.parent
    assert st.session_state["datadir_str"] == str(beta_export.parent)
    assert st.session_state["module_rel"] == Path("beta")
    assert st.session_state["ARGS-UI"] is False


def test_disappeared_project_preserves_current_inputs(monkeypatch):
    from agilab.about_page import bootstrap

    monkeypatch.setattr(bootstrap, "resolve_active_app_query_target", lambda *_: None)
    st, env, _ = fixture_data()
    st.session_state["loaded_df"] = "current data"
    st.query_params, st.warning = {}, Mock()
    ui.select_interface_project(st, env, "beta_project")
    assert st.session_state["loaded_df"] == "current data" and not st.query_params
    st.warning.assert_called_once()


def test_native_selector_does_not_duplicate_react_picker():
    st, env, _ = fixture_data()
    st.session_state[ui.SHELL_ACTIVE_KEY] = True
    assert render_project_selector(st, env.projects, env.app, on_change=Mock()) == env.app


def test_mount_is_registered_once_per_runtime_and_uses_trigger_actions():
    factory = Mock(return_value=Mock(return_value=SimpleNamespace(action=None)))
    registry = object()
    st = SimpleNamespace(components=SimpleNamespace(v2=SimpleNamespace(component=factory)),
        runtime=SimpleNamespace(exists=lambda: True, get_instance=lambda: SimpleNamespace(bidi_component_registry=registry)))
    host.render_main_interface(st, {"project": "alpha_project"})
    host.render_main_interface(st, {"project": "beta_project"})
    assert factory.call_count == 1
    kwargs = factory.return_value.call_args.kwargs
    assert kwargs["height"] == "content" and kwargs["data"]["project"] == "beta_project"
    assert "on_action_change" in kwargs
    registry = object()
    host.render_main_interface(st, {})
    assert factory.call_count == 2
