"""Service cleanup must prove execution stopped, not merely cancel a Future."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agi_cluster.agi_distributor.service import service_lifecycle_support as service
from agi_cluster.agi_distributor.runtime import runtime_distribution_support as runtime


@pytest.mark.parametrize("status,terminal", [("finished", True), ("ERROR", True), ("cancelled", False), ("pending", False), ("lost", False)])
def test_future_terminal_status_excludes_cancellation(status, terminal):
    assert service._future_execution_terminal(SimpleNamespace(status=status)) is terminal


def test_cancellation_failure_does_not_prevent_remaining_requests():
    first = SimpleNamespace(cancel=Mock(side_effect=RuntimeError("disconnected")))
    second = SimpleNamespace(cancel=Mock())
    log = Mock()
    assert not service._cancel_owned_futures([first, object(), second], log=log)
    second.cancel.assert_called_once_with()
    log.warning.assert_called_once()


@pytest.mark.parametrize("failure", [TimeoutError(), RuntimeError("transport"), asyncio.CancelledError()])
def test_wait_failure_cannot_prove_execution_stopped(failure):
    wait = Mock(side_effect=failure)
    assert not service._wait_for_execution_terminal([SimpleNamespace(status="pending")],
        wait_fn=wait, timeout=2, description="worker", log=Mock())
    assert wait.call_args.kwargs == {"timeout": 2}


@pytest.mark.parametrize("status,not_done,expected", [("finished", [], True), ("cancelled", [], False), ("pending", [1], False)])
def test_wait_return_requires_actual_terminal_status(status, not_done, expected):
    future = SimpleNamespace(status="pending")
    def wait(futures, **kwargs):
        assert futures == [future]
        assert kwargs == {}
        future.status = status
        return [future], not_done
    assert service._wait_for_execution_terminal([future], wait_fn=wait,
        timeout=None, description="worker", log=Mock()) is expected


def test_empty_or_already_terminal_futures_need_no_wait():
    wait = Mock(side_effect=AssertionError("unnecessary wait"))
    for futures in ([], [SimpleNamespace(status="error")]):
        assert service._wait_for_execution_terminal(futures, wait_fn=wait, timeout=0, description="worker")


@pytest.mark.asyncio
@pytest.mark.parametrize("connected", [[], ["a"], RuntimeError("disconnected")])
async def test_stop_reused_runtime_signals_only_owned_workers_and_retains_unproven_loops(connected):
    loops = {"a": SimpleNamespace(status="finished"), "b": SimpleNamespace(status="cancelled")}
    client = SimpleNamespace(submit=Mock(return_value=SimpleNamespace(status="finished")), gather=Mock())
    inspect = AsyncMock()
    if isinstance(connected, Exception):
        inspect.side_effect = connected
    else:
        inspect.return_value = connected
    agi = SimpleNamespace(_dask_client=client, _service_connected_workers=inspect,
                          _service_safe_worker_name=lambda worker: worker, _service_stop_timeout=0)
    remaining = await service._stop_owned_service_loops(agi, SimpleNamespace(target="demo"),
        loops, wait_fn=lambda *_args, **_kwargs: ([], []), log=Mock())
    assert remaining == {"b": loops["b"]}
    expected = ["a"] if connected == ["a"] else ["a", "b"]
    assert [call.kwargs["workers"][0] for call in client.submit.call_args_list] == expected
    assert all(call.kwargs["allow_other_workers"] is False for call in client.submit.call_args_list)
    client.gather.assert_called_once()


@pytest.mark.asyncio
async def test_stop_without_client_retains_all_owned_loops():
    loops = {"a": SimpleNamespace(status="pending")}
    assert await service._stop_owned_service_loops(SimpleNamespace(), object(), loops, wait_fn=Mock(), log=Mock()) == loops
    assert await service._stop_owned_service_loops(SimpleNamespace(), object(), {}, wait_fn=Mock(), log=Mock()) == {}


@pytest.mark.asyncio
async def test_break_submission_failure_cannot_claim_loop_stopped():
    loop = SimpleNamespace(status="pending")
    client = SimpleNamespace(submit=Mock(side_effect=RuntimeError("lost")), gather=Mock())
    agi = SimpleNamespace(_dask_client=client, _service_connected_workers=AsyncMock(return_value=["a"]),
                          _service_safe_worker_name=lambda x: x)
    assert await service._stop_owned_service_loops(agi, SimpleNamespace(target="demo"), {"a": loop},
        wait_fn=lambda *_args, **_kwargs: ([], [loop]), log=Mock()) == {"a": loop}
    client.gather.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled", "pending"])
async def test_cleanup_task_reuse_preserves_task_and_consumes_terminal_result(outcome):
    gate = asyncio.Event()
    async def clean():
        if outcome == "failure":
            raise RuntimeError("cleanup failed")
        if outcome in ("pending", "cancelled"):
            await gate.wait()
    task = asyncio.create_task(clean())
    await asyncio.sleep(0)
    if outcome == "cancelled":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    agi = SimpleNamespace(_runtime_cleanup_task=task, _service_cleanup_unproven=True,
                          _runtime_cleanup_phase="stopping")
    returned = runtime._reusable_runtime_cleanup_task(agi, log=Mock())
    if outcome == "success":
        assert returned is task
        assert agi._runtime_cleanup_task is None
        assert not agi._service_cleanup_unproven
        assert agi._runtime_cleanup_phase is None
    elif outcome == "pending":
        assert returned is task
        assert agi._runtime_cleanup_task is task
        gate.set()
        await task
    else:
        assert returned is None
        assert agi._runtime_cleanup_task is None
        assert agi._service_cleanup_unproven


@pytest.mark.asyncio
async def test_cleanup_drain_deadline_does_not_cancel_owned_cleanup():
    gate = asyncio.Event()
    task = asyncio.create_task(gate.wait())
    with pytest.raises(TimeoutError, match="exceeded its deadline"):
        await runtime._drain_owned_cleanup_task(task, timeout=0)
    assert not task.cancelled()
    assert not task.done()
    gate.set()
    await task


@pytest.mark.asyncio
async def test_cleanup_drain_returns_actual_result():
    async def clean():
        return "closed"
    task = asyncio.create_task(clean())
    assert await runtime._drain_owned_cleanup_task(task, timeout=1) == "closed"


@pytest.fixture
def restart_state():
    old = SimpleNamespace(status="finished", key="old")
    replacement = SimpleNamespace(status="pending", key="replacement")
    state = SimpleNamespace(
        _service_workers=["a"], _service_futures={"a": old},
        _service_cleanup_unproven=False,
        _service_connected_workers=AsyncMock(return_value=["a"]),
        _service_unhealthy_workers=Mock(return_value={"a": "unhealthy"}),
        _service_write_state=Mock(), _service_state_payload=Mock(return_value={"workers": ["a"]}),
    )
    async def restart(_env, _client, workers):
        assert workers == ["a"]
        state._service_futures = {"a": replacement}
        return ["a"]
    state._service_restart_workers = AsyncMock(side_effect=restart)
    return state, old, replacement


@pytest.mark.asyncio
async def test_healthy_service_does_not_restart_or_publish(restart_state):
    state, _, _ = restart_state
    state._service_unhealthy_workers.return_value = {}
    assert await service.service_auto_restart_unhealthy(state, object(), object()) == {"restarted": [], "reasons": {}}
    state._service_restart_workers.assert_not_awaited()
    state._service_write_state.assert_not_called()


@pytest.mark.asyncio
async def test_successful_auto_restart_publishes_replacement_ownership(restart_state):
    state, _, replacement = restart_state
    result = await service.service_auto_restart_unhealthy(state, object(), object())
    assert result == {"restarted": ["a"], "reasons": {"a": "unhealthy"}}
    assert state._service_futures == {"a": replacement}
    state._service_write_state.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_outcome,shutdown_fails", [("stopped", False), ("pending", False), ("pending", True), ("raises", True)])
async def test_auto_restart_publication_failure_keeps_unproven_replacement_owned(monkeypatch, restart_state, cleanup_outcome, shutdown_fails):
    state, old, replacement = restart_state
    publish_error = OSError("state disk unavailable")
    state._service_write_state.side_effect = publish_error
    cleanup = AsyncMock(return_value={} if cleanup_outcome == "stopped" else {"a": replacement})
    if cleanup_outcome == "raises":
        cleanup.side_effect = RuntimeError("loop cleanup unavailable")
    shutdown = AsyncMock()
    if shutdown_fails:
        shutdown.side_effect = RuntimeError("runtime cleanup unavailable")
    monkeypatch.setattr(service, "_stop_owned_service_loops", cleanup)
    monkeypatch.setattr(service, "_ensure_service_runtime_shutdown", shutdown)
    with pytest.raises(OSError, match="state disk unavailable") as raised:
        await service.service_auto_restart_unhealthy(state, object(), object(), wait_fn=Mock(), log=Mock())
    assert raised.value is publish_error
    if cleanup_outcome == "stopped":
        shutdown.assert_not_awaited()
        assert state._service_futures == {"a": old}
        assert not state._service_cleanup_unproven
    elif shutdown_fails:
        shutdown.assert_awaited_once_with(state)
        assert state._service_futures == {"a": replacement}
        assert state._service_cleanup_unproven
        assert any("shutdown also failed" in note for note in raised.value.__notes__)
        if cleanup_outcome == "raises":
            assert any("Replacement cleanup also failed" in note for note in raised.value.__notes__)
    else:
        shutdown.assert_awaited_once_with(state)
        assert state._service_futures == {"a": old}
    assert state._service_workers == ["a"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_outcome", ["pending", "raises"])
async def test_restart_cannot_replace_unproven_old_loop(monkeypatch, restart_state, stop_outcome):
    state, old, _ = restart_state
    stop = AsyncMock(return_value={"a": old})
    if stop_outcome == "raises":
        stop.side_effect = RuntimeError("cleanup failed")
    monkeypatch.setattr(service, "_stop_owned_service_loops", stop)
    initialize = Mock(side_effect=AssertionError("must not initialize replacement"))
    monkeypatch.setattr(service, "_submit_service_worker_inits", initialize)
    with pytest.raises(RuntimeError):
        await service.service_restart_workers(state, object(), object(), ["a"], wait_fn=Mock(), log=Mock())
    assert state._service_futures == {"a": old}
    assert state._service_cleanup_unproven
    initialize.assert_not_called()


@pytest.mark.asyncio
async def test_restart_requires_original_future_ownership(restart_state):
    state, _, _ = restart_state
    with pytest.raises(RuntimeError, match="original loop Future"):
        await service.service_restart_workers(state, object(), object(), ["unowned"], wait_fn=Mock(), log=Mock())
    assert state._service_cleanup_unproven
    assert await service.service_restart_workers(state, object(), object(), [], wait_fn=Mock()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_outcome,publish_fails,shutdown_fails", [
    ("stopped", False, False), ("pending", False, False),
    ("pending", True, False), ("pending", True, True), ("raises", True, True),
])
async def test_partial_restart_failure_retains_or_publishes_new_future_ownership(
    monkeypatch, restart_state, cleanup_outcome, publish_fails, shutdown_fails
):
    state, old, replacement = restart_state
    unrelated = SimpleNamespace(status="pending", key="unrelated")
    state._service_futures["b"] = unrelated
    state._service_connected_workers.return_value = ["a", "b"]
    restart_error = RuntimeError("replacement submission failed")
    monkeypatch.setattr(service, "_submit_service_worker_inits", Mock(return_value=["a"]))
    def partial_submit(*args, service_futures, **kwargs):
        service_futures["a"] = replacement
        raise restart_error
    monkeypatch.setattr(service, "_submit_service_loops", partial_submit)
    cleanup_second = RuntimeError("cleanup unavailable") if cleanup_outcome == "raises" else (
        {} if cleanup_outcome == "stopped" else {"a": replacement})
    monkeypatch.setattr(service, "_stop_owned_service_loops", AsyncMock(side_effect=[{}, cleanup_second]))
    shutdown = AsyncMock(side_effect=RuntimeError("shutdown unavailable") if shutdown_fails else None)
    monkeypatch.setattr(service, "_ensure_service_runtime_shutdown", shutdown)
    if publish_fails:
        state._service_write_state.side_effect = OSError("state disk unavailable")
    with pytest.raises(RuntimeError, match="replacement submission failed") as raised:
        await service.service_restart_workers(state, object(), object(), ["a"], wait_fn=Mock(), log=Mock())
    assert raised.value is restart_error
    assert state._service_futures["b"] is unrelated
    if cleanup_outcome == "stopped":
        assert "a" not in state._service_futures
        assert not state._service_cleanup_unproven
        state._service_write_state.assert_not_called()
    elif publish_fails and not shutdown_fails:
        assert state._service_futures["a"] is old
        assert state._service_workers == ["a", "b"]
    else:
        assert state._service_futures["a"] is replacement
        assert state._service_cleanup_unproven
    if publish_fails:
        shutdown.assert_awaited_once_with(state)
        assert any("ownership publication also failed" in note for note in raised.value.__notes__)
        if shutdown_fails:
            assert any("shutdown also failed" in note for note in raised.value.__notes__)
    else:
        shutdown.assert_not_awaited()
