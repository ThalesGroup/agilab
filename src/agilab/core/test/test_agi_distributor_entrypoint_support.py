from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import AGI, RunRequest, entrypoint_support


@pytest.fixture(autouse=True)
def _reset_agi_entrypoint_state():
    fields = [
        "env",
        "_mode",
        "_mode_auto",
        "_workers",
        "_worker_init_error",
        "_TIMEOUT",
        "_dask_client",
        "_install_done",
        "_scheduler",
        "_scheduler_ip",
        "_scheduler_port",
    ]
    snapshot = {field: getattr(AGI, field, None) for field in fields}
    try:
        AGI.env = None
        AGI._mode = 0
        AGI._mode_auto = False
        AGI._workers = {}
        AGI._worker_init_error = False
        AGI._TIMEOUT = 10
        AGI._dask_client = None
        AGI._install_done = False
        AGI._scheduler = None
        AGI._scheduler_ip = None
        AGI._scheduler_port = None
        yield
    finally:
        for field, value in snapshot.items():
            setattr(AGI, field, value)


@pytest.mark.asyncio
async def test_start_scheduler_local_switches_port_and_connects(monkeypatch, tmp_path):
    cluster_pck = tmp_path / "cluster"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")
    active_app = tmp_path / "app"
    active_app.mkdir(parents=True, exist_ok=True)
    (active_app / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")

    AGI._mode = AGI.DASK_MODE
    AGI._mode_auto = False
    AGI._workers = {"127.0.0.1": 1}
    AGI._worker_init_error = False
    AGI._scheduler = "127.0.0.1:8786"
    AGI.env = SimpleNamespace(
        wenv_rel=Path("wenv"),
        wenv_abs=tmp_path / "wenv",
        active_app=active_app,
        app="demo_app",
        uv="uv",
        envars={},
        cluster_pck=cluster_pck,
        export_local_bin="",
        is_local=lambda ip: ip == "127.0.0.1",
    )
    AGI.env.wenv_abs.mkdir(parents=True, exist_ok=True)
    calls = {"bg": [], "set_env": []}

    async def _fake_send(*_args, **_kwargs):
        return None

    async def _fake_kill(*_args, **_kwargs):
        return None

    async def _fake_connect(*_args, **_kwargs):
        return "fake-client"

    async def _fake_detect(_ip):
        return 'export PATH="$HOME/.local/bin:$PATH"; '

    async def _fake_sleep(_delay):
        return None

    async def _fake_port_release(*_args, **_kwargs):
        return False

    monkeypatch.setattr(
        AGI,
        "_get_scheduler",
        staticmethod(lambda _scheduler: ("127.0.0.1", 8786)),
    )
    monkeypatch.setattr(AGI, "send_file", staticmethod(_fake_send))
    monkeypatch.setattr(AGI, "_kill", staticmethod(_fake_kill))
    monkeypatch.setattr(AGI, "_wait_for_port_release", staticmethod(_fake_port_release))
    monkeypatch.setattr(AGI, "find_free_port", staticmethod(lambda *_a, **_k: 8899))
    monkeypatch.setattr(AGI, "_detect_export_cmd", staticmethod(_fake_detect))
    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fake_connect))
    monkeypatch.setattr(AGI, "_dask_env_prefix", staticmethod(lambda: ""))
    monkeypatch.setattr(
        AGI,
        "_exec_bg",
        staticmethod(lambda cmd, cwd: calls["bg"].append((cmd, cwd))),
    )

    ok = await entrypoint_support.start_scheduler(
        AGI,
        "127.0.0.1",
        set_env_var_fn=lambda *args: calls["set_env"].append(args),
        create_task_fn=lambda coro: coro,
        sleep_fn=_fake_sleep,
    )

    assert ok is True
    assert AGI._scheduler_port == 8899
    assert AGI._dask_client == "fake-client"
    assert AGI._install_done is True
    assert calls["bg"]
    assert any(entry[0] == "127.0.0.1_CMD_PREFIX" for entry in calls["set_env"])


def test_load_capacity_predictor_uses_shared_runtime_helper(monkeypatch, tmp_path):
    env = SimpleNamespace(
        resources_path=tmp_path / "resources",
        home_abs=tmp_path / "home",
    )
    env.resources_path.mkdir(parents=True, exist_ok=True)
    env.home_abs.mkdir(parents=True, exist_ok=True)
    sentinels = {"retrain": 0}
    predictor = object()

    monkeypatch.setattr(
        entrypoint_support.runtime_misc_support,
        "load_capacity_predictor",
        lambda model_path, *, retrain_fn=None, log=None, load_fn=None: predictor,
    )
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: sentinels.__setitem__("retrain", sentinels["retrain"] + 1)))

    entrypoint_support._load_capacity_predictor(AGI, env)

    assert AGI._capacity_predictor is predictor
    assert sentinels["retrain"] == 0


def test_prepare_run_execution_calls_runtime_steps_in_order(monkeypatch):
    calls = []
    env = object()

    monkeypatch.setattr(
        entrypoint_support,
        "_configure_mode",
        lambda agi_cls, current_env, mode: calls.append(("configure", agi_cls, current_env, mode)),
    )
    monkeypatch.setattr(
        entrypoint_support,
        "_load_capacity_predictor",
        lambda agi_cls, current_env: calls.append(("capacity", agi_cls, current_env)),
    )
    monkeypatch.setattr(
        entrypoint_support,
        "_resolve_install_worker_group",
        lambda agi_cls, current_env: calls.append(("install-group", agi_cls, current_env)),
    )

    entrypoint_support._prepare_run_execution(AGI, env, AGI.DASK_MODE)

    assert calls == [
        ("configure", AGI, env, AGI.DASK_MODE),
        ("capacity", AGI, env),
        ("install-group", AGI, env),
    ]


@pytest.mark.asyncio
async def test_run_prepared_execution_calls_prepare_then_run_main(monkeypatch):
    calls = []
    env = object()

    monkeypatch.setattr(
        entrypoint_support,
        "_prepare_run_execution",
        lambda agi_cls, current_env, mode: calls.append(("prepare", agi_cls, current_env, mode)),
    )

    async def _fake_run_main(
        agi_cls,
        scheduler,
        *,
        process_error_type,
        format_exception_chain_fn,
        traceback_format_exc_fn,
        log,
    ):
        calls.append(
            (
                "run-main",
                agi_cls,
                scheduler,
                process_error_type,
                format_exception_chain_fn,
                traceback_format_exc_fn,
                log,
            )
        )
        return "ok"

    monkeypatch.setattr(entrypoint_support, "_run_main_with_handled_errors", _fake_run_main)

    process_error_type = RuntimeError
    format_exception_chain_fn = str
    traceback_format_exc_fn = lambda: "tb"
    log = object()

    result = await entrypoint_support._run_prepared_execution(
        AGI,
        env,
        AGI.DASK_MODE,
        "127.0.0.1",
        process_error_type=process_error_type,
        format_exception_chain_fn=format_exception_chain_fn,
        traceback_format_exc_fn=traceback_format_exc_fn,
        log=log,
    )

    assert result == "ok"
    assert calls == [
        ("prepare", AGI, env, AGI.DASK_MODE),
        (
            "run-main",
            AGI,
            "127.0.0.1",
            process_error_type,
            format_exception_chain_fn,
            traceback_format_exc_fn,
            log,
        ),
    ]


@pytest.mark.asyncio
async def test_dispatch_run_execution_switches_between_benchmark_and_prepared(monkeypatch):
    calls = []
    env = object()
    benchmark_request = RunRequest(
        params={"sample": "value"},
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        verbose=2,
        mode=AGI.DASK_MODE,
        rapids_enabled=True,
    )
    prepared_request = RunRequest(
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        verbose=2,
        mode=AGI.DASK_MODE,
        rapids_enabled=True,
    )

    async def _fake_prepared(
        agi_cls,
        current_env,
        mode,
        scheduler,
        *,
        process_error_type,
        format_exception_chain_fn,
        traceback_format_exc_fn,
        log,
    ):
        calls.append(
            (
                "prepared",
                agi_cls,
                current_env,
                mode,
                scheduler,
                process_error_type,
                format_exception_chain_fn,
                traceback_format_exc_fn,
                log,
            )
        )
        return "prepared-ok"

    async def _fake_benchmark(
        current_env,
        request,
    ):
        calls.append(
            (
                "benchmark",
                current_env,
                request.scheduler,
                request.workers,
                request.verbose,
                request.mode,
                request.rapids_enabled,
                request.to_target_kwargs(),
            )
        )
        return "benchmark-ok"

    monkeypatch.setattr(entrypoint_support, "_run_prepared_execution", _fake_prepared)
    monkeypatch.setattr(AGI, "_benchmark", _fake_benchmark)

    process_error_type = RuntimeError
    format_exception_chain_fn = str
    traceback_format_exc_fn = lambda: "tb"
    log = object()

    benchmark_result = await entrypoint_support._dispatch_run_execution(
        AGI,
        env,
        benchmark_request,
        range(3),
        process_error_type=process_error_type,
        format_exception_chain_fn=format_exception_chain_fn,
        traceback_format_exc_fn=traceback_format_exc_fn,
        log=log,
    )
    prepared_result = await entrypoint_support._dispatch_run_execution(
        AGI,
        env,
        prepared_request,
        None,
        process_error_type=process_error_type,
        format_exception_chain_fn=format_exception_chain_fn,
        traceback_format_exc_fn=traceback_format_exc_fn,
        log=log,
    )

    assert benchmark_result == "benchmark-ok"
    assert prepared_result == "prepared-ok"
    assert calls == [
        (
            "benchmark",
            env,
            "127.0.0.1",
            {"127.0.0.1": 1},
            2,
            [0, 1, 2],
            True,
            {"sample": "value"},
        ),
        (
            "prepared",
            AGI,
            env,
            AGI.DASK_MODE,
            "127.0.0.1",
            process_error_type,
            format_exception_chain_fn,
            traceback_format_exc_fn,
            log,
        ),
    ]


def test_connection_error_payload_defaults_empty_message(capsys):
    class _FakeLogger:
        def __init__(self):
            self.info_messages = []

        def info(self, message):
            self.info_messages.append(message)

    payload = entrypoint_support._connection_error_payload(ConnectionError(""), log=_FakeLogger())

    assert payload == {
        "status": "error",
        "message": "Failed to connect to remote host.",
        "kind": "connection",
    }
    assert "Failed to connect to remote host." in capsys.readouterr().err


@pytest.mark.asyncio
async def test_run_main_with_handled_errors_covers_expected_branches(capsys):
    class _FakeProcessError(Exception):
        pass

    class _FakeLogger:
        def __init__(self):
            self.error_messages = []
            self.info_messages = []

        def error(self, message, *args):
            self.error_messages.append(message % args if args else message)

        def info(self, message, *args):
            self.info_messages.append(message % args if args else message)

        def isEnabledFor(self, _level):
            return False

    async def _raise_process(_scheduler):
        raise _FakeProcessError("process failed")

    async def _raise_connection(_scheduler):
        raise ConnectionError("scheduler unavailable")

    async def _raise_missing(_scheduler):
        raise ModuleNotFoundError("missing module")

    process_log = _FakeLogger()
    process_result = await entrypoint_support._run_main_with_handled_errors(
        SimpleNamespace(_main=_raise_process),
        "127.0.0.1",
        process_error_type=_FakeProcessError,
        format_exception_chain_fn=str,
        traceback_format_exc_fn=lambda: "tb",
        log=process_log,
    )
    assert process_result is None
    assert process_log.error_messages == ["failed to run \nprocess failed"]

    connection_log = _FakeLogger()
    connection_result = await entrypoint_support._run_main_with_handled_errors(
        SimpleNamespace(_main=_raise_connection),
        "127.0.0.1",
        process_error_type=_FakeProcessError,
        format_exception_chain_fn=str,
        traceback_format_exc_fn=lambda: "tb",
        log=connection_log,
    )
    assert connection_result == {
        "status": "error",
        "message": "scheduler unavailable",
        "kind": "connection",
    }
    assert connection_log.info_messages == ["scheduler unavailable"]
    assert "scheduler unavailable" in capsys.readouterr().err

    missing_log = _FakeLogger()
    missing_result = await entrypoint_support._run_main_with_handled_errors(
        SimpleNamespace(_main=_raise_missing),
        "127.0.0.1",
        process_error_type=_FakeProcessError,
        format_exception_chain_fn=str,
        traceback_format_exc_fn=lambda: "tb",
        log=missing_log,
    )
    assert missing_result is None
    assert missing_log.error_messages == ["failed to load module \nmissing module"]


@pytest.mark.asyncio
async def test_run_main_with_handled_errors_logs_and_reraises_unexpected_exception():
    class _FakeProcessError(Exception):
        pass

    class _FakeLogger:
        def __init__(self):
            self.error_messages = []
            self.debug_messages = []

        def error(self, message, *args):
            self.error_messages.append(message % args if args else message)

        def info(self, *_args, **_kwargs):
            return None

        def isEnabledFor(self, _level):
            return True

        def debug(self, message, *args):
            self.debug_messages.append(message % args if args else message)

    async def _raise_runtime(_scheduler):
        raise RuntimeError("unexpected failure")

    fake_logger = _FakeLogger()
    with pytest.raises(RuntimeError, match="unexpected failure"):
        await entrypoint_support._run_main_with_handled_errors(
            SimpleNamespace(_main=_raise_runtime),
            "127.0.0.1",
            process_error_type=_FakeProcessError,
            format_exception_chain_fn=lambda exc: f"chain:{exc}",
            traceback_format_exc_fn=lambda: "traceback-body",
            log=fake_logger,
        )

    assert fake_logger.error_messages == ["Unhandled exception in AGI.run: chain:unexpected failure"]
    assert fake_logger.debug_messages == ["Traceback:\ntraceback-body"]


@pytest.mark.asyncio
async def test_connect_scheduler_with_retry_succeeds_after_retry():
    attempts = {"n": 0}

    async def _fake_client(_address, heartbeat_interval=5000, timeout=1.0):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("not ready")
        return {"connected": True, "timeout": timeout, "heartbeat": heartbeat_interval}

    async def _fake_sleep(_delay):
        return None

    client = await entrypoint_support.connect_scheduler_with_retry(
        "tcp://127.0.0.1:8786",
        timeout=2.0,
        client_factory=_fake_client,
        sleep_fn=_fake_sleep,
    )
    assert client["connected"] is True
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_connect_scheduler_with_retry_times_out():
    async def _fake_client(_address, heartbeat_interval=5000, timeout=1.0):
        raise RuntimeError("never ready")

    async def _fake_sleep(_delay):
        return None

    clock = {"t": 0.0}

    def _monotonic():
        clock["t"] += 0.25
        return clock["t"]

    with pytest.raises(RuntimeError, match="Failed to instantiate Dask Client"):
        await entrypoint_support.connect_scheduler_with_retry(
            "tcp://127.0.0.1:8786",
            timeout=0.1,
            client_factory=_fake_client,
            sleep_fn=_fake_sleep,
            monotonic_fn=_monotonic,
        )


@pytest.mark.asyncio
async def test_connect_scheduler_with_retry_propagates_unexpected_value_error():
    async def _fake_client(_address, heartbeat_interval=5000, timeout=1.0):
        raise ValueError("programmer bug")

    async def _fake_sleep(_delay):
        return None

    with pytest.raises(ValueError, match="programmer bug"):
        await entrypoint_support.connect_scheduler_with_retry(
            "tcp://127.0.0.1:8786",
            timeout=2.0,
            client_factory=_fake_client,
            sleep_fn=_fake_sleep,
        )


@pytest.mark.asyncio
async def test_detect_export_cmd_local_and_remote(monkeypatch):
    assert await entrypoint_support.detect_export_cmd(
        AGI,
        "127.0.0.1",
        is_local_fn=lambda ip: ip == "127.0.0.1",
        local_export_bin="LOCAL_PREFIX ",
    ) == "LOCAL_PREFIX "

    async def _fake_exec(_ip, _cmd):
        return "Linux"

    monkeypatch.setattr(AGI, "exec_ssh", staticmethod(_fake_exec))
    assert await entrypoint_support.detect_export_cmd(
        AGI,
        "10.0.0.2",
        is_local_fn=lambda _ip: False,
        local_export_bin="LOCAL_PREFIX ",
    ) == 'export PATH="$HOME/.local/bin:$PATH";'


@pytest.mark.asyncio
async def test_detect_export_cmd_returns_empty_for_non_posix(monkeypatch):
    async def _fake_exec(_ip, _cmd):
        return "Windows_NT"

    monkeypatch.setattr(AGI, "exec_ssh", staticmethod(_fake_exec))
    assert await entrypoint_support.detect_export_cmd(
        AGI,
        "10.0.0.3",
        is_local_fn=lambda _ip: False,
        local_export_bin="LOCAL_PREFIX ",
    ) == ""


@pytest.mark.asyncio
async def test_detect_export_cmd_propagates_unexpected_value_error(monkeypatch):
    async def _fake_exec(_ip, _cmd):
        raise ValueError("bad command builder")

    monkeypatch.setattr(AGI, "exec_ssh", staticmethod(_fake_exec))
    with pytest.raises(ValueError, match="bad command builder"):
        await entrypoint_support.detect_export_cmd(
            AGI,
            "10.0.0.4",
            is_local_fn=lambda _ip: False,
            local_export_bin="LOCAL_PREFIX ",
        )


@pytest.mark.asyncio
async def test_resolve_scheduler_cmd_prefix_propagates_unexpected_value_error(monkeypatch):
    AGI.env = SimpleNamespace(envars={})
    AGI._scheduler_ip = "10.0.0.9"

    async def _fake_detect(_ip):
        raise ValueError("bad detect")

    monkeypatch.setattr(AGI, "_detect_export_cmd", staticmethod(_fake_detect))

    with pytest.raises(ValueError, match="bad detect"):
        await entrypoint_support._resolve_scheduler_cmd_prefix(
            AGI,
            set_env_var_fn=lambda *_args, **_kwargs: None,
        )


@pytest.mark.asyncio
async def test_start_scheduler_wraps_retryable_connect_error(monkeypatch, tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir()
    cluster_pck = tmp_path / "cluster"
    (cluster_pck / "agi_distributor").mkdir(parents=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')\n", encoding="utf-8")

    env = SimpleNamespace(
        wenv_rel=Path("wenv/demo_worker"),
        wenv_abs=tmp_path / "wenv" / "demo_worker",
        active_app=app_path,
        cluster_pck=cluster_pck,
        envars={},
        uv="uv",
        export_local_bin="",
        app="demo",
        hw_rapids_capable=False,
        is_local=lambda ip: True,
    )
    env.wenv_abs.mkdir(parents=True)
    AGI.env = env
    AGI._mode_auto = True
    AGI._mode = AGI.DASK_MODE
    AGI._workers = {"127.0.0.1": 1}
    AGI._TIMEOUT = 1
    AGI._worker_init_error = False
    AGI._scheduler = "127.0.0.1:8799"

    async def _fake_send_file(*_args, **_kwargs):
        return None

    async def _fake_kill(*_args, **_kwargs):
        return None

    async def _fake_wait_for_port_release(*_args, **_kwargs):
        return True

    async def _fake_detect_export_cmd(*_args, **_kwargs):
        return ""

    async def _fake_connect_scheduler_with_retry(*_args, **_kwargs):
        raise ConnectionError("client boom")

    async def _fake_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(AGI, "send_file", staticmethod(_fake_send_file))
    monkeypatch.setattr(AGI, "_kill", staticmethod(_fake_kill))
    monkeypatch.setattr(AGI, "_wait_for_port_release", staticmethod(_fake_wait_for_port_release))
    monkeypatch.setattr(AGI, "_detect_export_cmd", staticmethod(_fake_detect_export_cmd))
    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fake_connect_scheduler_with_retry))
    monkeypatch.setattr(AGI, "_exec_bg", staticmethod(lambda *_args, **_kwargs: None))
    monkeypatch.setattr(AGI, "_dask_env_prefix", staticmethod(lambda: ""))
    monkeypatch.setattr(AGI, "_get_scheduler", staticmethod(lambda _scheduler: ("127.0.0.1", 8799)))

    with pytest.raises(RuntimeError, match="Failed to instantiate Dask Client"):
        await entrypoint_support.start_scheduler(
            AGI,
            "127.0.0.1",
            set_env_var_fn=lambda *_args, **_kwargs: None,
            create_task_fn=lambda coro: coro,
            sleep_fn=_fake_sleep,
        )


@pytest.mark.asyncio
async def test_start_scheduler_propagates_unexpected_connect_bug(monkeypatch, tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir()
    cluster_pck = tmp_path / "cluster"
    (cluster_pck / "agi_distributor").mkdir(parents=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')\n", encoding="utf-8")

    env = SimpleNamespace(
        wenv_rel=Path("wenv/demo_worker"),
        wenv_abs=tmp_path / "wenv" / "demo_worker",
        active_app=app_path,
        cluster_pck=cluster_pck,
        envars={},
        uv="uv",
        export_local_bin="",
        app="demo",
        hw_rapids_capable=False,
        is_local=lambda ip: True,
    )
    env.wenv_abs.mkdir(parents=True)
    AGI.env = env
    AGI._mode_auto = True
    AGI._mode = AGI.DASK_MODE
    AGI._workers = {"127.0.0.1": 1}
    AGI._TIMEOUT = 1
    AGI._worker_init_error = False
    AGI._scheduler = "127.0.0.1:8799"

    async def _fake_send_file(*_args, **_kwargs):
        return None

    async def _fake_kill(*_args, **_kwargs):
        return None

    async def _fake_wait_for_port_release(*_args, **_kwargs):
        return True

    async def _fake_detect_export_cmd(*_args, **_kwargs):
        return ""

    async def _fake_connect_scheduler_with_retry(*_args, **_kwargs):
        raise ValueError("client bug")

    async def _fake_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(AGI, "send_file", staticmethod(_fake_send_file))
    monkeypatch.setattr(AGI, "_kill", staticmethod(_fake_kill))
    monkeypatch.setattr(AGI, "_wait_for_port_release", staticmethod(_fake_wait_for_port_release))
    monkeypatch.setattr(AGI, "_detect_export_cmd", staticmethod(_fake_detect_export_cmd))
    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fake_connect_scheduler_with_retry))
    monkeypatch.setattr(AGI, "_exec_bg", staticmethod(lambda *_args, **_kwargs: None))
    monkeypatch.setattr(AGI, "_dask_env_prefix", staticmethod(lambda: ""))
    monkeypatch.setattr(AGI, "_get_scheduler", staticmethod(lambda _scheduler: ("127.0.0.1", 8799)))

    with pytest.raises(ValueError, match="client bug"):
        await entrypoint_support.start_scheduler(
            AGI,
            "127.0.0.1",
            set_env_var_fn=lambda *_args, **_kwargs: None,
            create_task_fn=lambda coro: coro,
            sleep_fn=_fake_sleep,
        )


@pytest.mark.asyncio
async def test_update_get_distrib_and_distribute_delegate_to_run(monkeypatch):
    calls = []

    async def _fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": kwargs["request"].mode}

    monkeypatch.setattr(AGI, "run", staticmethod(_fake_run))

    env = SimpleNamespace()
    await entrypoint_support.update(
        AGI,
        env=env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        modes_enabled=AGI.DASK_MODE,
        args={"upgrade": True},
    )
    distrib = await entrypoint_support.get_distrib(
        AGI,
        env=env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        args={"simulate": True},
    )
    alias = await entrypoint_support.distribute(
        AGI,
        env=env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        args={"alias": True},
    )

    assert AGI._run_type == "simulate"
    assert calls[0][1]["request"].mode == ((AGI._UPDATE_MODE | AGI.DASK_MODE) & AGI._DASK_RESET)
    assert calls[1][0] == (env,)
    assert calls[1][1]["request"].scheduler == "127.0.0.1"
    assert calls[1][1]["request"].workers == {"127.0.0.1": 1}
    assert calls[1][1]["request"].mode == AGI._SIMULATE_MODE
    assert distrib == {"ok": AGI._SIMULATE_MODE}
    assert alias == {"ok": AGI._SIMULATE_MODE}


@pytest.mark.asyncio
async def test_detect_export_cmd_expected_lookup_error_returns_empty(monkeypatch):
    async def _fake_exec(_ip, _cmd):
        raise RuntimeError("expected lookup failure")

    monkeypatch.setattr(AGI, "exec_ssh", staticmethod(_fake_exec))

    assert await entrypoint_support.detect_export_cmd(
        AGI,
        "10.0.0.7",
        is_local_fn=lambda _ip: False,
        local_export_bin="LOCAL ",
    ) == ""


@pytest.mark.asyncio
async def test_prepare_scheduler_nodes_defaults_local_scheduler_and_handles_missing_remote_scheduler(monkeypatch, tmp_path):
    cluster_pck = tmp_path / "cluster"
    cli_path = cluster_pck / "agi_distributor" / "cli.py"
    cli_path.parent.mkdir(parents=True, exist_ok=True)
    cli_path.write_text("print('cli')\n", encoding="utf-8")

    calls = {"send": [], "kill": [], "info": []}

    async def _fake_send(_env, ip, local_path, remote_path):
        calls["send"].append((ip, local_path, remote_path))

    async def _fake_kill(ip, _pid, force=True):
        calls["kill"].append((ip, force))

    log = SimpleNamespace(info=lambda message, *args: calls["info"].append(message % args if args else message))

    AGI.env = SimpleNamespace(cluster_pck=cluster_pck, envars={}, hw_rapids_capable=False)
    AGI._mode_auto = False
    AGI._mode = AGI.DASK_MODE
    AGI._workers = {"127.0.0.1": 1}
    monkeypatch.setattr(AGI, "send_file", staticmethod(_fake_send))
    monkeypatch.setattr(AGI, "_kill", staticmethod(_fake_kill))
    monkeypatch.setattr(AGI, "_get_scheduler", staticmethod(lambda _scheduler: ("127.0.0.1", 8786)))

    scheduler = await entrypoint_support._prepare_scheduler_nodes(
        AGI,
        None,
        cli_rel=Path("worker/cli.py"),
        log=log,
    )

    assert scheduler == "127.0.0.1"
    assert calls["kill"] == [("127.0.0.1", True)]

    calls = {"send": [], "kill": [], "info": []}
    AGI._workers = {"10.0.0.2": 1}
    monkeypatch.setattr(AGI, "_get_scheduler", staticmethod(lambda _scheduler: ("10.0.0.1", 8786)))

    scheduler = await entrypoint_support._prepare_scheduler_nodes(
        AGI,
        None,
        cli_rel=Path("worker/cli.py"),
        log=log,
    )

    assert scheduler is None
    assert any("required -> Stop" in message for message in calls["info"])
    assert ("10.0.0.1", True) in calls["kill"]


@pytest.mark.asyncio
async def test_resolve_scheduler_cmd_prefix_ignores_expected_detect_error(monkeypatch):
    AGI.env = SimpleNamespace(envars={})
    AGI._scheduler_ip = "10.0.0.9"
    updates = []

    async def _fake_detect(_ip):
        raise RuntimeError("expected detect failure")

    monkeypatch.setattr(AGI, "_detect_export_cmd", staticmethod(_fake_detect))

    prefix = await entrypoint_support._resolve_scheduler_cmd_prefix(
        AGI,
        set_env_var_fn=lambda *args: updates.append(args),
    )

    assert prefix == ""
    assert updates == []


@pytest.mark.asyncio
async def test_launch_scheduler_process_local_logs_background_result(monkeypatch, tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir()
    (app_path / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")

    calls = {"info": []}
    AGI.env = SimpleNamespace(
        active_app=app_path,
        wenv_rel=Path("worker"),
        wenv_abs=tmp_path / "worker",
        uv="uv",
        export_local_bin="",
        app="demo",
        is_local=lambda _ip: True,
    )
    AGI.env.wenv_abs.mkdir(parents=True, exist_ok=True)
    AGI._scheduler_ip = "127.0.0.1"
    AGI._scheduler_port = 8786
    monkeypatch.setattr(AGI, "_dask_env_prefix", staticmethod(lambda: ""))
    monkeypatch.setattr(AGI, "_exec_bg", staticmethod(lambda *_args, **_kwargs: "started"))

    log = SimpleNamespace(info=lambda message, *args: calls["info"].append(message % args if args else message))

    async def _fake_sleep(_delay):
        return None

    await entrypoint_support._launch_scheduler_process(
        AGI,
        cmd_prefix="",
        create_task_fn=lambda coro: coro,
        sleep_fn=_fake_sleep,
        log=log,
    )

    assert "started" in calls["info"]


@pytest.mark.asyncio
async def test_launch_scheduler_process_remote_sends_pyproject_and_starts_async_worker(monkeypatch, tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir()
    (app_path / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")

    calls = {"exec": [], "send": [], "tasks": []}
    AGI.env = SimpleNamespace(
        active_app=app_path,
        wenv_rel=Path("worker"),
        wenv_abs=tmp_path / "worker",
        uv="uv",
        export_local_bin="",
        app="demo",
        is_local=lambda _ip: False,
    )
    AGI._scheduler_ip = "10.0.0.2"
    AGI._scheduler_port = 8786

    async def _fake_exec_ssh(ip, cmd):
        calls["exec"].append((ip, cmd))

    async def _fake_send(_env, ip, local_path, remote_path):
        calls["send"].append((ip, local_path, remote_path))

    monkeypatch.setattr(AGI, "_dask_env_prefix", staticmethod(lambda: "ENV=1 "))
    monkeypatch.setattr(AGI, "exec_ssh", staticmethod(_fake_exec_ssh))
    monkeypatch.setattr(AGI, "send_file", staticmethod(_fake_send))
    monkeypatch.setattr(
        AGI,
        "exec_ssh_async",
        staticmethod(lambda ip, cmd: ("exec_ssh_async", ip, cmd)),
    )

    async def _fake_sleep(_delay):
        return None

    await entrypoint_support._launch_scheduler_process(
        AGI,
        cmd_prefix="PREFIX ",
        create_task_fn=lambda task: calls["tasks"].append(task),
        sleep_fn=_fake_sleep,
    )

    assert calls["exec"]
    assert calls["send"][0][1] == app_path / "pyproject.toml"
    assert calls["send"][0][2] == Path("worker") / "pyproject.toml"
    assert calls["tasks"][0][0] == "exec_ssh_async"


@pytest.mark.asyncio
async def test_start_scheduler_reraises_runtime_error_and_worker_init_error(monkeypatch, tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir()
    cluster_pck = tmp_path / "cluster"
    (cluster_pck / "agi_distributor").mkdir(parents=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')\n", encoding="utf-8")

    env = SimpleNamespace(
        wenv_rel=Path("wenv/demo_worker"),
        wenv_abs=tmp_path / "wenv" / "demo_worker",
        active_app=app_path,
        cluster_pck=cluster_pck,
        envars={},
        uv="uv",
        export_local_bin="",
        app="demo",
        hw_rapids_capable=False,
        is_local=lambda ip: True,
    )
    env.wenv_abs.mkdir(parents=True)
    AGI.env = env
    AGI._mode_auto = True
    AGI._mode = AGI.DASK_MODE
    AGI._workers = {"127.0.0.1": 1}
    AGI._TIMEOUT = 1
    AGI._scheduler = "127.0.0.1:8799"

    async def _fake_send_file(*_args, **_kwargs):
        return None

    async def _fake_kill(*_args, **_kwargs):
        return None

    async def _fake_wait_for_port_release(*_args, **_kwargs):
        return True

    async def _fake_detect_export_cmd(*_args, **_kwargs):
        return ""

    async def _fake_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(AGI, "send_file", staticmethod(_fake_send_file))
    monkeypatch.setattr(AGI, "_kill", staticmethod(_fake_kill))
    monkeypatch.setattr(AGI, "_wait_for_port_release", staticmethod(_fake_wait_for_port_release))
    monkeypatch.setattr(AGI, "_detect_export_cmd", staticmethod(_fake_detect_export_cmd))
    monkeypatch.setattr(AGI, "_exec_bg", staticmethod(lambda *_args, **_kwargs: None))
    monkeypatch.setattr(AGI, "_dask_env_prefix", staticmethod(lambda: ""))
    monkeypatch.setattr(AGI, "_get_scheduler", staticmethod(lambda _scheduler: ("127.0.0.1", 8799)))

    async def _raise_runtime(*_args, **_kwargs):
        raise RuntimeError("retry exhausted")

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_raise_runtime))
    AGI._worker_init_error = False
    with pytest.raises(RuntimeError, match="retry exhausted"):
        await entrypoint_support.start_scheduler(
            AGI,
            "127.0.0.1",
            set_env_var_fn=lambda *_args, **_kwargs: None,
            create_task_fn=lambda coro: coro,
            sleep_fn=_fake_sleep,
        )

    async def _connect_ok(*_args, **_kwargs):
        return "client"

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_connect_ok))
    AGI._worker_init_error = True
    with pytest.raises(FileNotFoundError, match="Please run AGI.install"):
        await entrypoint_support.start_scheduler(
            AGI,
            "127.0.0.1",
            set_env_var_fn=lambda *_args, **_kwargs: None,
            create_task_fn=lambda coro: coro,
            sleep_fn=_fake_sleep,
        )
