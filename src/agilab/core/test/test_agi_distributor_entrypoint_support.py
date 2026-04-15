from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import AGI, entrypoint_support


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
