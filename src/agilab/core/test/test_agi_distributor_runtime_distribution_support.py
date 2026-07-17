from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import psutil
import pytest

from agi_cluster.agi_distributor import (
    AGI,
    background_jobs_support,
    runtime_distribution_support,
    uv_source_support,
)
from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher


@pytest.fixture(autouse=True)
def _reset_agi_runtime_distribution_state():
    fields = [
        "env",
        "_mode",
        "_mode_auto",
        "_workers",
        "_args",
        "_worker_args",
        "_dask_client",
        "_dask_workers",
        "_worker_init_error",
        "_scheduler",
        "_jobs",
        "verbose",
        "debug",
        "_TIMEOUT",
        "_work_plan",
        "_work_plan_metadata",
        "_capacity",
        "_phase_timings",
        "_dask_log_level",
        "_rapids_enabled",
        "_workers_data_path",
        "_worker_launch_tasks",
        "_scheduler_launch_tasks",
        "_startup_in_progress",
        "_service_cleanup_unproven",
        "_runtime_cleanup_task",
        "_runtime_cleanup_phase",
        "_runtime_shutdown_client",
    ]
    snapshot = {field: getattr(AGI, field, None) for field in fields}
    try:
        AGI.env = None
        AGI._mode = 0
        AGI._mode_auto = False
        AGI._workers = {}
        AGI._args = {}
        AGI._worker_args = None
        AGI._dask_client = None
        AGI._dask_workers = None
        AGI._worker_init_error = False
        AGI._scheduler = None
        AGI._jobs = None
        AGI.verbose = 0
        AGI.debug = False
        AGI._TIMEOUT = 10
        AGI._work_plan = None
        AGI._work_plan_metadata = None
        AGI._capacity = None
        AGI._phase_timings = []
        AGI._dask_log_level = "critical"
        AGI._rapids_enabled = False
        AGI._workers_data_path = None
        AGI._worker_launch_tasks = set()
        AGI._scheduler_launch_tasks = set()
        AGI._startup_in_progress = False
        AGI._service_cleanup_unproven = False
        AGI._runtime_cleanup_task = None
        AGI._runtime_cleanup_phase = None
        AGI._runtime_shutdown_client = None
        yield
    finally:
        cleanup_task = getattr(AGI, "_runtime_cleanup_task", None)
        if isinstance(cleanup_task, asyncio.Task) and not cleanup_task.done():
            cleanup_task.cancel()
        for field, value in snapshot.items():
            setattr(AGI, field, value)


def test_dask_env_prefix_and_scale_cluster_trim_workers():
    AGI._dask_log_level = ""
    assert runtime_distribution_support.dask_env_prefix(AGI) == ""
    AGI._dask_log_level = "INFO"
    assert "DASK_DISTRIBUTED__LOGGING__distributed=INFO" in runtime_distribution_support.dask_env_prefix(AGI)

    AGI._workers = {"10.0.0.1": 1}
    AGI._dask_workers = ["10.0.0.1:1001", "10.0.0.1:1002", "10.0.0.2:1001"]
    runtime_distribution_support.scale_cluster(AGI)
    assert AGI._dask_workers == ["10.0.0.1:1001"]


def test_sanitize_worker_upload_artifacts_removes_top_level_ui_modules(tmp_path):
    wenv_abs = tmp_path / "worker_env"
    src_dir = wenv_abs / "src"
    dist_dir = wenv_abs / "dist"
    pycache_dir = src_dir / "__pycache__"
    package_dir = src_dir / "demo_worker"
    pycache_dir.mkdir(parents=True)
    package_dir.mkdir()
    dist_dir.mkdir()
    (src_dir / "app_args_form.py").write_text("import streamlit\n", encoding="utf-8")
    (src_dir / "demo_args_form.py").write_text("import streamlit\n", encoding="utf-8")
    (pycache_dir / "app_args_form.cpython-313.pyc").write_bytes(b"")
    (package_dir / "app_args_form.py").write_text("keep = True\n", encoding="utf-8")
    egg_file = dist_dir / "demo-0.1.0.egg"
    with ZipFile(egg_file, "w") as zf:
        zf.writestr("app_args_form.py", "import streamlit\n")
        zf.writestr("demo_args_form.py", "import streamlit\n")
        zf.writestr("__pycache__/app_args_form.cpython-313.pyc", b"")
        zf.writestr("demo_worker/__init__.py", "")
        zf.writestr("demo_worker/app_args_form.py", "keep = True\n")
        zf.writestr("EGG-INFO/top_level.txt", "app_args_form\ndemo_args_form\ndemo_worker\n")

    removed = runtime_distribution_support.sanitize_worker_upload_artifacts(wenv_abs)

    assert "app_args_form.py" in removed
    assert "demo_args_form.py" in removed
    assert "__pycache__/app_args_form.cpython-313.pyc" in removed
    assert not (src_dir / "app_args_form.py").exists()
    assert not (src_dir / "demo_args_form.py").exists()
    assert not (pycache_dir / "app_args_form.cpython-313.pyc").exists()
    assert (package_dir / "app_args_form.py").exists()
    with ZipFile(egg_file) as zf:
        names = zf.namelist()
        top_level = zf.read("EGG-INFO/top_level.txt").decode("utf-8")
    assert "app_args_form.py" not in names
    assert "demo_args_form.py" not in names
    assert "__pycache__/app_args_form.cpython-313.pyc" not in names
    assert "demo_worker/app_args_form.py" in names
    assert top_level == "demo_worker\n"


def test_runtime_distribution_edge_helpers_cover_fallback_branches(tmp_path):
    assert runtime_distribution_support._sync_poll_delay(-3) == 0.2
    assert runtime_distribution_support._sync_poll_delay(99) == 3.0
    assert runtime_distribution_support._remote_prefix("source ~/.profile") == "source ~/.profile "
    assert runtime_distribution_support._remote_prefix("") == ""

    agi = SimpleNamespace(_phase_timings="not-a-list")
    runtime_distribution_support._record_phase_timing(agi, "start", 1.23456789)
    assert agi._phase_timings == [{"phase": "start", "seconds": 1.234568}]

    src_dir = tmp_path / "src"
    pycache_dir = src_dir / "__pycache__"
    pycache_dir.mkdir(parents=True)
    (pycache_dir / "demo_args_form.cpython-313.pyc").write_bytes(b"")
    (pycache_dir / "keep.cpython-313.pyc").write_bytes(b"")
    log = SimpleNamespace(messages=[], info=lambda *args: log.messages.append(args))
    removed = runtime_distribution_support._clean_top_level_ui_source_artifacts(src_dir, log=log)
    assert removed == [pycache_dir / "demo_args_form.cpython-313.pyc"]
    assert pycache_dir.exists()
    assert log.messages

    bad_egg = tmp_path / "bad.egg"
    bad_egg.write_text("not a zip", encoding="utf-8")
    assert runtime_distribution_support._sanitize_worker_upload_egg(bad_egg) == []

    clean_egg = tmp_path / "clean.egg"
    with ZipFile(clean_egg, "w") as zf:
        zf.writestr("demo_worker/__init__.py", "")
        zf.writestr("EGG-INFO/top_level.txt", "demo_worker\n")
    assert runtime_distribution_support._sanitize_worker_upload_egg(clean_egg) == []
    assert not (tmp_path / ".clean.egg.tmp").exists()

    assert runtime_distribution_support._manager_apps_path(SimpleNamespace()) is None
    assert runtime_distribution_support._manager_apps_path(
        SimpleNamespace(active_app=tmp_path / "apps" / "demo_project")
    ) == tmp_path / "apps"
    assert (
        runtime_distribution_support._manager_app_name(SimpleNamespace(target="demo"))
        == "demo_project"
    )
    assert (
        runtime_distribution_support._manager_app_name(SimpleNamespace(target_worker="demo_worker"))
        == "demo_project"
    )
    assert (
        runtime_distribution_support._manager_app_name(SimpleNamespace())
        == "flight_telemetry_project"
    )

    calls = []

    class _Jobs:
        def new(self, cmd, *, cwd, env=None):
            calls.append((cmd, cwd, env))
            return SimpleNamespace(num=7)

        def result(self, job_id):
            return job_id == 7

    runtime_distribution_support.exec_bg(
        SimpleNamespace(_jobs=_Jobs()),
        ["python", "-m", "demo"],
        str(tmp_path),
        env={"PATH": "/tmp/bin"},
    )
    assert calls == [(["python", "-m", "demo"], str(tmp_path), {"PATH": "/tmp/bin"})]


def test_local_dask_worker_command_uses_direct_venv_executable_when_available(tmp_path):
    wenv_abs = tmp_path / "wenv"
    dask_exe = wenv_abs / ".venv" / ("Scripts/dask.exe" if os.name == "nt" else "bin/dask")
    dask_exe.parent.mkdir(parents=True, exist_ok=True)
    dask_exe.write_text("", encoding="utf-8")

    command = runtime_distribution_support._local_dask_worker_command(
        "uv",
        wenv_abs,
        "127.0.0.1:8786",
        "worker.pid",
    )

    assert command[:3] == [str(dask_exe), "worker", "tcp://127.0.0.1:8786"]
    assert "--no-sync" not in command


def test_local_dask_worker_command_can_target_windows_layout(tmp_path):
    wenv_abs = tmp_path / "wenv"
    dask_exe = wenv_abs / ".venv" / "Scripts" / "dask.exe"
    dask_exe.parent.mkdir(parents=True, exist_ok=True)
    dask_exe.write_text("", encoding="utf-8")

    command = runtime_distribution_support._local_dask_worker_command(
        "uv",
        wenv_abs,
        "127.0.0.1:8786",
        "worker.pid",
        os_name="nt",
    )

    assert command[:3] == [str(dask_exe), "worker", "tcp://127.0.0.1:8786"]
    assert "--no-sync" not in command


def test_local_dask_worker_command_pins_worker_port_range(tmp_path):
    command = runtime_distribution_support._local_dask_worker_command(
        "uv",
        tmp_path / "wenv",
        "127.0.0.1:8786",
        "worker.pid",
        worker_port="9000:9100",
    )

    port_idx = command.index("--worker-port")
    assert command[port_idx + 1] == "9000:9100"


def test_remote_dask_worker_command_pins_worker_port_range():
    command = runtime_distribution_support._remote_dask_worker_command(
        cmd_prefix="",
        dask_env="",
        uv_cmd="uv",
        wenv_rel="wenv/app_worker",
        scheduler="172.16.40.2:8786",
        pid_file="worker.pid",
        worker_port="9000:9100",
    )

    assert "--worker-port 9000:9100" in command
    assert command.index("--worker-port") < command.index("--pid-file")


def test_remote_dask_worker_command_omits_worker_port_by_default():
    command = runtime_distribution_support._remote_dask_worker_command(
        cmd_prefix="",
        dask_env="",
        uv_cmd="uv",
        wenv_rel="wenv/app_worker",
        scheduler="172.16.40.2:8786",
        pid_file="worker.pid",
    )

    assert "--worker-port" not in command


@pytest.mark.parametrize("raw", ["9000", "9000:9100", " 9000 : 9100 "])
def test_worker_port_range_accepts_valid_values(raw):
    env = SimpleNamespace(envars={"AGILAB_DASK_WORKER_PORT_RANGE": raw})
    assert runtime_distribution_support._worker_port_range(env) == raw.replace(" ", "")


@pytest.mark.parametrize("raw", ["abc", "9100:9000", "0", "70000", "1:2:3"])
def test_worker_port_range_rejects_invalid_values(raw):
    env = SimpleNamespace(envars={"AGILAB_DASK_WORKER_PORT_RANGE": raw})
    with pytest.raises(ValueError):
        runtime_distribution_support._worker_port_range(env)


def test_worker_port_range_defaults_to_pinned_range(monkeypatch):
    monkeypatch.delenv("AGILAB_DASK_WORKER_PORT_RANGE", raising=False)
    monkeypatch.delenv("DASK_WORKER_PORT_RANGE", raising=False)
    assert (
        runtime_distribution_support._worker_port_range(SimpleNamespace(envars={}))
        == runtime_distribution_support.DEFAULT_WORKER_PORT_RANGE
    )


def test_worker_port_range_ephemeral_disables_pinning():
    env = SimpleNamespace(envars={"AGILAB_DASK_WORKER_PORT_RANGE": "ephemeral"})
    assert runtime_distribution_support._worker_port_range(env) is None


@pytest.mark.asyncio
async def test_start_acquires_remote_target_leases_before_scheduler_bootstrap():
    events = []

    async def _acquire(ip):
        events.append(f"lease:{ip}")

    async def _start_scheduler(_scheduler):
        events.append("scheduler")
        return False

    agi_cls = SimpleNamespace(
        env=SimpleNamespace(is_local=lambda ip: ip == "127.0.0.1"),
        _workers={"10.0.0.3": 1, "127.0.0.1": 1},
        _get_scheduler=lambda _scheduler: ("10.0.0.2", 8786),
        _lifecycle_call_token="a" * 32,
        _dask_log_level=None,
        _acquire_remote_target_lease=_acquire,
        _start_scheduler=_start_scheduler,
    )

    started = await runtime_distribution_support.start(
        agi_cls,
        "10.0.0.2",
        set_env_var_fn=lambda *_args, **_kwargs: None,
    )

    assert started is False
    assert events == ["lease:10.0.0.2", "lease:10.0.0.3", "scheduler"]


@pytest.mark.asyncio
async def test_start_launches_workers_and_uploads_eggs(monkeypatch, tmp_path):
    wenv_abs = tmp_path / "worker_env"
    (wenv_abs / "dist").mkdir(parents=True, exist_ok=True)
    (wenv_abs / "dist" / "z-demo.egg").write_text("x", encoding="utf-8")
    (wenv_abs / "dist" / "a-demo.egg").write_text("x", encoding="utf-8")

    AGI.env = SimpleNamespace(
        is_local=lambda ip: ip == "127.0.0.1",
        envars={},
        uv="uv",
        wenv_abs=wenv_abs,
        wenv_rel=Path("worker_env"),
    )
    AGI._mode = AGI.DASK_MODE
    AGI._mode_auto = False
    AGI._workers = {"127.0.0.1": 1, "10.0.0.2": 1}
    AGI._scheduler = "127.0.0.1:8786"
    AGI._worker_init_error = False
    calls = {"bg": [], "remote": [], "uploaded": []}

    class _Client:
        def upload_file(self, path):
            calls["uploaded"].append(path)

    async def _fake_start_scheduler(_scheduler):
        return True

    async def _fake_detect(_ip):
        return 'export PATH="$HOME/.local/bin:$PATH"; '

    async def _fake_sync(timeout=60):
        return None

    async def _fake_build_remote():
        return None

    def _fake_exec_ssh_async(ip, cmd):
        calls["remote"].append((ip, cmd))
        return None

    def _fake_create_task(coro):
        return None

    monkeypatch.setattr(AGI, "_dask_client", _Client())
    monkeypatch.setattr(AGI, "_start_scheduler", staticmethod(_fake_start_scheduler))
    monkeypatch.setattr(AGI, "_detect_export_cmd", staticmethod(_fake_detect))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_fake_sync))
    monkeypatch.setattr(AGI, "_build_lib_remote", staticmethod(_fake_build_remote))
    monkeypatch.setattr(AGI, "exec_ssh_async", staticmethod(_fake_exec_ssh_async))
    monkeypatch.setattr(
        AGI,
        "_exec_bg",
        staticmethod(lambda cmd, cwd, **kwargs: calls["bg"].append((cmd, cwd, kwargs))),
    )

    await runtime_distribution_support.start(
        AGI,
        "127.0.0.1",
        set_env_var_fn=lambda *_args, **_kwargs: None,
        create_task_fn=_fake_create_task,
    )

    assert calls["bg"][0][0][:5] == ["uv", "--project", str(wenv_abs), "run", "--no-sync"]
    assert calls["bg"][0][2]["env"]["PATH"].startswith(str(Path.home() / ".local" / "bin"))

    assert calls["bg"]
    assert any(ip == "10.0.0.2" for ip, _ in calls["remote"])
    assert [Path(path).name for path in calls["uploaded"]] == ["a-demo.egg", "z-demo.egg"]


@pytest.mark.asyncio
async def test_ensure_remote_cluster_shares_remounts_remote_workers_only():
    calls = []
    agi = SimpleNamespace(
        env=SimpleNamespace(is_local=lambda ip: ip in {"127.0.0.1", "192.168.20.111"}),
        _workers={"192.168.20.111": 1, "192.168.20.15": 1},
        _workers_data_path="clustershare/agi",
    )

    async def _fake_prepare(agi_cls, ip, env, remote_share, *, log):
        calls.append((agi_cls, ip, env, remote_share, log))

    mounted = await runtime_distribution_support.ensure_remote_cluster_shares(
        agi,
        prepare_remote_cluster_share_fn=_fake_prepare,
        log="logger",
    )

    assert mounted == ["192.168.20.15"]
    assert [(ip, remote_share) for _, ip, _, remote_share, _ in calls] == [
        ("192.168.20.15", "clustershare/agi")
    ]


@pytest.mark.asyncio
async def test_start_remounts_remote_cluster_share_before_worker_processes(monkeypatch, tmp_path):
    wenv_abs = tmp_path / "worker_env"
    (wenv_abs / "dist").mkdir(parents=True, exist_ok=True)
    (wenv_abs / "dist" / "demo.egg").write_text("x", encoding="utf-8")
    events: list[str] = []

    AGI.env = SimpleNamespace(
        is_local=lambda ip: ip == "192.168.20.111",
        envars={},
        uv="uv",
        wenv_abs=wenv_abs,
        wenv_rel=Path("worker_env"),
    )
    AGI._mode = AGI.DASK_MODE
    AGI._mode_auto = False
    AGI._workers = {"192.168.20.111": 1, "192.168.20.15": 1}
    AGI._workers_data_path = "clustershare/agi"
    AGI._scheduler = "192.168.20.111:8786"
    AGI._scheduler_ip = "192.168.20.111"
    AGI._worker_init_error = False

    class _Client:
        def upload_file(self, _path):
            events.append("upload")

    async def _fake_start_scheduler(_scheduler):
        events.append("scheduler")
        return True

    async def _fake_detect(_ip):
        return 'export PATH="$HOME/.local/bin:$PATH"; '

    async def _fake_sync(timeout=60):
        events.append("sync")
        return None

    async def _fake_build_remote():
        return None

    def _fake_exec_ssh_async(ip, _cmd):
        events.append(f"worker:{ip}")
        return None

    async def _fake_prepare(_agi_cls, ip, _env, remote_share, *, log):
        del log
        events.append(f"mount:{ip}:{remote_share}")

    monkeypatch.setattr(AGI, "_dask_client", _Client())
    monkeypatch.setattr(AGI, "_start_scheduler", staticmethod(_fake_start_scheduler))
    monkeypatch.setattr(AGI, "_detect_export_cmd", staticmethod(_fake_detect))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_fake_sync))
    monkeypatch.setattr(AGI, "_build_lib_remote", staticmethod(_fake_build_remote))
    monkeypatch.setattr(AGI, "exec_ssh_async", staticmethod(_fake_exec_ssh_async))
    monkeypatch.setattr(
        AGI,
        "_exec_bg",
        staticmethod(lambda _cmd, _cwd, **_kwargs: events.append("worker:192.168.20.111")),
    )
    monkeypatch.setattr(
        runtime_distribution_support.deployment_remote_support,
        "_prepare_remote_cluster_share",
        _fake_prepare,
    )

    await runtime_distribution_support.start(
        AGI,
        "192.168.20.111",
        set_env_var_fn=lambda *_args, **_kwargs: None,
        create_task_fn=lambda _value: None,
    )

    assert events.index("mount:192.168.20.15:clustershare/agi") < events.index("worker:192.168.20.15")


@pytest.mark.asyncio
async def test_start_propagates_unexpected_detect_export_bug(monkeypatch, tmp_path):
    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)

    AGI.env = SimpleNamespace(
        is_local=lambda _ip: False,
        envars={},
        uv="uv",
        wenv_abs=wenv_abs,
        wenv_rel=Path("worker_env"),
    )
    AGI._mode = AGI.DASK_MODE
    AGI._mode_auto = False
    AGI._workers = {"10.0.0.2": 1}
    AGI._scheduler = "127.0.0.1:8786"
    AGI._worker_init_error = False

    class _Client:
        def upload_file(self, _path):
            return None

    async def _fake_start_scheduler(_scheduler):
        return True

    async def _fake_detect(_ip):
        raise ValueError("unexpected export detection bug")

    monkeypatch.setattr(AGI, "_dask_client", _Client())
    monkeypatch.setattr(AGI, "_start_scheduler", staticmethod(_fake_start_scheduler))
    monkeypatch.setattr(AGI, "_detect_export_cmd", staticmethod(_fake_detect))

    with pytest.raises(ValueError, match="unexpected export detection bug"):
        await runtime_distribution_support.start(
            AGI,
            "127.0.0.1",
            set_env_var_fn=lambda *_args, **_kwargs: None,
            create_task_fn=lambda _coro: None,
        )


@pytest.mark.asyncio
async def test_stop_retires_workers_and_shutdown(monkeypatch):
    class _Client:
        def __init__(self):
            self.info_calls = 0
            self.retire_calls = 0
            self.shutdown_calls = 0

        async def scheduler_info(self):
            self.info_calls += 1
            if self.info_calls == 1:
                return {"workers": {"tcp://127.0.0.1:8787": {}}}
            return {"workers": {}}

        async def retire_workers(self, workers, close_workers=True, remove=True):
            self.retire_calls += 1

        async def shutdown(self):
            self.shutdown_calls += 1

    client = _Client()
    AGI._dask_client = client
    AGI._mode_auto = False
    AGI._mode = AGI.DASK_MODE
    AGI._TIMEOUT = 3
    closed = {"count": 0}

    async def _fake_close_all():
        closed["count"] += 1

    async def _fake_sleep(_delay):
        return None

    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_fake_close_all))

    await runtime_distribution_support.stop(AGI, sleep_fn=_fake_sleep)

    assert client.retire_calls >= 1
    assert client.shutdown_calls == 1
    assert AGI._dask_client is None
    assert closed["count"] == 1


@pytest.mark.asyncio
async def test_stop_supports_sync_scheduler_shutdown_calls(monkeypatch):
    class _Client:
        def __init__(self):
            self.info_calls = 0
            self.retire_calls = 0
            self.shutdown_calls = 0

        def scheduler_info(self):
            self.info_calls += 1
            if self.info_calls == 1:
                return {"workers": {"tcp://127.0.0.1:8787": {}}}
            return {"workers": {}}

        def retire_workers(self, workers, close_workers=True, remove=True):
            self.retire_calls += 1
            return {"retired": workers}

        def shutdown(self):
            self.shutdown_calls += 1
            return {"status": "stopped"}

    client = _Client()
    AGI._dask_client = client
    AGI._mode_auto = False
    AGI._mode = AGI.DASK_MODE
    AGI._TIMEOUT = 3
    closed = {"count": 0}

    async def _fake_close_all():
        closed["count"] += 1

    async def _fake_sleep(_delay):
        return None

    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_fake_close_all))

    await runtime_distribution_support.stop(AGI, sleep_fn=_fake_sleep)

    assert client.retire_calls >= 1
    assert client.shutdown_calls == 1
    assert AGI._dask_client is None
    assert closed["count"] == 1


@pytest.mark.asyncio
async def test_stop_retry_does_not_query_a_proven_closed_client(monkeypatch):
    class _Client:
        def __init__(self):
            self.closed = False
            self.info_calls = 0
            self.shutdown_calls = 0

        async def scheduler_info(self):
            self.info_calls += 1
            if self.closed:
                raise RuntimeError("closed client must not be queried")
            return {"workers": {}}

        async def shutdown(self):
            self.shutdown_calls += 1
            self.closed = True

    client = _Client()
    AGI._dask_client = client
    AGI._mode_auto = False
    closed_connections = {"count": 0}

    async def _fake_close_all():
        closed_connections["count"] += 1

    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_fake_close_all))

    await runtime_distribution_support.stop(AGI)
    # A retained lifecycle lease may call runtime stop again when state-file
    # cleanup failed after the first successful runtime shutdown.
    await runtime_distribution_support.stop(AGI)

    assert client.info_calls == 1
    assert client.shutdown_calls == 1
    assert closed_connections["count"] == 2
    assert AGI._dask_client is None


@pytest.mark.asyncio
async def test_stop_retry_reuses_client_shutdown_proof_until_process_cleanup_succeeds(
    monkeypatch,
):
    class _Client:
        def __init__(self):
            self.closed = False
            self.info_calls = 0
            self.shutdown_calls = 0

        async def scheduler_info(self):
            self.info_calls += 1
            if self.closed:
                raise RuntimeError("closed client must not be queried")
            return {"workers": {}}

        async def shutdown(self):
            self.shutdown_calls += 1
            self.closed = True

    process_cleanup_calls = {"count": 0}

    async def _terminate_jobs(_agi_cls, *, log):
        process_cleanup_calls["count"] += 1
        if process_cleanup_calls["count"] == 1:
            raise runtime_distribution_support.RuntimeCleanupRequiredError(
                "owned child is still exiting"
            )

    async def _fake_close_all():
        return None

    client = _Client()
    AGI._dask_client = client
    AGI._mode_auto = False
    monkeypatch.setattr(
        runtime_distribution_support,
        "_terminate_owned_background_jobs",
        _terminate_jobs,
    )
    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_fake_close_all))

    with pytest.raises(
        runtime_distribution_support.RuntimeCleanupRequiredError,
        match="owned child is still exiting",
    ):
        await runtime_distribution_support.stop(AGI)

    assert AGI._dask_client is client
    assert AGI._runtime_shutdown_client is client

    await runtime_distribution_support.stop(AGI)

    assert client.info_calls == 1
    assert client.shutdown_calls == 1
    assert process_cleanup_calls["count"] == 2
    assert AGI._dask_client is None
    assert AGI._runtime_shutdown_client is None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["scheduler_info", "retire_workers", "shutdown"])
async def test_stop_marks_operational_cleanup_errors_unproven(monkeypatch, phase):
    class _Client:
        def __init__(self):
            self.shutdown_calls = 0

        async def scheduler_info(self):
            if phase == "scheduler_info":
                raise RuntimeError("expected shutdown failure")
            if phase == "retire_workers":
                return {"workers": {"tcp://127.0.0.1:8787": {}}}
            return {"workers": {}}

        async def retire_workers(self, workers, close_workers=True, remove=True):
            if phase == "retire_workers":
                raise RuntimeError("expected shutdown failure")
            return None

        async def shutdown(self):
            self.shutdown_calls += 1
            if phase == "shutdown":
                raise RuntimeError("expected shutdown failure")

    AGI._dask_client = _Client()
    AGI._mode_auto = False
    AGI._mode = AGI.DASK_MODE
    AGI._TIMEOUT = 2
    closed = {"count": 0}

    async def _fake_close_all():
        closed["count"] += 1

    async def _fake_sleep(_delay):
        return None

    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_fake_close_all))

    with pytest.raises(
        runtime_distribution_support.RuntimeCleanupRequiredError,
        match="cleanup remains unproven",
    ):
        await runtime_distribution_support.stop(AGI, sleep_fn=_fake_sleep)

    assert closed["count"] == 1
    assert AGI._service_cleanup_unproven is True


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["scheduler_info", "retire_workers", "shutdown"])
async def test_stop_propagates_unexpected_programmer_bug(monkeypatch, phase):
    class _Client:
        async def scheduler_info(self):
            if phase == "scheduler_info":
                raise ValueError("unexpected shutdown bug")
            if phase == "retire_workers":
                return {"workers": {"tcp://127.0.0.1:8787": {}}}
            return {"workers": {}}

        async def retire_workers(self, workers, close_workers=True, remove=True):
            if phase == "retire_workers":
                raise ValueError("unexpected shutdown bug")
            return None

        async def shutdown(self):
            if phase == "shutdown":
                raise ValueError("unexpected shutdown bug")

    AGI._dask_client = _Client()
    AGI._mode_auto = False
    AGI._mode = AGI.DASK_MODE
    AGI._TIMEOUT = 2
    closed = {"count": 0}

    async def _fake_close_all():
        closed["count"] += 1

    async def _fake_sleep(_delay):
        return None

    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_fake_close_all))

    with pytest.raises(ValueError, match="unexpected shutdown bug"):
        await runtime_distribution_support.stop(AGI, sleep_fn=_fake_sleep)


@pytest.mark.asyncio
async def test_run_local_covers_debug_and_script_execution_paths(tmp_path, monkeypatch):
    wenv_abs = tmp_path / "worker env's"
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)

    AGI._mode = AGI.DASK_MODE
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {"sample": 1}
    AGI._worker_args = {"startup": 1}

    calls = {"new": [], "kill": [], "run_async": []}

    class _Worker:
        @staticmethod
        def _new(**kwargs):
            calls["new"].append(kwargs)

        @staticmethod
        async def _run(**kwargs):
            calls["new"].append(kwargs)
            return ["worker-log"]

    async def _fake_kill(*_args, **_kwargs):
        calls["kill"].append(True)

    async def _fake_run_async(cmd, cwd):
        calls["run_async"].append((cmd, cwd))
        return "line-1\nline-2\n"

    monkeypatch.setattr(AGI, "_kill", staticmethod(_fake_kill))

    AGI.env = SimpleNamespace(
        wenv_abs=wenv_abs,
        envars={},
        debug=True,
        verbose=2,
        target_worker="demo_worker",
        uv="uv",
    )

    debug_result = await runtime_distribution_support.run_local(
        AGI,
        base_worker_cls=_Worker,
        validate_worker_uv_sources_fn=lambda _path: None,
        run_async_fn=_fake_run_async,
    )

    assert debug_result == ["worker-log"]
    assert calls["kill"]
    assert calls["new"][0]["args"] == {"startup": 1}
    assert calls["new"][1]["args"] == {"sample": 1}

    AGI.env = SimpleNamespace(
        wenv_abs=wenv_abs,
        envars={},
        debug=False,
        verbose=2,
        app="demo_project",
        apps_path=Path("/tmp/apps"),
        active_app=Path("/tmp/apps/demo_project"),
        target_worker="demo_worker",
        uv="uv",
        uv_worker="uv-worker",
        pyvers_worker="3.13",
    )

    script_result = await runtime_distribution_support.run_local(
        AGI,
        base_worker_cls=_Worker,
        validate_worker_uv_sources_fn=lambda _path: None,
        run_async_fn=_fake_run_async,
    )

    assert script_result == "line-2"
    argv = shlex.split(calls["run_async"][0][0], posix=True)
    script = argv[argv.index("-c") + 1]
    assert argv[:5] == [
        "uv-worker",
        "run",
        "--preview-features",
        "python-upgrade",
        "--no-sync",
    ]
    assert Path(argv[argv.index("--project") + 1]) == wenv_abs
    assert argv[argv.index("--python") + 1] == "3.13"
    assert "from agi_env import AgiEnv" in script
    assert "AgiEnv(apps_path=Path('/tmp/apps'), app='demo_project', verbose=2)" in script
    assert "BaseWorker._new(env=env" in script
    assert "args={'startup': 1}" in script
    assert "BaseWorker._run(env=env" in script
    assert "args={'sample': 1}" in script
    assert "import asyncio" in script
    assert "if __name__ == '__main__':" in script

    calls["run_async"].clear()
    builtin_apps = Path("/tmp/repo/src/agilab/apps/builtin")
    AGI.env = SimpleNamespace(
        wenv_abs=wenv_abs,
        envars={},
        debug=False,
        verbose=2,
        app="flight_telemetry_project",
        apps_path=builtin_apps.parent,
        active_app=builtin_apps / "flight_telemetry_project",
        target_worker="flight_telemetry_worker",
        uv="uv",
        uv_worker="uv-worker",
        pyvers_worker="3.13",
    )

    await runtime_distribution_support.run_local(
        AGI,
        base_worker_cls=_Worker,
        validate_worker_uv_sources_fn=lambda _path: None,
        run_async_fn=_fake_run_async,
    )

    argv = shlex.split(calls["run_async"][0][0], posix=True)
    script = argv[argv.index("-c") + 1]
    assert (
        "AgiEnv(apps_path=Path('/tmp/repo/src/agilab/apps/builtin'), "
        "app='flight_telemetry_project', verbose=2)"
    ) in script


@pytest.mark.asyncio
async def test_start_returns_false_when_scheduler_bootstrap_fails(monkeypatch, tmp_path):
    AGI.env = SimpleNamespace(
        is_local=lambda _ip: True,
        envars={},
        uv="uv",
        wenv_abs=tmp_path / "worker_env",
        wenv_rel=Path("worker_env"),
    )
    AGI._workers = {"127.0.0.1": 1}

    async def _fake_start_scheduler(_scheduler):
        return False

    monkeypatch.setattr(AGI, "_start_scheduler", staticmethod(_fake_start_scheduler))

    assert await runtime_distribution_support.start(
        AGI,
        "127.0.0.1",
        set_env_var_fn=lambda *_args, **_kwargs: None,
    ) is False


@pytest.mark.asyncio
async def test_sync_handles_missing_worker_payloads_and_retryable_errors():
    class _Client:
        def __init__(self):
            self.calls = 0

        async def scheduler_info(self):
            self.calls += 1
            if self.calls == 1:
                return {"workers": None}
            if self.calls == 2:
                raise RuntimeError("temporary scheduler glitch")
            return {"workers": {"tcp://127.0.0.1:8787": {}}}

    class _Log:
        def __init__(self):
            self.info_messages = []

        def info(self, message, *args):
            self.info_messages.append(message % args if args else message)

        def error(self, *_args, **_kwargs):
            return None

    AGI._dask_client = _Client()
    AGI._workers = {"127.0.0.1": 1}

    async def _fake_sleep(_delay):
        return None

    clock = {"value": 0.0}

    def _fake_time():
        clock["value"] += 0.5
        return clock["value"]

    log = _Log()
    await runtime_distribution_support.sync(
        AGI,
        timeout=5,
        client_type=_Client,
        sleep_fn=_fake_sleep,
        time_fn=_fake_time,
        log=log,
    )

    assert any("workers' not ready yet" in message for message in log.info_messages)
    assert any("Exception in _sync" in message for message in log.info_messages)


@pytest.mark.asyncio
async def test_distribute_wraps_payloads_and_logs_worker_outputs(monkeypatch):
    calls = {"submit": []}

    class _Client:
        def scheduler_info(self):
            return {"workers": {"tcp://127.0.0.1:8787": {}}}

        def submit(self, fn, *args, **kwargs):
            calls["submit"].append((getattr(fn, "__name__", str(fn)), args, kwargs))
            return f"future-{len(calls['submit'])}"

        def gather(self, futures):
            if futures == ["future-1"]:
                return [None]
            return ["worker-log"]

    class _Dispatcher:
        @staticmethod
        async def _do_distrib(_env, workers, _args):
            return workers, [["step"]], [[{"meta": 1}]]

    class _Worker:
        @staticmethod
        def _new(**_kwargs):
            return None

        @staticmethod
        def _do_works(*_args, **_kwargs):
            return None

    AGI.env = SimpleNamespace(
        debug=False,
        target_worker="demo_worker",
        target="demo",
        mode2str=lambda mode: f"mode={mode}",
    )
    AGI._dask_client = _Client()
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {"payload": 1}
    AGI._mode = AGI.DASK_MODE
    AGI.verbose = 1

    async def _fake_calibration():
        return None

    monkeypatch.setattr(AGI, "_calibration", staticmethod(_fake_calibration))
    monkeypatch.setattr(AGI, "_scale_cluster", staticmethod(lambda: None))
    monkeypatch.setattr(AGI, "_wrap_worker_chunk", staticmethod(lambda payload, index: payload[index]))

    result = await runtime_distribution_support.distribute(
        AGI,
        work_dispatcher_cls=_Dispatcher,
        base_worker_cls=_Worker,
        time_fn=lambda: 5.0,
    )

    assert result == "mode=4 0.0"
    first_submit = calls["submit"][0]
    assert first_submit[2]["app"] == "demo_project"
    assert calls["submit"][1][1][0] == ["step"]
    assert calls["submit"][1][1][1] == [{"meta": 1}]


@pytest.mark.asyncio
async def test_main_runs_simulate_mode_directly(monkeypatch):
    calls = {"clean": []}

    async def _fake_run():
        return "simulate"

    monkeypatch.setattr(AGI, "_run", staticmethod(_fake_run))
    monkeypatch.setattr(AGI, "_clean_job", staticmethod(lambda cond: calls["clean"].append(cond)))
    AGI._mode = AGI._SIMULATE_MODE

    result = await runtime_distribution_support.main(
        AGI,
        "127.0.0.1",
        background_job_manager_factory=lambda: object(),
        time_fn=lambda: 1.0,
    )

    assert result == "simulate"
    assert calls["clean"] == [True]


@pytest.mark.asyncio
async def test_run_local_returns_none_for_empty_output_and_single_line_text(tmp_path, monkeypatch):
    wenv_abs = tmp_path / "worker_env"
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)

    AGI.env = SimpleNamespace(
        wenv_abs=wenv_abs,
        envars={},
        debug=False,
        verbose=0,
        uv="uv",
        target_worker="demo_worker",
    )
    AGI._mode = AGI.PYTHON_MODE
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {}

    async def _fake_kill(*_args, **_kwargs):
        return None

    async def _run_async_none(_cmd, _cwd):
        return None

    async def _run_async_single(_cmd, _cwd):
        return "single-line"

    monkeypatch.setattr(AGI, "_kill", staticmethod(_fake_kill))

    assert await runtime_distribution_support.run_local(
        AGI,
        base_worker_cls=SimpleNamespace(),
        validate_worker_uv_sources_fn=lambda _path: None,
        run_async_fn=_run_async_none,
    ) is None

    result = await runtime_distribution_support.run_local(
        AGI,
        base_worker_cls=SimpleNamespace(),
        validate_worker_uv_sources_fn=lambda _path: None,
        run_async_fn=_run_async_single,
    )
    assert result == "single-line"


@pytest.mark.asyncio
async def test_start_covers_detect_fallback_worker_errors_and_init_guard(monkeypatch, tmp_path):
    wenv_abs = tmp_path / "worker_env"
    wenv_abs.mkdir(parents=True, exist_ok=True)

    AGI.env = SimpleNamespace(
        is_local=lambda _ip: True,
        envars={},
        uv="uv",
        wenv_abs=wenv_abs,
        wenv_rel=Path("worker_env"),
    )
    AGI._mode = AGI.DASK_MODE
    AGI._mode_auto = False
    AGI._workers = {"127.0.0.1": 1}
    AGI._scheduler = "127.0.0.1:8786"

    class _Client:
        def upload_file(self, _path):
            return None

    async def _fake_start_scheduler(_scheduler):
        return True

    async def _fake_detect(_ip):
        raise RuntimeError("expected detect error")

    async def _fake_sync(*_args, **_kwargs):
        return None

    async def _fake_build_remote():
        return None

    monkeypatch.setattr(AGI, "_dask_client", _Client())
    monkeypatch.setattr(AGI, "_start_scheduler", staticmethod(_fake_start_scheduler))
    monkeypatch.setattr(AGI, "_detect_export_cmd", staticmethod(_fake_detect))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_fake_sync))
    monkeypatch.setattr(AGI, "_build_lib_remote", staticmethod(_fake_build_remote))
    monkeypatch.setattr(AGI, "_exec_bg", staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("start failed"))))

    AGI._worker_init_error = False
    with pytest.raises(RuntimeError, match="start failed"):
        await runtime_distribution_support.start(
            AGI,
            "127.0.0.1",
            set_env_var_fn=lambda *_args, **_kwargs: None,
            create_task_fn=lambda coro: coro,
        )

    monkeypatch.setattr(AGI, "_exec_bg", staticmethod(lambda *_args, **_kwargs: None))
    AGI._worker_init_error = True
    with pytest.raises(FileNotFoundError, match="Please run AGI.install"):
        await runtime_distribution_support.start(
            AGI,
            "127.0.0.1",
            set_env_var_fn=lambda *_args, **_kwargs: None,
            create_task_fn=lambda coro: coro,
        )


@pytest.mark.asyncio
async def test_sync_returns_for_non_client_and_times_out(monkeypatch):
    await runtime_distribution_support.sync(
        SimpleNamespace(_dask_client=object(), _workers={"127.0.0.1": 1}),
        client_type=dict,
    )

    class _Client:
        def __init__(self, payloads):
            self.payloads = list(payloads)

        async def scheduler_info(self):
            item = self.payloads.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    async def _fake_sleep(_delay):
        return None

    clock = {"value": 0.0}

    def _fake_time():
        clock["value"] += 2.0
        return clock["value"]

    agi = SimpleNamespace(
        _dask_client=_Client([{"workers": None}, {"workers": None}]),
        _workers={"127.0.0.1": 1},
    )
    with pytest.raises(TimeoutError, match="scheduler workers info"):
        await runtime_distribution_support.sync(
            agi,
            timeout=1,
            client_type=_Client,
            sleep_fn=_fake_sleep,
            time_fn=_fake_time,
            log=SimpleNamespace(info=lambda *_args, **_kwargs: None, error=lambda *_args, **_kwargs: None),
        )

    clock["value"] = 0.0
    agi = SimpleNamespace(
        _dask_client=_Client([{"workers": {"tcp://127.0.0.1:8787": {}}}, {"workers": {"tcp://127.0.0.1:8787": {}}}]),
        _workers={"127.0.0.1": 2},
    )
    with pytest.raises(TimeoutError, match="all workers to attach"):
        await runtime_distribution_support.sync(
            agi,
            timeout=1,
            client_type=_Client,
            sleep_fn=_fake_sleep,
            time_fn=_fake_time,
            log=SimpleNamespace(info=lambda *_args, **_kwargs: None, error=lambda *_args, **_kwargs: None),
        )


def test_scale_cluster_returns_when_no_dask_workers():
    agi = SimpleNamespace(_dask_workers=None, _workers={"127.0.0.1": 1})
    runtime_distribution_support.scale_cluster(agi)
    assert agi._dask_workers is None


@pytest.mark.asyncio
async def test_distribute_in_debug_mode_backfills_empty_worker_logs(monkeypatch):
    calls = {"submit": []}

    class _Client:
        def scheduler_info(self):
            return {"workers": {"tcp://127.0.0.1:8787": {}}}

        def submit(self, fn, *args, **kwargs):
            calls["submit"].append((getattr(fn, "__name__", str(fn)), args, kwargs))
            return "future-1"

        def gather(self, futures):
            if futures == ["future-1"]:
                return [None]
            return []

    class _Dispatcher:
        @staticmethod
        async def _do_distrib(_env, workers, _args):
            return workers, [["step"]], [[{"meta": 1}]]

    class _Worker:
        @staticmethod
        def _new(**_kwargs):
            return None

        @staticmethod
        def _do_works(*_args, **_kwargs):
            return None

    AGI.env = SimpleNamespace(
        debug=True,
        target_worker="demo_worker",
        target="demo",
        mode2str=lambda mode: f"mode={mode}",
    )
    AGI._dask_client = _Client()
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {"payload": 1}
    AGI._mode = AGI.DASK_MODE
    AGI.verbose = 1

    async def _fake_calibration():
        return None

    monkeypatch.setattr(AGI, "_calibration", staticmethod(_fake_calibration))
    monkeypatch.setattr(AGI, "_scale_cluster", staticmethod(lambda: None))
    monkeypatch.setattr(AGI, "_wrap_worker_chunk", staticmethod(lambda payload, index: payload[index]))

    result = await runtime_distribution_support.distribute(
        AGI,
        work_dispatcher_cls=_Dispatcher,
        base_worker_cls=_Worker,
        time_fn=lambda: 3.0,
    )

    assert result == "mode=4 0.0"


@pytest.mark.asyncio
async def test_distribute_in_debug_mode_backfills_known_workers_when_no_futures(monkeypatch):
    class _Client:
        def scheduler_info(self):
            return {"workers": {"tcp://127.0.0.1:8787": {}}}

        def submit(self, fn, *args, **kwargs):
            return f"future-{getattr(fn, '__name__', 'worker')}"

        def gather(self, futures):
            return futures

    class _Dispatcher:
        @staticmethod
        async def _do_distrib(_env, workers, _args):
            return workers, [], []

    AGI.env = SimpleNamespace(
        debug=True,
        target_worker="demo_worker",
        target="demo",
        mode2str=lambda mode: f"mode={mode}",
    )
    AGI._dask_client = _Client()
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {}
    AGI._mode = AGI.DASK_MODE
    AGI.verbose = 1
    AGI.debug = True

    async def _fake_calibration():
        AGI._capacity = {"127.0.0.1:8787": 1.0}

    monkeypatch.setattr(AGI, "_calibration", staticmethod(_fake_calibration))
    monkeypatch.setattr(AGI, "_scale_cluster", staticmethod(lambda: None))
    monkeypatch.setattr(
        AGI,
        "_wrap_worker_chunk",
        staticmethod(lambda payload, index: payload[index] if payload else []),
    )

    result = await runtime_distribution_support.distribute(
        AGI,
        work_dispatcher_cls=_Dispatcher,
        base_worker_cls=BaseWorker,
        time_fn=lambda: 4.0,
    )

    assert result == "mode=4 0.0"


@pytest.mark.asyncio
async def test_distribute_in_debug_mode_handles_empty_scheduler_worker_list(monkeypatch):
    class _Client:
        def scheduler_info(self):
            return {"workers": {}}

        def gather(self, futures):
            return futures

    class _Dispatcher:
        @staticmethod
        async def _do_distrib(_env, workers, _args):
            return workers, [], []

    AGI.env = SimpleNamespace(
        debug=True,
        target_worker="demo_worker",
        target="demo",
        mode2str=lambda mode: f"mode={mode}",
    )
    AGI._dask_client = _Client()
    AGI._workers = {}
    AGI._args = {}
    AGI._mode = AGI.DASK_MODE
    AGI.verbose = 1
    AGI.debug = True

    async def _fake_calibration():
        return None

    monkeypatch.setattr(AGI, "_calibration", staticmethod(_fake_calibration))
    monkeypatch.setattr(AGI, "_scale_cluster", staticmethod(lambda: None))
    monkeypatch.setattr(AGI, "_wrap_worker_chunk", staticmethod(lambda payload, index: payload[index] if payload else []))

    result = await runtime_distribution_support.distribute(
        AGI,
        work_dispatcher_cls=_Dispatcher,
        base_worker_cls=BaseWorker,
        time_fn=lambda: 4.0,
    )

    assert result == "mode=4 0.0"


@pytest.mark.asyncio
async def test_run_raises_when_worker_venv_is_missing(tmp_path, monkeypatch):
    AGI.env = SimpleNamespace(
        envars={},
        wenv_abs=tmp_path / "missing_wenv",
        debug=False,
        verbose=0,
        uv="uv",
        target_worker="demo_worker",
    )
    AGI._mode = AGI.PYTHON_MODE
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {}
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="Worker installation"):
        await runtime_distribution_support.run_local(
            AGI,
            base_worker_cls=BaseWorker,
            validate_worker_uv_sources_fn=lambda _path: None,
            run_async_fn=lambda *_args, **_kwargs: None,
        )


@pytest.mark.asyncio
async def test_run_raises_when_worker_uv_sources_are_stale(tmp_path, monkeypatch):
    wenv_abs = tmp_path / "wenv"
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        """
[tool.uv.sources]
ilp_worker = { path = "../../PycharmProjects/thales_agilab/apps/ilp_project/src/ilp_worker" }
""".strip(),
        encoding="utf-8",
    )
    AGI.env = SimpleNamespace(
        envars={},
        wenv_abs=wenv_abs,
        debug=False,
        verbose=0,
        uv="uv",
        target_worker="demo_worker",
    )
    AGI._mode = AGI.PYTHON_MODE
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {}
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="stale or incomplete"):
        await runtime_distribution_support.run_local(
            AGI,
            base_worker_cls=BaseWorker,
            validate_worker_uv_sources_fn=uv_source_support.validate_worker_uv_sources,
            run_async_fn=lambda *_args, **_kwargs: None,
        )


@pytest.mark.asyncio
async def test_run_debug_branch_returns_list_result(tmp_path, monkeypatch):
    wenv_abs = tmp_path / "wenv"
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
    AGI.env = SimpleNamespace(
        envars={},
        wenv_abs=wenv_abs,
        debug=True,
        verbose=1,
        uv="uv",
        target_worker="demo_worker",
    )
    AGI._mode = AGI.DASK_MODE
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {"alpha": 1}
    monkeypatch.chdir(tmp_path)
    calls = {"new": 0, "run": 0, "kill": 0}

    def _fake_new(*_args, **_kwargs):
        calls["new"] += 1

    async def _fake_run(*_args, **_kwargs):
        calls["run"] += 1
        calls["pid_namespaced"] = (
            (wenv_abs / "dask_worker_0.pid").exists()
            and not (tmp_path / "dask_worker_0.pid").exists()
        )
        return ["ok", "done"]

    async def _fake_kill(*_args, **_kwargs):
        calls["kill"] += 1
        return None

    monkeypatch.setattr(BaseWorker, "_new", staticmethod(_fake_new))
    monkeypatch.setattr(BaseWorker, "_run", staticmethod(_fake_run))
    monkeypatch.setattr(AGI, "_kill", staticmethod(_fake_kill))

    result = await runtime_distribution_support.run_local(
        AGI,
        base_worker_cls=BaseWorker,
        validate_worker_uv_sources_fn=lambda _path: None,
        run_async_fn=lambda *_args, **_kwargs: None,
    )
    assert result == ["ok", "done"]
    assert calls["new"] == 1
    assert calls["run"] == 1
    assert calls["kill"] == 1
    assert calls["pid_namespaced"] is True
    assert not (wenv_abs / "dask_worker_0.pid").exists()


@pytest.mark.asyncio
async def test_run_non_debug_branch_parses_last_line(tmp_path, monkeypatch):
    wenv_abs = tmp_path / "wenv"
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
    AGI.env = SimpleNamespace(
        envars={},
        wenv_abs=wenv_abs,
        debug=False,
        verbose=0,
        uv="uv",
        target_worker="demo_worker",
    )
    AGI._mode = AGI.PYTHON_MODE
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {"beta": 2}
    monkeypatch.chdir(tmp_path)

    async def _fake_kill(*_args, **_kwargs):
        return None

    async def _fake_run_async(_cmd, _cwd):
        return "header\nresult-line\n"

    monkeypatch.setattr(AGI, "_kill", staticmethod(_fake_kill))

    result = await runtime_distribution_support.run_local(
        AGI,
        base_worker_cls=BaseWorker,
        validate_worker_uv_sources_fn=lambda _path: None,
        run_async_fn=_fake_run_async,
    )
    assert result == "result-line"


@pytest.mark.asyncio
async def test_distribute_executes_new_calibration_and_works(monkeypatch):
    class _Client:
        def __init__(self):
            self._gather_calls = 0
            self.submissions = []

        def scheduler_info(self):
            return {
                "workers": {
                    "tcp://127.0.0.1:8787": {},
                    "tcp://10.0.0.2:8788": {},
                }
            }

        def submit(self, fn, *args, **kwargs):
            self.submissions.append(getattr(fn, "__name__", str(fn)))
            return {"fn": getattr(fn, "__name__", "fn"), "args": args, "kwargs": kwargs}

        def gather(self, futures):
            self._gather_calls += 1
            if self._gather_calls == 1:
                return [None for _ in futures]
            return ["log-a", "log-b"]

    AGI.env = SimpleNamespace(
        debug=False,
        target_worker="demo_worker",
        mode2str=lambda _mode: "dask",
    )
    AGI._dask_client = _Client()
    AGI._workers = {"127.0.0.1": 1, "10.0.0.2": 1}
    AGI._args = {"k": "v"}
    AGI._mode = AGI.DASK_MODE
    AGI.verbose = 0
    AGI.debug = False
    called = {"calibration": 0}

    async def _fake_distrib(_env, workers, _args):
        return workers, [["step-a"], ["step-b"]], [[{"m": 1}], [{"m": 2}]]

    async def _fake_calibration():
        called["calibration"] += 1
        AGI._capacity = {"127.0.0.1:8787": 1.0, "10.0.0.2:8788": 1.0}

    monkeypatch.setattr(WorkDispatcher, "_do_distrib", staticmethod(_fake_distrib))
    monkeypatch.setattr(AGI, "_calibration", staticmethod(_fake_calibration))
    monkeypatch.setattr(AGI, "_wrap_worker_chunk", staticmethod(lambda payload, index: payload[index]))

    result = await runtime_distribution_support.distribute(
        AGI,
        work_dispatcher_cls=WorkDispatcher,
        base_worker_cls=BaseWorker,
    )
    assert result.startswith("dask ")
    assert called["calibration"] == 1
    assert AGI._work_plan == [["step-a"], ["step-b"]]
    assert AGI._work_plan_metadata == [[{"m": 1}], [{"m": 2}]]
    assert "BaseWorker._new" not in AGI._dask_client.submissions


@pytest.mark.asyncio
async def test_sync_waits_until_expected_workers():
    class _FakeClient:
        def __init__(self):
            self.calls = 0

        def scheduler_info(self):
            self.calls += 1
            if self.calls == 1:
                return {"workers": None}
            if self.calls == 2:
                return {"workers": {"tcp://127.0.0.1:8787": {}}}
            return {
                "workers": {
                    "tcp://127.0.0.1:8787": {},
                    "tcp://10.0.0.2:8788": {},
                }
            }

    AGI._workers = {"127.0.0.1": 1, "10.0.0.2": 1}
    fake_client = _FakeClient()
    AGI._dask_client = fake_client
    sleep_delays: list[float] = []

    async def _fake_sleep(delay):
        sleep_delays.append(delay)
        return None

    await runtime_distribution_support.sync(
        AGI,
        timeout=2,
        client_type=_FakeClient,
        sleep_fn=_fake_sleep,
    )
    assert fake_client.calls >= 3
    assert sleep_delays == [0.2, 0.5]


@pytest.mark.asyncio
async def test_sync_supports_awaitable_scheduler_info():
    class _FakeClient:
        def __init__(self):
            self.calls = 0

        async def scheduler_info(self):
            self.calls += 1
            if self.calls == 1:
                return {"workers": None}
            if self.calls == 2:
                return {"workers": {"tcp://127.0.0.1:8787": {}}}
            return {
                "workers": {
                    "tcp://127.0.0.1:8787": {},
                    "tcp://10.0.0.2:8788": {},
                }
            }

    AGI._workers = {"127.0.0.1": 1, "10.0.0.2": 1}
    fake_client = _FakeClient()
    AGI._dask_client = fake_client

    async def _fake_sleep(_delay):
        return None

    await runtime_distribution_support.sync(
        AGI,
        timeout=2,
        client_type=_FakeClient,
        sleep_fn=_fake_sleep,
    )
    assert fake_client.calls >= 3


@pytest.mark.asyncio
async def test_sync_raises_timeout_on_repeated_failures():
    class _FakeClient:
        def scheduler_info(self):
            raise RuntimeError("scheduler down")

    AGI._workers = {"127.0.0.1": 1}
    AGI._dask_client = _FakeClient()

    async def _fake_sleep(_delay):
        return None

    clock = {"t": 0.0}

    def _fake_time():
        clock["t"] += 0.3
        return clock["t"]

    with pytest.raises(TimeoutError, match="Timeout waiting for all workers"):
        await runtime_distribution_support.sync(
            AGI,
            timeout=0.5,
            client_type=_FakeClient,
            sleep_fn=_fake_sleep,
            time_fn=_fake_time,
        )


@pytest.mark.asyncio
async def test_sync_propagates_unexpected_value_error():
    class _FakeClient:
        def scheduler_info(self):
            raise ValueError("unexpected scheduler bug")

    AGI._workers = {"127.0.0.1": 1}
    AGI._dask_client = _FakeClient()

    async def _fake_sleep(_delay):
        return None

    with pytest.raises(ValueError, match="unexpected scheduler bug"):
        await runtime_distribution_support.sync(
            AGI,
            timeout=1,
            client_type=_FakeClient,
            sleep_fn=_fake_sleep,
        )


@pytest.mark.asyncio
async def test_main_branches_simulate_install_dask_and_local(monkeypatch):
    class _Jobs:
        def flush(self):
            return None

    calls = []

    async def _fake_run():
        calls.append("run")
        return "run-result"

    async def _fake_prepare_local():
        calls.append("prepare_local")
        return None

    async def _fake_prepare_cluster(_scheduler):
        calls.append("prepare_cluster")
        return None

    async def _fake_deploy(_scheduler):
        calls.append("deploy")
        return None

    async def _fake_start(_scheduler):
        calls.append("start")
        return None

    async def _fake_distribute():
        calls.append("distribute")
        return "dist-result"

    async def _fake_stop():
        calls.append("stop")
        return None

    monkeypatch.setattr(AGI, "_run", staticmethod(_fake_run))
    monkeypatch.setattr(AGI, "_prepare_local_env", staticmethod(_fake_prepare_local))
    monkeypatch.setattr(AGI, "_prepare_cluster_env", staticmethod(_fake_prepare_cluster))
    monkeypatch.setattr(AGI, "_deploy_application", staticmethod(_fake_deploy))
    monkeypatch.setattr(AGI, "_start", staticmethod(_fake_start))
    monkeypatch.setattr(AGI, "_distribute", staticmethod(_fake_distribute))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_fake_stop))
    monkeypatch.setattr(AGI, "_update_capacity", staticmethod(lambda: calls.append("update_capacity")))
    monkeypatch.setattr(AGI, "_clean_dirs_local", staticmethod(lambda: calls.append("clean_dirs_local")))
    monkeypatch.setattr(AGI, "_clean_job", staticmethod(lambda cond: calls.append(("clean_job", cond))))

    AGI._mode = AGI._SIMULATE_MODE
    result = await runtime_distribution_support.main(
        AGI,
        "127.0.0.1",
        background_job_manager_factory=lambda: _Jobs(),
    )
    assert result == "run-result"

    times = iter([10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 14.5])
    AGI._mode = AGI._INSTALL_MODE | AGI.DASK_MODE
    result = await runtime_distribution_support.main(
        AGI,
        "127.0.0.1",
        background_job_manager_factory=lambda: _Jobs(),
        time_fn=lambda: next(times),
    )
    assert result == 4.5
    assert [entry["phase"] for entry in AGI._phase_timings] == [
        "prepare-local-env",
        "prepare-cluster-env",
        "deploy-application",
    ]

    AGI._mode = AGI.DASK_MODE
    result = await runtime_distribution_support.main(
        AGI,
        "127.0.0.1",
        background_job_manager_factory=lambda: _Jobs(),
    )
    assert result == "dist-result"

    AGI._mode = AGI.PYTHON_MODE
    result = await runtime_distribution_support.main(
        AGI,
        "127.0.0.1",
        background_job_manager_factory=lambda: _Jobs(),
    )
    assert result == "run-result"

    assert "prepare_local" in calls
    assert "prepare_cluster" in calls
    assert "deploy" in calls
    assert "start" in calls
    assert "distribute" in calls
    assert "stop" in calls


def test_remote_dask_worker_command_uses_posix_paths_for_windows_manager():
    # Regression: a Windows manager's native wenv_rel must not leak
    # backslash separators into the command sent to POSIX workers.
    from pathlib import PureWindowsPath

    command = runtime_distribution_support._remote_dask_worker_command(
        cmd_prefix="",
        dask_env="",
        uv_cmd="uv",
        wenv_rel=PureWindowsPath("wenv") / "flight_telemetry_worker",
        scheduler="10.0.0.1:8786",
        pid_file="dask_worker_0_0.pid",
    )

    assert "--project wenv/flight_telemetry_worker" in command
    assert (
        "--pid-file wenv/flight_telemetry_worker/dask_worker_0_0.pid" in command
    )
    assert "\\" not in command


@pytest.mark.asyncio
async def test_sync_raises_recorded_worker_launch_error():
    # Regression: a failed background remote launch must surface its root
    # cause instead of the generic 10s attach timeout.
    class _Client:
        async def scheduler_info(self):
            return {"workers": {}}

    AGI._dask_client = _Client()
    AGI._workers = {"10.0.0.5": 2}
    AGI._worker_launch_errors = [ConnectionError("Authentication failed for SSH user")]

    async def _fake_sleep(_delay):
        return None

    try:
        with pytest.raises(ConnectionError, match="Authentication failed"):
            await runtime_distribution_support.sync(
                AGI,
                timeout=5,
                client_type=_Client,
                sleep_fn=_fake_sleep,
            )
    finally:
        AGI._worker_launch_errors = []


@pytest.mark.asyncio
async def test_start_records_launch_task_failures(monkeypatch, tmp_path):
    wenv_abs = tmp_path / "worker_env"
    (wenv_abs / "dist").mkdir(parents=True, exist_ok=True)

    AGI.env = SimpleNamespace(
        is_local=lambda _ip: False,
        envars={"10.0.0.5_CMD_PREFIX": "x "},
        uv="uv",
        wenv_abs=wenv_abs,
        wenv_rel=Path("worker_env"),
    )
    AGI._mode = AGI.DASK_MODE
    AGI._mode_auto = False
    AGI._workers = {"10.0.0.5": 1}
    AGI._scheduler = "10.0.0.5:8786"
    AGI._worker_init_error = False

    class _Client:
        def upload_file(self, _path):
            return None

    async def _fake_start_scheduler(_scheduler):
        return True

    async def _failing_exec_ssh_async(_ip, _cmd):
        raise ConnectionError("key changed on remote host")

    sync_calls = {"count": 0}

    async def _fake_sync(timeout=60):
        sync_calls["count"] += 1
        # Yield so the launch task's done callback runs before assertions.
        for _ in range(5):
            await asyncio.sleep(0)
        errors = getattr(AGI, "_worker_launch_errors", None)
        if errors:
            raise errors[0]

    async def _fake_build_remote():
        return None

    monkeypatch.setattr(AGI, "_dask_client", _Client())
    monkeypatch.setattr(AGI, "_start_scheduler", staticmethod(_fake_start_scheduler))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_fake_sync))
    monkeypatch.setattr(AGI, "_build_lib_remote", staticmethod(_fake_build_remote))
    monkeypatch.setattr(AGI, "exec_ssh_async", staticmethod(_failing_exec_ssh_async))

    with pytest.raises(ConnectionError, match="key changed"):
        await runtime_distribution_support.start(
            AGI,
            "10.0.0.5",
            set_env_var_fn=lambda *_args, **_kwargs: None,
        )
    assert sync_calls["count"] == 1
    assert AGI._worker_launch_errors


@pytest.mark.asyncio
async def test_stop_shuts_down_client_after_partial_benchmark(monkeypatch):
    # Regression: stop() used to skip client.shutdown() unless the last
    # benchmark mode happened to be 7 or 15, leaking the scheduler for
    # partial mode ranges. New contract: only an in-flight benchmark
    # (_mode_auto=True) defers shutdown.
    class _Client:
        def __init__(self):
            self.shutdown_calls = 0

        async def scheduler_info(self):
            return {"workers": {}}

        async def retire_workers(self, workers, close_workers=True, remove=True):
            return None

        async def shutdown(self):
            self.shutdown_calls += 1

    async def _fake_close_all():
        return None

    async def _fake_sleep(_delay):
        return None

    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_fake_close_all))
    AGI._TIMEOUT = 2

    owned_client = _Client()
    AGI._dask_client = owned_client
    AGI._mode_auto = False
    AGI._mode = 5  # partial-range benchmark final mode
    await runtime_distribution_support.stop(AGI, sleep_fn=_fake_sleep)
    assert owned_client.shutdown_calls == 1
    assert AGI._dask_client is None

    deferred_client = _Client()
    AGI._dask_client = deferred_client
    AGI._mode_auto = True
    await runtime_distribution_support.stop(AGI, sleep_fn=_fake_sleep)
    assert deferred_client.shutdown_calls == 0
    assert AGI._dask_client is deferred_client


def test_clean_job_respects_cond_and_verbosity():
    class _Jobs:
        def __init__(self):
            self.flush_calls = 0

        def flush(self):
            self.flush_calls += 1

    jobs = _Jobs()
    AGI._jobs = jobs

    AGI.verbose = 1
    runtime_distribution_support.clean_job(AGI, True)
    assert jobs.flush_calls == 1

    AGI.verbose = 0
    runtime_distribution_support.clean_job(AGI, True)
    assert jobs.flush_calls == 2

    runtime_distribution_support.clean_job(AGI, False)
    assert jobs.flush_calls == 2


def test_rapids_mode_bit_does_not_collide_with_install_mode():
    # Regression: RAPIDS_MODE used to be 16, colliding with _INSTALL_MODE
    # (0b01 << DASK_MODE == 16), so AGI.DASK_MODE | AGI.RAPIDS_MODE silently
    # selected the install/sync path. The rapids run bit is 8.
    assert AGI.RAPIDS_MODE == (AGI._RAPIDS_SET ^ AGI._RAPIDS_RESET) == 8
    assert AGI.RAPIDS_MODE != AGI._INSTALL_MODE
    combined = AGI.DASK_MODE | AGI.RAPIDS_MODE
    # Not on the simulate branch, not >= install, but still a dask run.
    assert (combined & AGI._DEPLOYEMENT_MASK) != AGI._SIMULATE_MODE
    assert combined < AGI._INSTALL_MODE
    assert combined & AGI.DASK_MODE


@pytest.mark.asyncio
async def test_main_dask_rapids_run_resolves_to_distribute_not_install(monkeypatch):
    # Regression: DASK_MODE | RAPIDS_MODE must run the distribute pipeline, not
    # the install/deploy branch.
    class _Jobs:
        def flush(self):
            return None

    calls = []

    async def _fake_start(_scheduler):
        calls.append("start")
        return None

    async def _fake_distribute():
        calls.append("distribute")
        return "rapids-run-result"

    async def _fake_stop():
        calls.append("stop")
        return None

    async def _fake_deploy(_scheduler):
        calls.append("deploy")
        return None

    monkeypatch.setattr(AGI, "_start", staticmethod(_fake_start))
    monkeypatch.setattr(AGI, "_distribute", staticmethod(_fake_distribute))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_fake_stop))
    monkeypatch.setattr(AGI, "_deploy_application", staticmethod(_fake_deploy))
    monkeypatch.setattr(AGI, "_update_capacity", staticmethod(lambda: calls.append("update_capacity")))
    monkeypatch.setattr(AGI, "_clean_job", staticmethod(lambda cond: None))

    AGI._mode = AGI.DASK_MODE | AGI.RAPIDS_MODE
    result = await runtime_distribution_support.main(
        AGI,
        "127.0.0.1",
        background_job_manager_factory=lambda: _Jobs(),
    )

    assert result == "rapids-run-result"
    assert calls == ["start", "distribute", "update_capacity", "stop"]
    assert "deploy" not in calls


@pytest.mark.asyncio
async def test_main_dask_run_stops_cluster_when_distribute_raises(monkeypatch):
    # Regression: a raising _distribute used to skip _stop(), leaking the
    # scheduler/workers/ports/SSH connections. main() must always run _stop().
    class _Jobs:
        def flush(self):
            return None

    calls = []

    async def _fake_start(_scheduler):
        calls.append("start")
        return None

    async def _fake_distribute():
        calls.append("distribute")
        raise RuntimeError("distribute exploded")

    async def _fake_stop():
        calls.append("stop")
        return None

    monkeypatch.setattr(AGI, "_start", staticmethod(_fake_start))
    monkeypatch.setattr(AGI, "_distribute", staticmethod(_fake_distribute))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_fake_stop))
    monkeypatch.setattr(
        AGI,
        "_update_capacity",
        staticmethod(lambda: calls.append("update_capacity")),
    )
    monkeypatch.setattr(AGI, "_clean_job", staticmethod(lambda cond: None))

    AGI._mode = AGI.DASK_MODE

    with pytest.raises(RuntimeError, match="distribute exploded"):
        await runtime_distribution_support.main(
            AGI,
            "127.0.0.1",
            background_job_manager_factory=lambda: _Jobs(),
        )

    # _update_capacity is skipped because distribute failed, but _stop must run.
    assert "stop" in calls
    assert "update_capacity" not in calls


@pytest.mark.asyncio
async def test_main_dask_run_stops_cluster_when_startup_raises(monkeypatch):
    class _Jobs:
        def flush(self):
            return None

    calls = []

    async def _fail_start(_scheduler):
        calls.append("start")
        raise ConnectionError("scheduler launch failed")

    async def _stop():
        calls.append("stop")

    monkeypatch.setattr(AGI, "_start", staticmethod(_fail_start))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))
    monkeypatch.setattr(AGI, "_clean_job", staticmethod(lambda _cond: None))
    AGI._mode = AGI.DASK_MODE

    with pytest.raises(ConnectionError, match="scheduler launch failed"):
        await runtime_distribution_support.main(
            AGI,
            "127.0.0.1",
            background_job_manager_factory=lambda: _Jobs(),
        )

    assert calls == ["start", "stop"]
    assert AGI._startup_in_progress is False


@pytest.mark.asyncio
async def test_stop_cancels_and_awaits_scheduler_and_worker_launch_tasks(monkeypatch):
    cleaned = []
    blocker = asyncio.Event()

    async def _launch(label):
        try:
            await blocker.wait()
        finally:
            cleaned.append(label)

    scheduler_task = asyncio.create_task(_launch("scheduler"))
    worker_task = asyncio.create_task(_launch("worker"))
    await asyncio.sleep(0)
    AGI._dask_client = None
    AGI._scheduler_launch_tasks = {scheduler_task}
    AGI._worker_launch_tasks = {worker_task}

    async def _close_all():
        cleaned.append("connections")

    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_close_all))
    await runtime_distribution_support.stop(AGI)

    assert scheduler_task.cancelled()
    assert worker_task.cancelled()
    assert set(cleaned) == {"scheduler", "worker", "connections"}
    assert AGI._scheduler_launch_tasks == set()
    assert AGI._worker_launch_tasks == set()


@pytest.mark.asyncio
async def test_stop_drains_owned_cleanup_under_repeated_cancellation(monkeypatch):
    launch_cleanup_started = asyncio.Event()
    allow_launch_cleanup = asyncio.Event()
    launch_cleanup_finished = asyncio.Event()
    connections_started = asyncio.Event()
    allow_connections = asyncio.Event()
    connections_finished = asyncio.Event()

    async def _launch():
        try:
            await asyncio.Event().wait()
        finally:
            launch_cleanup_started.set()
            await allow_launch_cleanup.wait()
            launch_cleanup_finished.set()

    launch_task = asyncio.create_task(_launch())
    await asyncio.sleep(0)
    AGI._dask_client = None
    AGI._scheduler_launch_tasks = {launch_task}
    AGI._worker_launch_tasks = set()

    async def _close_all():
        connections_started.set()
        await allow_connections.wait()
        connections_finished.set()

    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_close_all))
    stop_task = asyncio.create_task(runtime_distribution_support.stop(AGI))

    await launch_cleanup_started.wait()
    stop_task.cancel()
    await asyncio.sleep(0)
    stop_task.cancel()
    await asyncio.sleep(0)
    assert not launch_task.done()

    allow_launch_cleanup.set()
    await connections_started.wait()
    stop_task.cancel()
    await asyncio.sleep(0)
    stop_task.cancel()
    await asyncio.sleep(0)
    allow_connections.set()

    with pytest.raises(asyncio.CancelledError):
        await stop_task

    assert launch_task.cancelled()
    assert launch_cleanup_finished.is_set()
    assert connections_finished.is_set()
    assert AGI._scheduler_launch_tasks == set()
    assert AGI._service_cleanup_unproven is False


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_phase", ["client-shutdown", "connections"])
async def test_stop_times_out_repeated_cancellation_and_reuses_owned_cleanup_task(
    monkeypatch,
    blocked_phase,
):
    cleanup_entered = asyncio.Event()
    allow_cleanup = asyncio.Event()
    connections_finished = asyncio.Event()

    class _Client:
        async def scheduler_info(self):
            return {"workers": {}}

        async def shutdown(self):
            if blocked_phase == "client-shutdown":
                cleanup_entered.set()
                await allow_cleanup.wait()

    AGI._dask_client = _Client() if blocked_phase == "client-shutdown" else None
    AGI._mode_auto = False

    async def _close_all():
        if blocked_phase == "connections":
            cleanup_entered.set()
            await allow_cleanup.wait()
        connections_finished.set()

    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_close_all))
    stop_task = asyncio.create_task(
        runtime_distribution_support.stop(AGI, cleanup_timeout=0.05)
    )

    await asyncio.wait_for(cleanup_entered.wait(), timeout=1)
    stop_task.cancel()
    await asyncio.sleep(0)
    stop_task.cancel()

    with pytest.raises(
        runtime_distribution_support.RuntimeCleanupRequiredError,
        match="owned cleanup task and lifecycle lease were retained",
    ):
        await stop_task

    owned_cleanup = AGI._runtime_cleanup_task
    assert isinstance(owned_cleanup, asyncio.Task)
    assert not owned_cleanup.done()
    assert AGI._service_cleanup_unproven is True
    assert AGI._runtime_cleanup_phase == blocked_phase

    allow_cleanup.set()
    await runtime_distribution_support.stop(AGI, cleanup_timeout=1.0)

    assert owned_cleanup.done()
    assert AGI._runtime_cleanup_task is None
    assert AGI._service_cleanup_unproven is False
    assert connections_finished.is_set()


@pytest.mark.asyncio
async def test_stop_marks_cleanup_unproven_when_connection_cleanup_fails(monkeypatch):
    AGI._dask_client = None
    AGI._scheduler_launch_tasks = set()
    AGI._worker_launch_tasks = set()

    async def _close_all():
        raise RuntimeError("connection cleanup failed")

    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_close_all))

    with pytest.raises(
        runtime_distribution_support.RuntimeCleanupRequiredError,
        match="connection cleanup failed",
    ):
        await runtime_distribution_support.stop(AGI)

    assert AGI._service_cleanup_unproven is True


@pytest.mark.asyncio
async def test_stop_terminates_owned_local_jobs_after_partial_startup(monkeypatch):
    calls = []

    class _Process:
        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout):
            calls.append(("wait", timeout))
            if calls.count(("wait", timeout)) == 1:
                raise subprocess.TimeoutExpired("dask-worker", timeout)
            return 0

        def kill(self):
            calls.append("kill")

    process = _Process()
    AGI._jobs = SimpleNamespace(running=[SimpleNamespace(process=process)])
    AGI._dask_client = None
    AGI._mode_auto = True
    AGI._startup_in_progress = True

    async def _close_all():
        calls.append("connections")

    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_close_all))

    await runtime_distribution_support.stop(AGI)

    assert calls == [
        "terminate",
        ("wait", 3.0),
        "kill",
        ("wait", 3.0),
        "connections",
    ]


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group regression")
async def test_stop_terminates_child_after_background_wrapper_exits(monkeypatch, tmp_path):
    child_pid_file = tmp_path / "child.pid"
    parent_code = "\n".join(
        [
            "import subprocess",
            "import sys",
            "from pathlib import Path",
            "child = subprocess.Popen(",
            "    [sys.executable, '-c', 'import time; time.sleep(120)']",
            ")",
            "Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8')",
        ]
    )
    manager = background_jobs_support.BackgroundProcessManager()
    job = manager.new(
        [sys.executable, "-c", parent_code, str(child_pid_file)],
        cwd=tmp_path,
    )
    child_pid: int | None = None

    def _is_live_process(pid: int) -> bool:
        try:
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return False

    async def _wait_until(predicate, *, timeout: float = 5.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("background process condition was not reached")
            await asyncio.sleep(0.02)

    try:
        await _wait_until(child_pid_file.is_file)
        child_pid = int(child_pid_file.read_text(encoding="utf-8"))
        await _wait_until(lambda: job.process.poll() is not None)
        assert _is_live_process(child_pid)

        # This refresh retires the successful wrapper from ``running``. The
        # separate ownership record must still make its child discoverable.
        assert manager.result(job.num) is job.process
        assert job not in manager.running
        assert job in manager.owned

        AGI._jobs = manager
        AGI._dask_client = None
        AGI._mode_auto = True
        AGI._startup_in_progress = True

        async def _fake_close_all():
            return None

        monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_fake_close_all))

        await runtime_distribution_support.stop(AGI)
        await _wait_until(lambda: not _is_live_process(child_pid))

        assert job not in manager.owned
        assert job.num not in manager.all
    finally:
        if child_pid is not None and _is_live_process(child_pid):
            child = psutil.Process(child_pid)
            child.kill()
            try:
                child.wait(timeout=3)
            except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                pass


@pytest.mark.asyncio
async def test_owned_job_cleanup_rejects_inaccessible_token_candidate(monkeypatch):
    started_at = time.time()
    username = psutil.Process(os.getpid()).username()

    class _CompletedWrapper:
        pid = 7101

        @staticmethod
        def poll():
            return 0

    class _InaccessibleCandidate:
        pid = 7102

        @staticmethod
        def create_time():
            return started_at

        @staticmethod
        def username():
            return username

        def environ(self):
            raise psutil.AccessDenied(self.pid)

    job = SimpleNamespace(
        process=_CompletedWrapper(),
        ownership_token="owned-token",
        ownership_started_at=started_at,
        process_group_id=None,
        num=7,
    )
    manager = SimpleNamespace(
        owned=[job],
        running=[],
        completed=[],
        dead=[],
        all={7: job},
    )
    monkeypatch.setattr(
        runtime_distribution_support.psutil,
        "process_iter",
        lambda attrs: iter([_InaccessibleCandidate()]),
    )

    with pytest.raises(
        runtime_distribution_support.RuntimeCleanupRequiredError,
        match="ownership token unavailable.*7102",
    ):
        await runtime_distribution_support._terminate_owned_background_jobs(
            SimpleNamespace(_jobs=manager)
        )

    assert manager.owned == [job]
    assert manager.all == {7: job}


@pytest.mark.asyncio
async def test_stop_marks_kill_wait_timeout_as_recovery_required(monkeypatch):
    calls = []

    class _Process:
        pid = 4321

        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout):
            calls.append(("wait", timeout))
            raise subprocess.TimeoutExpired("dask-worker", timeout)

        def kill(self):
            calls.append("kill")

    process = _Process()
    AGI._jobs = SimpleNamespace(running=[SimpleNamespace(process=process)])
    AGI._dask_client = None
    AGI._mode_auto = True
    AGI._startup_in_progress = True

    async def _close_all():
        calls.append("connections")

    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_close_all))

    with pytest.raises(
        runtime_distribution_support.RuntimeCleanupRequiredError,
        match="kill/wait",
    ):
        await runtime_distribution_support.stop(AGI)

    assert calls == [
        "terminate",
        ("wait", 3.0),
        "kill",
        ("wait", 3.0),
        "connections",
    ]
    assert AGI._service_cleanup_unproven is True
    assert AGI._runtime_cleanup_task is None
