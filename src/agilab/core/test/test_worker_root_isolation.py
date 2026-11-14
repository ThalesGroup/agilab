"""Cross-package local worker-root deployment and cleanup contracts."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from agi_env import AgiEnv
from agi_cluster.agi_distributor.api.worker_cli_support import prepare_local_worker_cli
from agi_cluster.agi_distributor.runtime import cleanup_support
from agi_node.agi_dispatcher import cli
from agi_node.agi_dispatcher import base_worker_execution_support as execution
from agi_node.agi_dispatcher import base_worker_runtime_support as loading


def _selected_environment(tmp_path):
    root = tmp_path / "selected-workers"
    target = root / "probe_worker"
    target.mkdir(parents=True)
    return SimpleNamespace(
        worker_root=root, _agilab_worker_root_context=root,
        wenv_abs=target, home_abs=tmp_path / "home", cli=Path(cli.__file__),
    )


def test_copied_cli_cleans_selected_root_without_importing_sdk(tmp_path):
    env = _selected_environment(tmp_path)
    copied = prepare_local_worker_cli(env)
    (env.wenv_abs / "sentinel").write_text("task owned", encoding="utf-8")
    script = """
import importlib.abc, runpy, sys
class RejectSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"agi_env", "agi_node", "agi_cluster"}:
            raise AssertionError("Standalone CLI attempted SDK import: " + fullname)
sys.meta_path.insert(0, RejectSdk())
sys.argv = [sys.argv[1], "clean", sys.argv[2]]
runpy.run_path(sys.argv[0], run_name="__main__")
"""
    child_env = dict(os.environ, AGILAB_WORKER_ROOT=str(env.worker_root))
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(copied), str(env.wenv_abs)],
        cwd=tmp_path, env=child_env, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not env.wenv_abs.exists()
    assert copied.exists()
    assert (env.worker_root / "agilab_runtime_bootstrap_support.py").exists()


def test_copied_cli_extracts_before_sdk_install(tmp_path):
    env = _selected_environment(tmp_path)
    copied = prepare_local_worker_cli(env)
    with ZipFile(env.wenv_abs / "probe.egg", "w") as archive:
        archive.writestr("probe_worker/probe_worker.py", "class ProbeWorker: pass\n")
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(copied), "unzip", str(env.wenv_abs)],
        cwd=tmp_path, env=dict(os.environ, AGILAB_WORKER_ROOT=str(env.worker_root)),
        text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (env.wenv_abs / "src/probe_worker/probe_worker.py").is_file()


def test_cli_refreshes_partial_install_and_rejects_symlink_artifacts(tmp_path):
    env = _selected_environment(tmp_path)
    copied = env.worker_root / "cli.py"
    copied.write_text("old partial install", encoding="utf-8")
    assert prepare_local_worker_cli(env).read_bytes() == Path(cli.__file__).read_bytes()
    outside = tmp_path / "unrelated.py"
    outside.write_text("preserve", encoding="utf-8")
    copied.unlink()
    copied.symlink_to(outside)
    with pytest.raises(ValueError, match="symbolic links"):
        prepare_local_worker_cli(env)
    assert outside.read_text(encoding="utf-8") == "preserve"


def test_cleanup_recognizes_only_frozen_explicit_root(tmp_path, monkeypatch):
    env = _selected_environment(tmp_path)
    monkeypatch.setenv("AGILAB_WORKER_ROOT", str(tmp_path / "ambient"))
    assert cleanup_support._validated_local_worker_runtime_target(env) == env.wenv_abs
    env._agilab_worker_root_context = None
    with pytest.raises(RuntimeError, match="unsafe"):
        cleanup_support._validated_local_worker_runtime_target(env)


def test_cleanup_preserves_exact_token_and_allows_successful_continuation(tmp_path, monkeypatch):
    env = _selected_environment(tmp_path)
    monkeypatch.setenv("AGILAB_WORKER_ROOT", str(env.worker_root))
    monkeypatch.setattr(cli, "_target_dask_processes", lambda _target: {})
    token = "a" * 32
    assert cli.acquire_remote_target_lease(env.wenv_abs, token)
    assert not cli.clean(
        env.wenv_abs, lease_token="b" * 32, home_path=env.home_abs, cwd_path=tmp_path,
    )
    assert env.wenv_abs.is_dir()
    assert cli.clean(
        env.wenv_abs, lease_token=token, home_path=env.home_abs, cwd_path=tmp_path,
    )
    assert cli.release_remote_target_lease(env.wenv_abs, token)
    env.wenv_abs.mkdir()
    assert cli.clean(env.wenv_abs, home_path=env.home_abs, cwd_path=tmp_path)
    assert not cli.clean(env.worker_root, home_path=env.home_abs, cwd_path=tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    env.wenv_abs.symlink_to(outside, target_is_directory=True)
    assert not cli.clean(env.wenv_abs, home_path=env.home_abs, cwd_path=tmp_path)
    assert outside.is_dir()


def test_worker_egg_install_path_can_use_frozen_root_despite_ambient_change(tmp_path, monkeypatch):
    selected = tmp_path / "selected"
    dask_home = tmp_path / "dask"
    dask_home.mkdir()
    (dask_home / "probe_worker.egg").write_bytes(b"payload")
    monkeypatch.setenv("AGILAB_WORKER_ROOT", str(tmp_path / "changed"))
    egg, target = execution._resolve_worker_egg_install_paths(
        home_dir=tmp_path / "home", target_worker="probe_worker",
        dask_home=str(dask_home), worker_root=selected,
    )
    assert Path(egg).parent == dask_home
    assert target == selected / "probe_worker"


@pytest.mark.parametrize("source_mode", [False, True])
def test_real_checkout_marker_does_not_override_selected_worker_root(tmp_path, monkeypatch, source_mode):
    apps = tmp_path / "apps"
    app = apps / "probe_01a1d57c_project"
    manager = app / "src/probe_01a1d57c"
    worker = app / "src/probe_01a1d57c_worker"
    manager.mkdir(parents=True)
    worker.mkdir()
    for package in (manager, worker):
        (package / "__init__.py").write_text("", encoding="utf-8")
    (manager / "probe_01a1d57c.py").write_text(
        "class Probe01A1D57C: pass\n", encoding="utf-8",
    )
    (worker / "probe_01a1d57c_worker.py").write_text(
        "class Probe01A1D57CWorker: marker = 'dynamic-worker'\n", encoding="utf-8",
    )
    (app / "pyproject.toml").write_text(
        '[project]\nname = "probe_01a1d57c_project"\nversion = "1.0"\n',
        encoding="utf-8",
    )
    (worker / "pyproject.toml").write_text(
        '[project]\nname = "probe_01a1d57c_worker"\nversion = "1.0"\n',
        encoding="utf-8",
    )
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / ".env").write_text(
        f"IS_SOURCE_ENV={int(source_mode)}\n", encoding="utf-8",
    )
    selected = tmp_path / "selected"
    assert not selected.exists()
    marker = Path.home() / ".local/share/agilab/.agilab-path"
    assert marker.is_file()
    marker_before = marker.read_bytes()
    monkeypatch.setenv("AGILAB_RESOURCES_DIR", str(resources))
    monkeypatch.setenv("AGILAB_WORKER_ROOT", str(selected))
    env = AgiEnv(apps_path=apps, app=app.name)
    assert env.is_source_env is source_mode
    assert env.wenv_abs == selected / "probe_01a1d57c_worker"
    assert env.wenv_rel == Path("wenv/probe_01a1d57c_worker")
    assert not (env.wenv_abs / ".venv").exists()
    assert marker.read_bytes() == marker_before
    monkeypatch.syspath_prepend(str(env.app_src))
    loaded = loading.load_worker(env, 0, load_module_fn=loading.load_module)
    assert loaded.marker == "dynamic-worker"
    assert Path(sys.modules[loaded.__module__].__file__).is_relative_to(app)


def test_copied_cli_rejects_linked_policy_before_executing_it(tmp_path):
    env = _selected_environment(tmp_path)
    copied = prepare_local_worker_cli(env)
    helper = copied.with_name("agilab_runtime_bootstrap_support.py")
    helper.unlink()
    outside = tmp_path / "untrusted-policy.py"
    outside.write_text("raise AssertionError('must not execute')\n", encoding="utf-8")
    helper.symlink_to(outside)
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(copied), "clean", str(env.wenv_abs)],
        cwd=tmp_path, env=dict(os.environ, AGILAB_WORKER_ROOT=str(env.worker_root)),
        text=True, capture_output=True, timeout=30,
    )
    assert result.returncode != 0
    assert "must not execute" not in result.stderr
    assert "symbolic link" in result.stderr
    assert env.wenv_abs.is_dir()


@pytest.mark.parametrize("selected", [False, True])
def test_worker_build_ignores_stale_manager_environment_root(tmp_path, monkeypatch, selected):
    import logging

    manager_root = tmp_path / "manager-only-root"
    process_root = tmp_path / "local-process-root"
    if selected:
        monkeypatch.setenv("AGILAB_WORKER_ROOT", str(process_root))
    else:
        monkeypatch.delenv("AGILAB_WORKER_ROOT", raising=False)
    dask_home = tmp_path / "incoming"
    dask_home.mkdir()
    (dask_home / "probe_worker.egg").write_bytes(b"task-owned worker artifact")
    state = SimpleNamespace(
        env=SimpleNamespace(worker_root=manager_root),
        _worker_id=0,
    )
    execution.build_worker_artifacts(
        target_worker="probe_worker", dask_home=str(dask_home), worker="task-worker",
        mode=0, verbose=0, base_worker_cls=state,
        logger_obj=logging.getLogger(__name__), getuser_fn=lambda: "agi",
        file_path=__file__, sys_path=[],
    )
    expected = process_root if selected else Path.home() / "wenv"
    assert (expected / "probe_worker/probe_worker.egg").is_file()
    assert not manager_root.exists()


def test_worker_build_keeps_current_local_environment_root(tmp_path, monkeypatch):
    import logging

    local_root = tmp_path / "frozen-local-root"
    ambient_root = tmp_path / "changed-ambient-root"
    manager_root = tmp_path / "foreign-manager-root"
    monkeypatch.setattr(
        AgiEnv, "_instance",
        SimpleNamespace(worker_root=local_root, _agilab_initialized=True),
    )
    monkeypatch.setenv("AGILAB_WORKER_ROOT", str(ambient_root))
    dask_home = tmp_path / "incoming"
    dask_home.mkdir()
    (dask_home / "probe_worker.egg").write_bytes(b"task-owned worker artifact")
    execution.build_worker_artifacts(
        target_worker="probe_worker", dask_home=str(dask_home), worker="task-worker",
        mode=0, verbose=0,
        base_worker_cls=SimpleNamespace(
            env=SimpleNamespace(worker_root=manager_root), _worker_id=0,
        ),
        logger_obj=logging.getLogger(__name__), getuser_fn=lambda: "agi",
        file_path=__file__, sys_path=[],
    )
    assert (local_root / "probe_worker/probe_worker.egg").is_file()
    assert not ambient_root.exists()
    assert not manager_root.exists()
