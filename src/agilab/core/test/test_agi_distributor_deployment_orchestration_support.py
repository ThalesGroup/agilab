from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import deployment_orchestration_support


def test_reset_deploy_state_initializes_flags():
    agi_cls = SimpleNamespace(
        _run_types=["run", "sync", "upgrade", "simulate"],
        _mode=4,
        _DEPLOYEMENT_MASK=0b110000,
        _install_done_local=True,
        _install_done=True,
        _worker_init_error=True,
        _run_type=None,
    )

    deployment_orchestration_support.reset_deploy_state(agi_cls)

    assert agi_cls._run_type == "run"
    assert agi_cls._install_done_local is False
    assert agi_cls._install_done is False
    assert agi_cls._worker_init_error is False


@pytest.mark.asyncio
async def test_clean_remote_procs_only_non_local():
    called = []

    async def _fake_kill(ip, _current_pid, force=True):
        called.append((ip, force))
        return None

    agi_cls = SimpleNamespace(_kill=_fake_kill)

    await deployment_orchestration_support.clean_remote_procs(
        agi_cls,
        {"127.0.0.1", "10.0.0.2"},
        force=False,
        is_local_fn=lambda ip: ip == "127.0.0.1",
    )

    assert called == [("10.0.0.2", False)]


@pytest.mark.asyncio
async def test_clean_remote_dirs_runs_for_all():
    called = []

    async def _fake_clean(ip):
        called.append(ip)

    agi_cls = SimpleNamespace(_clean_dirs=_fake_clean)

    await deployment_orchestration_support.clean_remote_dirs(
        agi_cls,
        {"127.0.0.1", "10.0.0.2"},
    )

    assert set(called) == {"127.0.0.1", "10.0.0.2"}


@pytest.mark.asyncio
async def test_clean_nodes_runs_local_and_remote_cleanup():
    calls = {"local": 0, "procs": None, "dirs": None}

    def _clean_local():
        calls["local"] += 1

    async def _clean_procs(*, list_ip, force=True):
        calls["procs"] = (set(list_ip), force)

    async def _clean_dirs(*, list_ip):
        calls["dirs"] = set(list_ip)

    agi_cls = SimpleNamespace(
        _workers={"127.0.0.1": 1, "10.0.0.2": 1},
        _get_scheduler=lambda _addr=None: ("127.0.0.1", 8786),
        _clean_dirs_local=_clean_local,
        _clean_remote_procs=_clean_procs,
        _clean_remote_dirs=_clean_dirs,
    )

    list_ip = await deployment_orchestration_support.clean_nodes(
        agi_cls,
        "127.0.0.1:8786",
        force=True,
        is_local_fn=lambda ip: ip == "127.0.0.1",
        gethostbyname_fn=lambda _name: "127.0.0.1",
    )

    assert set(list_ip) == {"127.0.0.1", "10.0.0.2"}
    assert calls["local"] >= 1
    assert calls["procs"][1] is True
    assert calls["dirs"] == {"127.0.0.1", "10.0.0.2"}


@pytest.mark.asyncio
async def test_deploy_application_calls_local_and_remote_workers():
    calls = {"local": [], "remote": [], "todo": []}
    env = SimpleNamespace(
        active_app=Path("/tmp/demo_app"),
        wenv_rel=Path("wenv"),
        base_worker_cls="PandasWorker",
        verbose=1,
        is_local=lambda ip: ip == "127.0.0.1",
    )

    async def _fake_local(src, wenv_rel, options):
        calls["local"].append((str(src), str(wenv_rel), options))

    async def _fake_remote(ip, _env, wenv_rel, options):
        calls["remote"].append((ip, str(wenv_rel), options))

    agi_cls = SimpleNamespace(
        _run_types=["run --no-sync", "sync --dev", "sync --upgrade --dev", "simulate"],
        _mode=0b0100,
        _DEPLOYEMENT_MASK=0b110000,
        DASK_MODE=0b0100,
        _workers={"127.0.0.1": 1, "10.0.0.2": 1},
        install_worker_group=["pandas-worker"],
        env=env,
        verbose=0,
        _get_scheduler=lambda _scheduler: ("127.0.0.1", 8786),
        _venv_todo=lambda node_ips: calls["todo"].append(set(node_ips)),
        _deploy_local_worker=_fake_local,
        _deploy_remote_worker=_fake_remote,
    )

    await deployment_orchestration_support.deploy_application(agi_cls, "127.0.0.1")

    assert calls["local"] == [("/tmp/demo_app", "wenv", " --extra pandas-worker")]
    assert calls["remote"] == [("10.0.0.2", "wenv", " --extra pandas-worker")]
    assert calls["todo"][0] == {"127.0.0.1", "10.0.0.2"}


@pytest.mark.asyncio
async def test_deploy_application_local_mode_skips_remote_workers():
    calls = {"local": [], "remote": [], "todo": []}
    env = SimpleNamespace(
        active_app=Path("/tmp/demo_app"),
        wenv_rel=Path("wenv"),
        base_worker_cls="PandasWorker",
        verbose=0,
        is_local=lambda ip: ip == "127.0.0.1",
    )

    async def _fake_local(src, wenv_rel, options):
        calls["local"].append((str(src), str(wenv_rel), options))

    async def _fake_remote(ip, _env, wenv_rel, options):
        calls["remote"].append((ip, str(wenv_rel), options))

    agi_cls = SimpleNamespace(
        _run_types=["run --no-sync", "sync --dev", "sync --upgrade --dev", "simulate"],
        _mode=0b0001,
        _DEPLOYEMENT_MASK=0b110000,
        DASK_MODE=0b0100,
        _workers={"127.0.0.1": 1, "10.0.0.2": 1},
        install_worker_group=["pandas-worker"],
        env=env,
        verbose=0,
        _get_scheduler=lambda _scheduler: ("127.0.0.1", 8786),
        _venv_todo=lambda node_ips: calls["todo"].append(set(node_ips)),
        _deploy_local_worker=_fake_local,
        _deploy_remote_worker=_fake_remote,
    )

    await deployment_orchestration_support.deploy_application(agi_cls, "127.0.0.1")

    assert calls["local"] == [("/tmp/demo_app", "wenv", " --extra pandas-worker")]
    assert calls["remote"] == []
    assert calls["todo"][0] == {"127.0.0.1", "10.0.0.2"}
