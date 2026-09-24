"""Bootstrap transition recovery and environment refresh contracts."""

from types import MappingProxyType, SimpleNamespace

import pytest

from agilab.about_page import bootstrap, env_editor


@pytest.mark.parametrize("locked", [False, True])
def test_rebootstrap_legacy_environment_restores_authority_after_initialization(
    tmp_path, locked
):
    events = []

    class Lock:
        def __enter__(self):
            events.append("lock")

        def __exit__(self, *args):
            events.append("unlock")

    class Environment:
        _lock = Lock() if locked else None

        def __init__(self, **kwargs):
            events.append(kwargs)
            self.init_done = False
            self._agilab_authorized_app_container_roots = ()

    env = object.__new__(Environment)
    env.verbose = 2
    env.init_done = True
    roots = (tmp_path / "allowed",)
    env._agilab_authorized_app_container_roots = roots
    target = roots[0] / "demo_project"
    assert bootstrap._rebootstrap_active_app_path(
        env,
        target,
        target.name,
        streamlit=SimpleNamespace(warning=lambda text: pytest.fail(text)),
    )
    expected = {
        "apps_path": target.parent,
        "app": target.name,
        "verbose": 2,
        "_agilab_reinitialize": True,
    }
    assert events == (["lock", expected, "unlock"] if locked else [expected])
    assert env.init_done is True
    assert env._agilab_authorized_app_container_roots == roots


def test_rebootstrap_public_reinitializer_preserves_authorized_roots(tmp_path):
    roots = (tmp_path,)
    calls = []
    env = SimpleNamespace(
        verbose=0, init_done=True, _agilab_authorized_app_container_roots=roots
    )

    def initialize(**kwargs):
        calls.append(kwargs)
        env.init_done = False
        env._agilab_authorized_app_container_roots = ()

    env.reinitialize_for_app = initialize
    target = tmp_path / "other_project"
    assert bootstrap._rebootstrap_active_app_path(
        env,
        target,
        target.name,
        streamlit=SimpleNamespace(warning=lambda text: pytest.fail(text)),
    )
    assert calls == [{"apps_path": tmp_path, "app": target.name, "verbose": 0}]
    assert env.init_done is True
    assert env._agilab_authorized_app_container_roots == roots


def test_query_transition_rolls_back_first_run_when_query_write_fails(
    monkeypatch, tmp_path
):
    target = tmp_path / "target_project"
    env = SimpleNamespace(app="current_project")
    state = {"first_run": False}
    ui = SimpleNamespace(
        query_params=MappingProxyType({"active_app": str(target)}),
        session_state=state,
        rerun=lambda: pytest.fail("failed transition reran"),
    )
    monkeypatch.setattr(
        bootstrap, "resolve_active_app_query_target", lambda env, value: target
    )
    assert bootstrap.sync_active_app_from_query(env, streamlit=ui) is False
    assert state == {"first_run": False}
    assert env.app == "current_project"


@pytest.mark.parametrize("previous", [False, True])
def test_query_transition_schedules_cold_rerun_without_mutating_environment(
    monkeypatch, tmp_path, previous
):
    target = tmp_path / "target_project"
    env = SimpleNamespace(app="current_project")
    calls = []
    ui = SimpleNamespace(
        query_params={"active_app": [str(target)]},
        session_state={"first_run": previous},
        rerun=lambda: calls.append("rerun"),
    )
    monkeypatch.setattr(
        bootstrap, "resolve_active_app_query_target", lambda env, value: target
    )
    assert bootstrap.sync_active_app_from_query(env, streamlit=ui)
    assert ui.query_params["active_app"] == str(target)
    assert ui.session_state["first_run"] is True
    assert env.app == "current_project"
    assert calls == ["rerun"]


@pytest.fixture
def local_env_file(tmp_path, monkeypatch):
    path = tmp_path / "runtime.env"
    state = {}
    monkeypatch.setattr(env_editor, "ENV_FILE_PATH", path)
    monkeypatch.setattr(env_editor, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(env_editor.os, "environ", {})
    return path, state


@pytest.mark.parametrize("env_values", [None, {}, "immutable"])
def test_environment_refresh_tolerates_uninitialized_environment_map(
    local_env_file, env_values
):
    path, state = local_env_file
    path.write_text("AGILAB_TEST_REFRESH=updated\n")
    env = SimpleNamespace(envars=env_values)
    env_editor._refresh_env_from_file(env)
    assert env_editor.os.environ["AGILAB_TEST_REFRESH"] == "updated"
    if isinstance(env_values, dict):
        assert env.envars["AGILAB_TEST_REFRESH"] == "updated"
    assert state["env_file_mtime_ns"] == path.stat().st_mtime_ns


def test_empty_environment_refresh_records_mtime_and_skips_reparse(
    local_env_file, monkeypatch
):
    path, state = local_env_file
    path.write_text("# no configuration yet\n")
    env_editor._refresh_env_from_file(SimpleNamespace(envars={}))
    assert state["env_file_mtime_ns"] == path.stat().st_mtime_ns
    monkeypatch.setattr(
        env_editor,
        "_load_env_file_map",
        lambda *a, **k: pytest.fail("unchanged file reparsed"),
    )
    env_editor._refresh_env_from_file(SimpleNamespace(envars={}))


def test_env_refresh_invalid_saved_app_path_uses_configured_root(
    local_env_file, tmp_path
):
    path, state = local_env_file
    apps = tmp_path / "apps"
    apps.mkdir()
    path.write_text("APPS_PATH=" + str(apps) + "\n")
    state["apps_path"] = {"invalid": "saved path"}
    env = SimpleNamespace(envars={})
    env_editor._refresh_env_from_file(env)
    assert env.apps_path == apps.resolve()


@pytest.mark.parametrize("template_state", ["missing", "invalid-utf8"])
def test_env_initialization_unreadable_template_creates_empty_config(
    tmp_path, monkeypatch, template_state
):
    path = tmp_path / "settings/runtime.env"
    template = tmp_path / "template.env"
    if template_state == "invalid-utf8":
        template.write_bytes(b"\xff")
    monkeypatch.setattr(env_editor, "TEMPLATE_ENV_PATH", template)
    assert env_editor._ensure_env_file(path) == path
    assert path.read_text() == ""
