"""Environment and project-selection failure contracts for the native UI bootstrap."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from agilab.about_page import bootstrap


def _env(root, current="current_project"):
    return SimpleNamespace(
        app=current, active_app=root / current, apps_path=root,
        builtin_apps_path=root / "builtin", apps_repository_root=None, projects=set(),
        _agilab_authorized_app_container_roots=(root,),
    )


def _ports(load_last=lambda: None):
    return bootstrap.BootstrapPorts(
        agi_env_cls=None, activate_mlflow=lambda env: None,
        background_services_enabled=lambda: False, load_last_active_app=load_last,
        store_last_active_app=lambda path: None, environ={},
    )


def _startup(root, *, ui=None, ports=None, args=None, warm=None, saved=None):
    return bootstrap.resolve_startup_app_request(
        streamlit=ui or SimpleNamespace(query_params={}),
        args=args or argparse.Namespace(active_app=None),
        ports=ports or _ports(), apps_path=root, saved_env=saved or {}, warm_env=warm,
    )


def test_persisted_identity_survives_unexpandable_home_without_taking_authority(
    tmp_path, monkeypatch,
):
    raw = "~unavailable_account/demo_project"
    original = Path.expanduser

    def fail(path):
        if str(path) == raw:
            raise RuntimeError("home is unavailable")
        return original(path)

    monkeypatch.setattr(Path, "expanduser", fail)
    assert bootstrap.persisted_active_app_request(_env(tmp_path), raw) == raw


def test_persisted_absolute_identity_skips_invalid_root_and_keeps_allowed_root(tmp_path):
    project = tmp_path / "builtin" / "demo_project"
    project.mkdir(parents=True)
    env = _env(tmp_path)
    env.apps_path = object()
    assert bootstrap.persisted_active_app_request(env, str(project)) == str(project)


def test_exact_startup_candidate_rejects_unresolvable_path(tmp_path, monkeypatch):
    project = tmp_path / "demo_project"
    original = Path.resolve

    def fail(path, *args, **kwargs):
        if path == project:
            raise PermissionError("project inaccessible")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fail)
    assert not bootstrap._path_matches_startup_root_candidate(project, project.name, (tmp_path,))
    assert not bootstrap._path_is_allowed_startup_target(
        project, project.name, container_roots=(), installed_projects=(),
    )


def test_exact_startup_candidate_skips_unexpandable_root(tmp_path, monkeypatch):
    project = tmp_path / "demo_project"
    broken_root = Path("~unavailable_account")
    original = Path.expanduser

    def fail(path):
        if path == broken_root:
            raise RuntimeError("root home unavailable")
        return original(path)

    monkeypatch.setattr(Path, "expanduser", fail)
    assert bootstrap._path_matches_startup_root_candidate(
        project, project.name, (broken_root, tmp_path),
    )


@pytest.mark.parametrize("failure", ["expand", "resolve", "inspect"])
def test_candidate_resolution_refuses_uninspectable_project(tmp_path, monkeypatch, failure):
    project = tmp_path / "demo_project"
    project.mkdir()
    env = _env(tmp_path)
    raw = str(project)
    if failure == "expand":
        original = Path.expanduser

        def fail(path):
            if path == project:
                raise RuntimeError("home unavailable")
            return original(path)

        monkeypatch.setattr(Path, "expanduser", fail)
    elif failure == "resolve":
        original = Path.resolve

        def fail(path, *args, **kwargs):
            if path == project:
                raise PermissionError("resolve denied")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", fail)
    else:
        original = Path.is_dir

        def fail(path):
            if path == project:
                raise PermissionError("directory inspect denied")
            return original(path)

        monkeypatch.setattr(Path, "is_dir", fail)
    assert bootstrap._resolve_startup_candidate_path(
        raw, project.name, resolver_env=env, allowed_roots=(tmp_path,), installed_projects=(),
    ) is None
    assert env.app == "current_project"


@pytest.mark.parametrize("value", ["", "not-a-project", "/tmp/not-a-project"])
def test_query_target_rejects_invalid_project_identity(tmp_path, value):
    assert bootstrap.resolve_active_app_query_target(_env(tmp_path), value) is None


def test_query_target_requires_explicit_authorized_roots(tmp_path):
    project = tmp_path / "demo_project"
    project.mkdir()
    env = _env(tmp_path)
    env._agilab_authorized_app_container_roots = ()
    assert bootstrap.resolve_active_app_query_target(env, str(project)) is None


def test_query_target_does_not_promote_failed_provider_discovery(tmp_path, monkeypatch):
    env = _env(tmp_path)

    def unavailable():
        raise OSError("provider unavailable")

    monkeypatch.setattr(bootstrap, "discover_installed_app_projects", unavailable)
    assert bootstrap.resolve_active_app_query_target(env, "missing_project") is None
    assert env.app == "current_project"


def test_startup_recovers_from_query_provider_and_remembered_state_failures(tmp_path, monkeypatch):
    project = tmp_path / "demo_project"
    project.mkdir()

    class QueryFailure(dict):
        def get(self, key, default=None):
            raise RuntimeError("query unavailable")

    def unavailable():
        raise OSError("provider unavailable")

    def unreadable_last():
        raise PermissionError("remembered state unavailable")

    monkeypatch.setattr(bootstrap, "discover_installed_app_projects", unavailable)
    request = _startup(
        tmp_path, ui=SimpleNamespace(query_params=QueryFailure()),
        ports=_ports(unreadable_last), saved={"APP_DEFAULT": project.name},
    )
    assert request.target_path == project
    assert request.source == "default"
    assert tmp_path in request.authorized_container_roots


@pytest.mark.parametrize("query", [[], (), ["demo_project"], ("demo_project",)])
def test_startup_handles_query_sequences_with_explicit_cli_fallback(tmp_path, monkeypatch, query):
    project = tmp_path / "demo_project"
    project.mkdir()
    monkeypatch.setattr(bootstrap, "discover_installed_app_projects", lambda: ())
    request = _startup(
        tmp_path, ui=SimpleNamespace(query_params={"active_app": query}),
        args=argparse.Namespace(active_app=project.name),
    )
    assert request.target_path == project
    assert request.source == ("query" if query else "cli")


@pytest.mark.parametrize("app,active", [("invalid-name", "demo_project"), ("demo_project", None)])
def test_invalid_warm_identity_cannot_override_selected_default(tmp_path, monkeypatch, app, active):
    project = tmp_path / "demo_project"
    project.mkdir()
    env = _env(tmp_path, app)
    env._agilab_session_scoped = True
    env.active_app = tmp_path / active if active else None
    monkeypatch.setattr(bootstrap, "discover_installed_app_projects", lambda: ())
    request = _startup(tmp_path, warm=env, saved={"APP_DEFAULT": project.name})
    assert request.target_path == project
    assert request.source == "default"


def test_source_settings_inspection_failure_keeps_selected_path_for_fail_closed_recovery(
    tmp_path, monkeypatch,
):
    source = tmp_path / "source_settings.toml"
    source.write_text("[cluster]\ncluster_enabled = true\n")
    project = tmp_path / "demo_project"
    project.mkdir()
    request = bootstrap.StartupAppRequest(project.name, project, "query")
    monkeypatch.setattr(bootstrap, "find_source_app_settings_file", lambda **kwargs: source)
    original = Path.is_file

    def denied(path):
        if path == source:
            raise PermissionError("source inspection denied")
        return original(path)

    monkeypatch.setattr(Path, "is_file", denied)
    assert bootstrap.startup_app_source_settings_file(
        request, apps_path=tmp_path, saved_env={}, ports=_ports(),
    ) == source
    assert source.read_text() == "[cluster]\ncluster_enabled = true\n"


def test_query_transition_recovers_unreadable_first_run_state(tmp_path):
    project = tmp_path / "demo_project"
    project.mkdir()
    env = _env(tmp_path)

    class ReadFailure(dict):
        def get(self, key, default=None):
            raise ValueError("state read failed")

    reruns = []
    state = ReadFailure()
    ui = SimpleNamespace(
        query_params={"active_app": project.name}, session_state=state,
        rerun=lambda: reruns.append(True),
    )
    assert bootstrap.sync_active_app_from_query(env, streamlit=ui)
    assert state["first_run"] is True
    assert ui.query_params["active_app"] == str(project)
    assert env.app == "current_project"
    assert reruns == [True]


@pytest.mark.parametrize("rollback_fails", [False, True])
def test_query_transition_write_failure_never_reruns_or_mutates_active_environment(
    tmp_path, rollback_fails,
):
    project = tmp_path / "demo_project"
    project.mkdir()
    env = _env(tmp_path)

    class WriteFailure(dict):
        def __setitem__(self, key, value):
            if rollback_fails:
                raise ValueError("state write failed")
            return super().__setitem__(key, value)

    class QueryFailure(dict):
        def __setitem__(self, key, value):
            if value != env.app:
                raise RuntimeError("query write failed")
            return super().__setitem__(key, value)

    state = WriteFailure(first_run=False)
    query = QueryFailure(active_app=project.name)
    reruns = []
    ui = SimpleNamespace(query_params=query, session_state=state, rerun=lambda: reruns.append(True))
    assert not bootstrap.sync_active_app_from_query(env, streamlit=ui)
    assert state["first_run"] is False
    assert query["active_app"] == env.app
    assert env.app == "current_project"
    assert env.active_app == tmp_path / "current_project"
    assert reruns == []


@pytest.mark.parametrize("missing", ["rerun", "session"])
def test_query_transition_without_host_controls_keeps_existing_environment(tmp_path, missing):
    project = tmp_path / "demo_project"
    project.mkdir()
    env = _env(tmp_path)
    state = {"first_run": False}
    ui = SimpleNamespace(
        query_params={"active_app": project.name},
        session_state=state if missing != "session" else None,
        rerun=(lambda: pytest.fail("unsupported transition must not rerun")) if missing != "rerun" else None,
    )
    assert not bootstrap.sync_active_app_from_query(env, streamlit=ui)
    assert ui.query_params["active_app"] == env.app
    assert state == {"first_run": False}
    assert env.active_app == tmp_path / "current_project"


def test_startup_provider_only_authorizes_its_exact_advertised_project(tmp_path):
    provider_project = tmp_path / "provider" / "demo_project"
    provider_project.mkdir(parents=True)
    advertised = (SimpleNamespace(project_root=provider_project),)
    assert bootstrap._path_is_allowed_startup_target(
        provider_project, "demo_project", container_roots=(), installed_projects=advertised,
    )
    assert not bootstrap._path_is_allowed_startup_target(
        provider_project.parent / "other_project", "other_project",
        container_roots=(), installed_projects=advertised,
    )


@pytest.mark.parametrize("response", ["legacy", "wrong-project", "selected-project"])
def test_ui_session_adapter_enforces_session_ownership_and_validated_project(tmp_path, response):
    project = tmp_path / "demo_project"
    project.mkdir()
    request = bootstrap.StartupAppRequest(project.name, project, "query")
    env = _env(tmp_path, project.name if response != "wrong-project" else "other_project")
    env._agilab_session_scoped = response != "legacy"
    captured = []

    def session(**kwargs):
        captured.append(kwargs)
        return env

    sdk = SimpleNamespace(session=session)
    if response == "selected-project":
        assert bootstrap._create_streamlit_session_env(
            sdk, apps_path=tmp_path, startup_app=request, verbose=2,
        ) is env
    else:
        with pytest.raises(RuntimeError, match="legacy shared|different project"):
            bootstrap._create_streamlit_session_env(
                sdk, apps_path=tmp_path, startup_app=request, verbose=2,
            )
    assert captured == [{"apps_path": tmp_path, "active_app": project, "verbose": 2}]


def test_preinit_launch_values_support_sdk_without_persistence_setter():
    environ = {"keep": "unchanged"}
    bootstrap.persist_preinit_launch_env(
        SimpleNamespace(), {"APP_DEFAULT": "demo_project"}, environ=environ,
    )
    assert environ == {"keep": "unchanged", "APP_DEFAULT": "demo_project"}


def test_workspace_settings_resolution_failure_preserves_source_and_target(tmp_path, monkeypatch):
    project = tmp_path / "apps" / "demo_project"
    project.mkdir(parents=True)
    settings = project / "app_settings.toml"
    original_text = "[cluster]\ncluster_enabled = true\n"
    settings.write_text(original_text)
    original_resolve = Path.resolve

    def denied(path, *args, **kwargs):
        if path == settings:
            raise PermissionError("selected settings resolve denied")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", denied)
    with pytest.raises(ValueError, match="Cannot safely resolve workspace settings"):
        bootstrap.disable_cluster_in_app_settings(settings)
    assert settings.read_text() == original_text
