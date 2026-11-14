"""Runtime kind follows the executing SDK instead of the application's location."""

from types import SimpleNamespace

import pytest

from agi_env.runtime import agi_env_instance_initialization as initialization
from agi_env.runtime.package_layout_support import (
    resolve_agilab_source_root_from_module_file,
)


@pytest.mark.parametrize("nested", [".venv", "src/agilab/apps/probe_project/.venv"])
def test_wheel_sdk_under_checkout_is_not_a_source_runtime(
    tmp_path, monkeypatch, nested
):
    repo = tmp_path / "repo"
    (repo / "src/agilab/core/agi-env").mkdir(parents=True)
    (repo / "src/agilab/apps").mkdir()
    installed = (
        repo / nested / "lib/python3.13/site-packages/agi_env/runtime/initialization.py"
    )
    installed.parent.mkdir(parents=True)
    installed.write_text("")
    monkeypatch.setattr(initialization, "__file__", str(installed))
    assert resolve_agilab_source_root_from_module_file(installed) is None
    env = SimpleNamespace(is_source_env=False, is_worker_env=False)
    initialization._configure_environment_kind(
        env,
        envars={},
        apps_path=repo / "src/agilab/apps",
        active_app_override=None,
        is_agilab_installed=False,
    )
    assert not env.is_source_env


@pytest.mark.parametrize("explicit,expected", [(None, True), ("0", False), ("1", True)])
def test_source_sdk_identity_and_explicit_override(
    tmp_path, monkeypatch, explicit, expected
):
    module = (
        tmp_path / "repo/src/agilab/core/agi-env/src/agi_env/runtime/initialization.py"
    )
    module.parent.mkdir(parents=True)
    module.write_text("")
    monkeypatch.setattr(initialization, "__file__", str(module))
    env = SimpleNamespace(is_source_env=False, is_worker_env=False)
    initialization._configure_environment_kind(
        env,
        envars={} if explicit is None else {"IS_SOURCE_ENV": explicit},
        apps_path=tmp_path / "apps",
        active_app_override=None,
        is_agilab_installed=False,
    )
    assert env.is_source_env is expected
