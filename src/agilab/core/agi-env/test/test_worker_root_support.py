"""Pre-init worker installation context, including polluted process state."""

import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_env import AgiEnv
from agi_env.runtime import agi_env as env_module
from agi_env.runtime import agi_env_instance_initialization as initialization
from agi_env.runtime import runtime_bootstrap_support as bootstrap
from agi_env.runtime.bootstrap_support import resolve_active_app_selection

ROOT_ENV = bootstrap.WORKER_ROOT_ENV


@pytest.mark.parametrize("managed_home", [False, True])
def test_default_root_preserves_home_without_creation(tmp_path, managed_home):
    home = tmp_path / "home"
    if managed_home:
        home /= "MyApp"
    assert bootstrap.resolve_worker_root(home_path=home, environ={}) == home / "wenv"
    assert not home.exists()


def test_expanded_absolute_root_does_not_create_directories(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert bootstrap.resolve_worker_root(
        home_path=tmp_path, environ={ROOT_ENV: "~/selected/workers"},
    ) == tmp_path / "selected/workers"
    assert not (tmp_path / "selected").exists()


@pytest.mark.parametrize("raw", ["", "  ", "relative/workers", ".", "..", "/bad\x00path"])
def test_invalid_root_cannot_read_dotenv_or_write_files(tmp_path, raw):
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(ValueError, match=ROOT_ENV):
        initialization._load_environment(
            SimpleNamespace(), verbose=0, worker_root_environ={ROOT_ENV: raw},
            load_dotenv_values_fn=lambda *_a, **_k: pytest.fail("dotenv read"),
            module_logger=logging.getLogger(__name__),
        )
    assert sorted(tmp_path.rglob("*")) == before


@pytest.mark.parametrize("kind", ["anchor", "home", "cwd", "traversal", "file"])
def test_unsafe_root_preserves_existing_files(tmp_path, kind):
    home = tmp_path / "home"
    home.mkdir()
    blocked = tmp_path / "file"
    blocked.write_text("preserve", encoding="utf-8")
    targets = {
        "anchor": Path(tmp_path.anchor), "home": home, "cwd": Path.cwd(),
        "traversal": tmp_path / "new/../workers", "file": blocked / "workers",
    }
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(ValueError, match=ROOT_ENV):
        bootstrap.resolve_worker_root(home_path=home, environ={ROOT_ENV: str(targets[kind])})
    assert sorted(tmp_path.rglob("*")) == before
    assert blocked.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("ancestor", [False, True])
def test_symlinks_cannot_retarget_root(tmp_path, ancestor):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    root = link / "workers" if ancestor else link
    with pytest.raises(ValueError, match="symbolic links"):
        bootstrap.resolve_worker_root(home_path=tmp_path / "home", environ={ROOT_ENV: str(root)})


def test_unwritable_root_is_rejected_without_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap.os, "access", lambda *_a: False)
    with pytest.raises(ValueError, match="unusable"):
        bootstrap.resolve_worker_root(environ={ROOT_ENV: str(tmp_path / "uncreated")})
    assert not (tmp_path / "uncreated").exists()


@pytest.mark.parametrize("explicit", [False, True])
def test_context_is_selected_before_dotenv(tmp_path, monkeypatch, explicit):
    selected = tmp_path / "selected"
    context = {ROOT_ENV: str(selected)} if explicit else {}
    state = SimpleNamespace()
    expected = selected if explicit else Path.home() / "wenv"

    def load(*_a, **_k):
        assert state.worker_root == expected
        monkeypatch.setenv(ROOT_ENV, str(tmp_path / "ambient"))
        return {ROOT_ENV: str(tmp_path / "dotenv")}

    initialization._load_environment(
        state, verbose=0, worker_root_environ=context,
        load_dotenv_values_fn=load, module_logger=logging.getLogger(__name__),
    )
    assert state.worker_root == expected
    assert state._agilab_worker_root_context == (selected if explicit else None)
    assert not selected.exists()


@pytest.mark.parametrize("session", [False, True])
@pytest.mark.parametrize("explicit", [False, True])
def test_children_freeze_root_against_ambient_and_dotenv(tmp_path, monkeypatch, session, explicit):
    selected = tmp_path / "selected"
    state = object.__new__(AgiEnv)
    state._agilab_initialized = True
    state._agilab_worker_root_context = selected if explicit else None
    state._agilab_resources_context = None
    state._pythonpath_entries = []
    state.envars = {ROOT_ENV: str(tmp_path / "dotenv")}
    state.apps_path = None
    state.app = None
    monkeypatch.setenv(ROOT_ENV, str(tmp_path / "ambient"))
    monkeypatch.setattr(AgiEnv, "_instance", state)
    child = state._build_env_for_instance() if session else AgiEnv._build_env()
    assert child.get(ROOT_ENV) == (str(selected) if explicit else None)
    assert os.environ[ROOT_ENV] == str(tmp_path / "ambient")


def test_constructor_identity_and_app_reinitialization(tmp_path, monkeypatch):
    selected = tmp_path / "selected"
    seen = []

    def initialize(state, **kwargs):
        seen.append(kwargs["worker_root_environ"])
        state.worker_root = bootstrap.resolve_worker_root(environ=kwargs["worker_root_environ"])
        state._agilab_worker_root_context = state.worker_root
        state._agilab_initialized = True
        state._agilab_init_signature = kwargs["init_signature"]

    monkeypatch.setattr(env_module, "initialize_agi_env_instance", initialize)
    monkeypatch.setenv(ROOT_ENV, str(selected))
    state = object.__new__(AgiEnv)
    state._agilab_session_scoped = True
    AgiEnv.__init__(state, apps_path=tmp_path / "apps", app="first_project")
    monkeypatch.setenv(ROOT_ENV, str(tmp_path / "other"))
    with pytest.raises(RuntimeError, match="different configuration"):
        AgiEnv.__init__(state, apps_path=tmp_path / "apps", app="first_project")
    AgiEnv.__init__(
        state, apps_path=tmp_path / "apps", app="second_project", _agilab_reinitialize=True,
    )
    assert seen == [{ROOT_ENV: str(selected)}, {ROOT_ENV: str(selected)}]


def test_for_app_checks_context_before_reusing_matching_app(tmp_path, monkeypatch):
    state = object.__new__(AgiEnv)
    state._agilab_initialized = True
    state._agilab_resources_context = None
    state._agilab_worker_root_context = tmp_path / "selected"
    state.apps_path = tmp_path / "apps"
    state.app = "demo_project"
    state.active_app = state.apps_path / state.app
    monkeypatch.setattr(AgiEnv, "_instance", state)
    monkeypatch.setenv(ROOT_ENV, str(tmp_path / "changed"))
    with pytest.raises(RuntimeError, match="worker root context changed"):
        AgiEnv.for_app(apps_path=state.apps_path, app=state.app)


def test_worker_mode_lookup_uses_selected_root(tmp_path):
    result = resolve_active_app_selection(
        app="demo_worker", active_app_override=None, apps_path=None,
        builtin_apps_path=None, home_abs=tmp_path / "home", is_worker_env=True,
        default_app="", worker_root=tmp_path / "selected",
    )
    assert result.active_app == tmp_path / "selected/demo_worker"


@pytest.mark.parametrize("protected", ["home", "cwd"])
def test_case_alias_of_protected_directory_is_rejected(tmp_path, monkeypatch, protected):
    home = tmp_path / "ProtectedHome"
    home.mkdir()
    target = home
    if protected == "cwd":
        target = tmp_path / "ProtectedCwd"
        target.mkdir()
        monkeypatch.chdir(target)
    alias = target.with_name(target.name.swapcase())
    if not alias.exists() or not alias.samefile(target):
        pytest.skip("filesystem does not expose case aliases for this directory")
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(ValueError, match=ROOT_ENV):
        bootstrap.resolve_worker_root(home_path=home, environ={ROOT_ENV: str(alias)})
    assert sorted(tmp_path.rglob("*")) == before


@pytest.mark.parametrize("explicit", [False, True])
def test_preinit_child_context_recovers_after_rejected_constructor(tmp_path, monkeypatch, explicit):
    monkeypatch.setenv(ROOT_ENV, "relative-workers")
    resources = tmp_path / "corrected-resources"
    monkeypatch.setenv(bootstrap.RESOURCES_DIR_ENV, str(resources))
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(ValueError, match=ROOT_ENV):
        AgiEnv()
    assert not getattr(AgiEnv._instance, "_agilab_initialized", False)
    selected = tmp_path / "corrected-workers"
    if explicit:
        monkeypatch.setenv(ROOT_ENV, str(selected))
    else:
        monkeypatch.delenv(ROOT_ENV)
    child = AgiEnv._build_env()
    assert child[bootstrap.RESOURCES_DIR_ENV] == str(resources)
    assert child.get(ROOT_ENV) == (str(selected) if explicit else None)
    assert os.environ.get(ROOT_ENV) == (str(selected) if explicit else None)
    assert sorted(tmp_path.rglob("*")) == before
