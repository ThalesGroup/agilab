from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import AGI
import agi_cluster.agi_distributor.agi_distributor as agi_distributor_module


@pytest.fixture(autouse=True)
def _reset_agi_wrapper_state(monkeypatch):
    snapshot = {
        "_instantiated": getattr(AGI, "_instantiated", False),
        "env": getattr(AGI, "env", None),
    }
    monkeypatch.setattr(AGI, "_instantiated", False, raising=False)
    AGI.env = SimpleNamespace()
    yield
    AGI._instantiated = snapshot["_instantiated"]
    AGI.env = snapshot["env"]


def test_agi_singleton_marks_instance_on_first_init():
    AGI("demo")
    assert AGI._instantiated is True


def test_agi_sync_wrapper_surface_delegates(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr(
        agi_distributor_module.service_runtime_support,
        "service_queue_paths",
        lambda queue_root: calls.append(("service_queue_paths", queue_root)) or {"root": queue_root},
    )
    monkeypatch.setattr(
        agi_distributor_module.capacity_support,
        "train_capacity",
        lambda agi_cls, train_home, log=None: calls.append(("train_capacity", agi_cls, train_home, log)),
    )
    monkeypatch.setattr(
        agi_distributor_module.capacity_support,
        "update_capacity",
        lambda agi_cls: calls.append(("update_capacity", agi_cls)),
    )
    monkeypatch.setattr(
        agi_distributor_module.capacity_support,
        "train_capacity",
        lambda agi_cls, train_home, log=None: calls.append(("train_capacity", agi_cls, train_home, log)),
    )
    monkeypatch.setattr(
        agi_distributor_module.scheduler_io_support,
        "find_free_port",
        lambda **kwargs: calls.append(("find_free_port", kwargs)) or 4321,
    )
    monkeypatch.setattr(
        agi_distributor_module.scheduler_io_support,
        "get_scheduler",
        lambda *args, **kwargs: calls.append(("get_scheduler", args, kwargs)) or ("127.0.0.1", 9999),
    )
    monkeypatch.setattr(
        agi_distributor_module.scheduler_io_support,
        "get_stdout",
        lambda func, *args, **kwargs: calls.append(("get_stdout", func, args, kwargs)) or ("out", "res"),
    )
    monkeypatch.setattr(
        agi_distributor_module.scheduler_io_support,
        "read_stderr",
        lambda *args, **kwargs: calls.append(("read_stderr", args, kwargs)),
    )
    monkeypatch.setattr(
        agi_distributor_module.cleanup_support,
        "remove_dir_forcefully",
        lambda *args, **kwargs: calls.append(("remove_dir_forcefully", args, kwargs)),
    )
    monkeypatch.setattr(
        agi_distributor_module.cleanup_support,
        "clean_dirs_local",
        lambda *args, **kwargs: calls.append(("clean_dirs_local", args, kwargs)),
    )
    monkeypatch.setattr(
        agi_distributor_module.deployment_orchestration_support,
        "reset_deploy_state",
        lambda agi_cls: calls.append(("reset_deploy_state", agi_cls)),
    )
    monkeypatch.setattr(
        agi_distributor_module.runtime_misc_support,
        "hardware_supports_rapids",
        lambda: calls.append(("hardware_supports_rapids",)) or True,
    )
    monkeypatch.setattr(
        agi_distributor_module.runtime_misc_support,
        "should_install_pip",
        lambda: calls.append(("should_install_pip",)) or False,
    )
    monkeypatch.setattr(
        agi_distributor_module.runtime_misc_support,
        "format_elapsed",
        lambda seconds: calls.append(("format_elapsed", seconds)) or f"{seconds}s",
    )
    monkeypatch.setattr(
        agi_distributor_module.deployment_prepare_support,
        "venv_todo",
        lambda agi_cls, list_ip, log=None: calls.append(("venv_todo", agi_cls, list_ip, log)),
    )
    monkeypatch.setattr(
        agi_distributor_module.runtime_distribution_support,
        "dask_env_prefix",
        lambda agi_cls: calls.append(("dask_env_prefix", agi_cls)) or "DASK=1 ",
    )
    monkeypatch.setattr(
        agi_distributor_module.runtime_distribution_support,
        "exec_bg",
        lambda agi_cls, cmd, cwd: calls.append(("exec_bg", agi_cls, cmd, cwd)),
    )

    queue_root = tmp_path / "queue"
    assert AGI._service_queue_paths(queue_root) == {"root": queue_root}
    assert AGI.find_free_port() == 4321
    assert AGI._get_scheduler("127.0.0.1") == ("127.0.0.1", 9999)
    assert AGI._get_stdout(str, 1) == ("out", "res")
    AGI._read_stderr("stream")
    AGI._remove_dir_forcefully(tmp_path / "target")
    AGI._clean_dirs_local()
    AGI._reset_deploy_state()
    assert AGI._hardware_supports_rapids() is True
    assert AGI._should_install_pip() is False
    assert AGI._format_elapsed(2.5) == "2.5s"
    AGI._venv_todo({"10.0.0.1"})
    assert AGI._dask_env_prefix() == "DASK=1 "
    AGI._train_capacity(Path("/tmp/train"))
    AGI._update_capacity()
    AGI._exec_bg("echo hi", "/tmp")

    names = [entry[0] for entry in calls]
    assert "service_queue_paths" in names
    assert "find_free_port" in names
    assert "get_scheduler" in names
    assert "read_stderr" in names
    assert "remove_dir_forcefully" in names
    assert "clean_dirs_local" in names
    assert "reset_deploy_state" in names
    assert "hardware_supports_rapids" in names
    assert "should_install_pip" in names
    assert "format_elapsed" in names
    assert "venv_todo" in names
    assert "dask_env_prefix" in names
    assert "train_capacity" in names
    assert "update_capacity" in names
    assert "exec_bg" in names


@pytest.mark.asyncio
async def test_agi_async_wrapper_surface_delegates(monkeypatch, tmp_path):
    calls = []

    async def _record(name, *args, **kwargs):
        calls.append((name, args, kwargs))
        return name

    monkeypatch.setattr(
        agi_distributor_module.capacity_support,
        "benchmark",
        lambda *args, **kwargs: _record("benchmark", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.capacity_support,
        "benchmark_dask_modes",
        lambda *args, **kwargs: _record("benchmark_dask_modes", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.transport_support,
        "send_file",
        lambda *args, **kwargs: _record("send_file", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.transport_support,
        "send_files",
        lambda *args, **kwargs: _record("send_files", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.cleanup_support,
        "kill_processes",
        lambda *args, **kwargs: _record("kill_processes", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.cleanup_support,
        "wait_for_port_release",
        lambda *args, **kwargs: _record("wait_for_port_release", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.cleanup_support,
        "clean_dirs",
        lambda *args, **kwargs: _record("clean_dirs", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.deployment_orchestration_support,
        "clean_nodes",
        lambda *args, **kwargs: _record("clean_nodes", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.deployment_orchestration_support,
        "clean_remote_procs",
        lambda *args, **kwargs: _record("clean_remote_procs", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.deployment_orchestration_support,
        "clean_remote_dirs",
        lambda *args, **kwargs: _record("clean_remote_dirs", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.deployment_prepare_support,
        "prepare_local_env",
        lambda *args, **kwargs: _record("prepare_local_env", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.deployment_prepare_support,
        "prepare_cluster_env",
        lambda *args, **kwargs: _record("prepare_cluster_env", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.deployment_orchestration_support,
        "deploy_application",
        lambda *args, **kwargs: _record("deploy_application", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.deployment_local_support,
        "deploy_local_worker",
        lambda *args, **kwargs: _record("deploy_local_worker", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.deployment_remote_support,
        "deploy_remote_worker",
        lambda *args, **kwargs: _record("deploy_remote_worker", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.deployment_prepare_support,
        "uninstall_modules",
        lambda *args, **kwargs: _record("uninstall_modules", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.entrypoint_support,
        "update",
        lambda *args, **kwargs: _record("update", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.entrypoint_support,
        "get_distrib",
        lambda *args, **kwargs: _record("get_distrib", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.entrypoint_support,
        "distribute",
        lambda *args, **kwargs: _record("distribute_alias", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.entrypoint_support,
        "start_scheduler",
        lambda *args, **kwargs: _record("start_scheduler", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.entrypoint_support,
        "connect_scheduler_with_retry",
        lambda *args, **kwargs: _record("connect_scheduler_with_retry", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.entrypoint_support,
        "detect_export_cmd",
        lambda *args, **kwargs: _record("detect_export_cmd", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.runtime_distribution_support,
        "start",
        lambda *args, **kwargs: _record("runtime_start", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.runtime_distribution_support,
        "sync",
        lambda *args, **kwargs: _record("runtime_sync", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.deployment_build_support,
        "build_lib_local",
        lambda *args, **kwargs: _record("build_lib_local", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.deployment_build_support,
        "build_lib_remote",
        lambda *args, **kwargs: _record("build_lib_remote", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.runtime_distribution_support,
        "run_local",
        lambda *args, **kwargs: _record("run_local", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.runtime_distribution_support,
        "distribute",
        lambda *args, **kwargs: _record("runtime_distribute", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.runtime_distribution_support,
        "main",
        lambda *args, **kwargs: _record("runtime_main", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.runtime_distribution_support,
        "stop",
        lambda *args, **kwargs: _record("runtime_stop", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.capacity_support,
        "calibration",
        lambda *args, **kwargs: _record("calibration", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.transport_support,
        "exec_ssh",
        lambda *args, **kwargs: _record("exec_ssh", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.transport_support,
        "exec_ssh_async",
        lambda *args, **kwargs: _record("exec_ssh_async", *args, **kwargs),
    )
    monkeypatch.setattr(
        agi_distributor_module.transport_support,
        "close_all_connections",
        lambda *args, **kwargs: _record("close_all_connections", *args, **kwargs),
    )

    env = SimpleNamespace()
    await AGI._benchmark(env, scheduler="127.0.0.1", workers={"127.0.0.1": 1}, mode_range=[1, 2])
    await AGI._benchmark_dask_modes(env, "127.0.0.1", {"127.0.0.1": 1}, [1, 2], AGI.RAPIDS_MODE, {})
    await AGI.send_file(env, "127.0.0.1", Path("a"), Path("b"))
    await AGI.send_files(env, "127.0.0.1", [Path("a")], Path("remote"))
    await AGI._kill("127.0.0.1")
    await AGI._wait_for_port_release("127.0.0.1", 8786)
    await AGI._clean_dirs("127.0.0.1")
    await AGI._clean_nodes("127.0.0.1")
    await AGI._clean_remote_procs({"10.0.0.2"})
    await AGI._clean_remote_dirs({"10.0.0.2"})
    await AGI._prepare_local_env()
    await AGI._prepare_cluster_env("127.0.0.1")
    await AGI._deploy_application("127.0.0.1")
    await AGI._deploy_local_worker(Path("src"), Path("wenv"), "--worker")
    await AGI._deploy_remote_worker("10.0.0.2", env, Path("wenv"), "--worker")
    await AGI._uninstall_modules()
    await AGI.update(env=env)
    await AGI.get_distrib(env=env)
    await AGI.distribute(env=env)
    await AGI._start_scheduler("127.0.0.1")
    await AGI._connect_scheduler_with_retry("tcp://127.0.0.1:8786", timeout=1.0)
    await AGI._detect_export_cmd("127.0.0.1")
    await AGI._start("127.0.0.1")
    await AGI._sync()
    await AGI._build_lib_local()
    await AGI._build_lib_remote()
    await AGI._run()
    await AGI._distribute()
    await AGI._main("127.0.0.1")
    await AGI._stop()
    await AGI._calibration()
    await AGI.exec_ssh("127.0.0.1", "echo hi")
    await AGI.exec_ssh_async("127.0.0.1", "echo hi")
    await AGI._close_all_connections()

    names = [entry[0] for entry in calls]
    assert "benchmark" in names
    assert "benchmark_dask_modes" in names
    assert "send_file" in names
    assert "send_files" in names
    assert "kill_processes" in names
    assert "wait_for_port_release" in names
    assert "clean_dirs" in names
    assert "clean_nodes" in names
    assert "clean_remote_procs" in names
    assert "clean_remote_dirs" in names
    assert "prepare_local_env" in names
    assert "prepare_cluster_env" in names
    assert "deploy_application" in names
    assert "deploy_local_worker" in names
    assert "deploy_remote_worker" in names
    assert "uninstall_modules" in names
    assert "update" in names
    assert "get_distrib" in names
    assert "distribute_alias" in names
    assert "start_scheduler" in names
    assert "connect_scheduler_with_retry" in names
    assert "detect_export_cmd" in names
    assert "runtime_start" in names
    assert "runtime_sync" in names
    assert "build_lib_local" in names
    assert "build_lib_remote" in names
    assert "run_local" in names
    assert "runtime_distribute" in names
    assert "runtime_main" in names
    assert "runtime_stop" in names
    assert "calibration" in names
    assert "exec_ssh" in names
    assert "exec_ssh_async" in names
    assert "close_all_connections" in names


@pytest.mark.asyncio
async def test_agi_get_ssh_connection_wrapper_delegates(monkeypatch):
    sentinel = object()
    calls = []

    @asynccontextmanager
    async def _fake_get_ssh_connection(*args, **kwargs):
        calls.append((args, kwargs))
        yield sentinel

    monkeypatch.setattr(
        agi_distributor_module.transport_support,
        "get_ssh_connection",
        _fake_get_ssh_connection,
    )

    async with AGI.get_ssh_connection("127.0.0.1", timeout_sec=7) as conn:
        assert conn is sentinel

    assert calls


def test_agi_get_default_local_ip_wrapper_delegates(monkeypatch):
    monkeypatch.setattr(
        agi_distributor_module.scheduler_io_support,
        "get_default_local_ip",
        lambda **_kwargs: "127.0.0.9",
    )

    assert AGI.get_default_local_ip() == "127.0.0.9"
