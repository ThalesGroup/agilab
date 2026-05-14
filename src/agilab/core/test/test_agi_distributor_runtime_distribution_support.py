from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from agi_cluster.agi_distributor import AGI, runtime_distribution_support, uv_source_support
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
        "_dask_log_level",
        "_rapids_enabled",
        "_workers_data_path",
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
        AGI._dask_log_level = "critical"
        AGI._rapids_enabled = False
        AGI._workers_data_path = None
        yield
    finally:
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

    AGI._dask_client = _Client()
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

    assert AGI._dask_client.retire_calls >= 1
    assert AGI._dask_client.shutdown_calls == 1
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

    AGI._dask_client = _Client()
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

    assert AGI._dask_client.retire_calls >= 1
    assert AGI._dask_client.shutdown_calls == 1
    assert closed["count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["scheduler_info", "retire_workers", "shutdown"])
async def test_stop_swallows_expected_operational_errors(monkeypatch, phase):
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

    await runtime_distribution_support.stop(AGI, sleep_fn=_fake_sleep)

    assert closed["count"] == 1


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
    wenv_abs = tmp_path / "worker_env"
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
    assert "uv-worker run --preview-features python-upgrade --no-sync" in calls["run_async"][0][0]
    assert "--python 3.13 python -c" in calls["run_async"][0][0]
    assert "from agi_env import AgiEnv" in calls["run_async"][0][0]
    assert "AgiEnv(apps_path=Path('/tmp/apps'), app='demo_project', verbose=2)" in calls["run_async"][0][0]
    assert "BaseWorker._new(env=env" in calls["run_async"][0][0]
    assert "args={'startup': 1}" in calls["run_async"][0][0]
    assert "BaseWorker._run(env=env" in calls["run_async"][0][0]
    assert "args={'sample': 1}" in calls["run_async"][0][0]
    assert "import asyncio" in calls["run_async"][0][0]
    assert "if __name__ == '__main__':" in calls["run_async"][0][0]

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
        target_worker="flight_worker",
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

    assert (
        "AgiEnv(apps_path=Path('/tmp/repo/src/agilab/apps/builtin'), "
        "app='flight_telemetry_project', verbose=2)"
    ) in calls["run_async"][0][0]


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
    assert (tmp_path / "dask_worker_0.pid").exists()


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

    times = iter([10.0, 14.5])
    AGI._mode = AGI._INSTALL_MODE | AGI.DASK_MODE
    result = await runtime_distribution_support.main(
        AGI,
        "127.0.0.1",
        background_job_manager_factory=lambda: _Jobs(),
        time_fn=lambda: next(times),
    )
    assert result == 4.5

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
