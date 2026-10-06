"""Scheduler startup reports actual async failures before declaring installation."""

import asyncio
import shlex
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agi_cluster.agi_distributor.api import entrypoint_support as entrypoint


@pytest.fixture
def scheduler(tmp_path):
    app = tmp_path / "app with spaces"
    app.mkdir()
    (app / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    return SimpleNamespace(
        env=SimpleNamespace(
            active_app=app,
            wenv_rel=Path("worker with spaces"),
            wenv_abs=tmp_path / "worker",
            uv="uv",
            envars={"remote_CMD_PREFIX": ""},
            is_local=lambda _ip: False,
        ),
        _scheduler_ip="remote",
        _scheduler_port=8786,
        _scheduler="remote:8786",
        _TIMEOUT=1,
        _mode_auto=True,
        _mode=0,
        DASK_MODE=2,
        _worker_init_error=False,
        _install_done=False,
        _dask_env_prefix=lambda: "",
        _detect_export_cmd=AsyncMock(return_value=""),
        exec_ssh=AsyncMock(),
        send_file=AsyncMock(),
        _connect_scheduler_with_retry=AsyncMock(return_value=object()),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
async def test_remote_launch_done_callback_preserves_task_and_failure_identity(
    scheduler, outcome
):
    failure = OSError("remote scheduler executable missing")
    started = asyncio.Event()
    release = asyncio.Event()
    commands = []

    async def launch(ip, command):
        commands.append((ip, shlex.split(command)))
        started.set()
        await release.wait()
        if outcome == "failure":
            raise failure

    scheduler.exec_ssh_async = launch
    # Startup replaces stale incompatible containers left by another caller.
    scheduler._scheduler_launch_tasks = None
    scheduler._scheduler_launch_errors = None
    log = Mock()
    await entrypoint._launch_scheduler_process(
        scheduler,
        cmd_prefix="",
        create_task_fn=asyncio.create_task,
        sleep_fn=AsyncMock(),
        log=log,
    )
    assert len(scheduler._scheduler_launch_tasks) == 1
    task = next(iter(scheduler._scheduler_launch_tasks))
    await started.wait()
    if outcome == "cancelled":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        release.set()
        if outcome == "failure":
            with pytest.raises(OSError) as raised:
                await task
            assert raised.value is failure
        else:
            await task
    await asyncio.sleep(0)  # Let the real Task invoke its registered callback.

    assert task in scheduler._scheduler_launch_tasks
    assert commands[0][0] == "remote"
    assert "worker with spaces/dask_scheduler.pid" in commands[0][1]
    scheduler.send_file.assert_awaited_once_with(
        scheduler.env,
        "remote",
        scheduler.env.active_app / "pyproject.toml",
        Path("worker with spaces/pyproject.toml"),
    )
    assert scheduler._scheduler_launch_errors == ([failure] if outcome == "failure" else [])
    if outcome == "failure":
        log.error.assert_called_once_with("Remote scheduler launch failed: %s", failure)
    else:
        log.error.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_phase", ["launch", "connect", "connect_runtime", "late_launch"])
async def test_scheduler_start_never_declares_installation_after_async_failure(
    scheduler, failure_phase
):
    failure = (RuntimeError if failure_phase == "connect_runtime" else OSError)(
        "scheduler startup failed"
    )
    release = asyncio.Event()

    async def launch(_ip, _command):
        if failure_phase == "launch":
            raise failure
        if failure_phase == "late_launch":
            await release.wait()
            raise failure

    async def connect(*_args, **_kwargs):
        if failure_phase in {"connect", "connect_runtime"}:
            raise failure
        if failure_phase == "late_launch":
            release.set()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        return object()

    async def yield_to_launch(_delay):
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    scheduler.exec_ssh_async = launch
    scheduler._connect_scheduler_with_retry.side_effect = connect
    with pytest.raises((OSError, RuntimeError)) as raised:
        await entrypoint.start_scheduler(
            scheduler,
            "remote:8786",
            set_env_var_fn=Mock(),
            sleep_fn=yield_to_launch,
            log=Mock(),
        )
    assert scheduler._install_done is False
    if failure_phase == "connect":
        assert raised.value.__cause__ is failure
        assert str(raised.value) == "Failed to instantiate Dask Client"
    else:
        assert raised.value is failure
    if failure_phase == "launch":
        scheduler._connect_scheduler_with_retry.assert_not_awaited()
        assert not hasattr(scheduler, "_dask_client")
    else:
        scheduler._connect_scheduler_with_retry.assert_awaited_once()
    if failure_phase in {"connect", "connect_runtime"}:
        assert not hasattr(scheduler, "_dask_client")
    tasks = scheduler._scheduler_launch_tasks
    await asyncio.gather(*tasks, return_exceptions=True)
    assert all(task.done() for task in tasks)
