"""Bounded cleanup of explicitly owned synthetic background process handles."""
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agi_cluster.agi_distributor.runtime import runtime_distribution_support as runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_phase,failure,expected", [
    ("terminate", ProcessLookupError(), None),
    ("terminate", OSError("denied"), "termination"),
    ("wait", ProcessLookupError(), None),
    ("wait", OSError("denied"), "wait"),
    ("kill", ProcessLookupError(), None),
    ("kill", OSError("denied"), "kill/wait"),
    ("second_wait", subprocess.TimeoutExpired("fake", 1), "kill/wait"),
    ("second_wait", OSError("denied"), "kill/wait"),
    ("second_wait", ProcessLookupError(), None),
])
async def test_legacy_cleanup_reports_exact_failed_phase(failure_phase, failure, expected):
    process = SimpleNamespace(pid=123, poll=Mock(return_value=None), terminate=Mock(), kill=Mock(), wait=Mock())
    if failure_phase == "terminate":
        process.terminate.side_effect = failure
    elif failure_phase == "wait":
        process.wait.side_effect = failure
    else:
        process.wait.side_effect = [subprocess.TimeoutExpired("fake", 1), failure if failure_phase == "second_wait" else None]
        if failure_phase == "kill":
            process.kill.side_effect = failure
    result = await runtime._terminate_legacy_background_process(process, timeout=1)
    if expected is None:
        assert result is None
    else:
        assert result[0] == "background process 123 " + expected
        assert result[1] is failure
    if failure_phase in ("terminate", "wait"):
        process.kill.assert_not_called()
    else:
        process.kill.assert_called_once_with()


@pytest.mark.asyncio
async def test_completed_legacy_process_is_never_signalled():
    process = SimpleNamespace(pid=123, poll=Mock(return_value=0), terminate=Mock(), kill=Mock())
    assert await runtime._terminate_legacy_background_process(process, timeout=1) is None
    process.terminate.assert_not_called()
    process.kill.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_cleanup_escalates_once_after_timeout():
    process = SimpleNamespace(pid=123, poll=Mock(return_value=None), terminate=Mock(), kill=Mock(),
                              wait=Mock(side_effect=[subprocess.TimeoutExpired("fake", 1), 0]))
    assert await runtime._terminate_legacy_background_process(process, timeout=1) is None
    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert process.wait.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["posix", "nt"])
@pytest.mark.parametrize("failure", [False, True])
async def test_owned_job_retained_until_tree_cleanup_proven(monkeypatch, platform, failure):
    process = SimpleNamespace(pid=123)
    job = SimpleNamespace(process=process, num=1, ownership_token="owned")
    manager = SimpleNamespace(owned=[job], running=[job], completed=[job], dead=[job], all={1: job})
    runtime_state = SimpleNamespace(_jobs=manager)
    tree = Mock(side_effect=OSError("cleanup unproven") if failure else None)
    other = Mock(side_effect=AssertionError("wrong platform cleanup"))
    monkeypatch.setattr(runtime, "os", SimpleNamespace(name=platform))
    monkeypatch.setattr(runtime, "_terminate_posix_owned_process_tree", tree if platform == "posix" else other)
    monkeypatch.setattr(runtime, "_terminate_token_process_tree", tree if platform != "posix" else other)
    if failure:
        with pytest.raises(runtime.RuntimeCleanupRequiredError, match="cleanup unproven"):
            await runtime._terminate_owned_background_jobs(runtime_state, timeout=1, log=Mock())
        assert manager.owned == [job]
        assert manager.all == {1: job}
    else:
        await runtime._terminate_owned_background_jobs(runtime_state, timeout=1, log=Mock())
        assert manager.owned == manager.running == manager.completed == manager.dead == []
        assert manager.all == {}
    tree.assert_called_once_with(job, timeout=1)
    other.assert_not_called()


@pytest.mark.asyncio
async def test_job_without_process_handle_remains_owned():
    job = SimpleNamespace(num=1)
    manager = SimpleNamespace(owned=[job], running=[])
    with pytest.raises(runtime.RuntimeCleanupRequiredError, match="no process handle"):
        await runtime._terminate_owned_background_jobs(SimpleNamespace(_jobs=manager), timeout=1, log=Mock())
    assert manager.owned == [job]


@pytest.mark.asyncio
async def test_failed_legacy_job_retains_ownership_for_retry():
    process = SimpleNamespace(pid=123, poll=Mock(return_value=None), terminate=Mock(side_effect=OSError("denied")))
    job = SimpleNamespace(num=1, process=process)
    manager = SimpleNamespace(owned=[job], running=[])
    with pytest.raises(runtime.RuntimeCleanupRequiredError, match="denied"):
        await runtime._terminate_owned_background_jobs(SimpleNamespace(_jobs=manager), timeout=1, log=Mock())
    assert manager.owned == [job]


def test_forget_job_preserves_other_generation_with_same_number():
    job = SimpleNamespace(num=1)
    replacement = object()
    manager = SimpleNamespace(owned=[job, job], running=None, all={1: replacement})
    runtime._forget_owned_background_job(manager, job)
    assert manager.owned == []
    assert manager.all == {1: replacement}


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["scheduler", "shutdown", "launch", "background", "connections"])
async def test_fatal_runtime_cleanup_still_attempts_remaining_owned_resources(monkeypatch, phase):
    from unittest.mock import AsyncMock
    error = KeyboardInterrupt("synthetic fatal cleanup failure")
    client = SimpleNamespace(scheduler_info=AsyncMock(return_value={"workers": {}}),
                             shutdown=AsyncMock(), retire_workers=AsyncMock())
    task = SimpleNamespace(done=lambda: False, cancel=Mock())
    background = AsyncMock()
    close = AsyncMock()
    if phase == "scheduler":
        client.scheduler_info.side_effect = error
    elif phase == "shutdown":
        client.shutdown.side_effect = error
    elif phase == "launch":
        task.cancel.side_effect = error
    elif phase == "background":
        background.side_effect = error
    else:
        close.side_effect = error
    state = SimpleNamespace(_dask_client=client, _mode_auto=False, _TIMEOUT="invalid",
                            _worker_launch_tasks=[task], _scheduler_launch_tasks=[],
                            _close_all_connections=close, _runtime_shutdown_client=object())
    monkeypatch.setattr(runtime, "_terminate_owned_background_jobs", background)
    with pytest.raises(KeyboardInterrupt) as raised:
        await runtime._stop_runtime_resources(state, sleep_fn=AsyncMock(), log=Mock())
    assert raised.value is error
    close.assert_awaited_once()
    background.assert_awaited_once()
    assert state._runtime_cleanup_phase == "recovery-required"


@pytest.mark.asyncio
async def test_fatal_cleanup_preserves_additional_connection_failure_notes(monkeypatch):
    from unittest.mock import AsyncMock
    fatal = KeyboardInterrupt("synthetic fatal")
    client = SimpleNamespace(scheduler_info=AsyncMock(return_value={"workers": {}}),
                             shutdown=AsyncMock(side_effect=fatal))
    state = SimpleNamespace(_dask_client=client, _close_all_connections=AsyncMock(side_effect=OSError("connection remains")),
                            _mode_auto=False)
    monkeypatch.setattr(runtime, "_terminate_owned_background_jobs", AsyncMock())
    with pytest.raises(KeyboardInterrupt) as raised:
        await runtime._stop_runtime_resources(state, sleep_fn=AsyncMock(), log=Mock())
    assert any("connection shutdown: connection remains" in note for note in raised.value.__notes__)


@pytest.mark.asyncio
async def test_retirement_failure_is_superseded_only_by_proven_full_shutdown(monkeypatch):
    from unittest.mock import AsyncMock
    client = SimpleNamespace(scheduler_info=AsyncMock(return_value={"workers": {"worker": {}}}),
                             shutdown=AsyncMock(), retire_workers=AsyncMock())
    task = SimpleNamespace(done=lambda: True, cancel=Mock())
    state = SimpleNamespace(_dask_client=client, _close_all_connections=AsyncMock(),
                            _mode_auto=False, _TIMEOUT=0, _worker_launch_tasks=[task])
    background = AsyncMock()
    monkeypatch.setattr(runtime, "_terminate_owned_background_jobs", background)
    await runtime._stop_runtime_resources(state, sleep_fn=AsyncMock(), log=Mock())
    assert state._dask_client is None
    assert state._runtime_cleanup_phase is None
    assert state._worker_launch_tasks == []
    task.cancel.assert_not_called()
    client.shutdown.assert_awaited_once()
    background.assert_awaited_once()
