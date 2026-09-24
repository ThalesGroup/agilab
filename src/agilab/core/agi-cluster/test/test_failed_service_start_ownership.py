"""Failed service startup retains ownership until cleanup and publication are proven."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agi_cluster.agi_distributor.service import service_lifecycle_support as lifecycle


@pytest.fixture
def startup_state():
    future = SimpleNamespace(status="pending", key="loop-key", cancel=Mock())
    state = SimpleNamespace(
        _service_workers=["worker"], _service_futures={"worker": future}, _service_cleanup_unproven=False,
        _service_runtime_shutdown_proven=False, _jobs=None, _clean_job=Mock(),
        _service_write_state=Mock(), _service_state_payload=Mock(return_value={"keys": ["loop-key"]}),
        _service_clear_state=Mock(), _reset_service_queue_state=Mock(),
    )
    return state, future


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown_fails", [False, True])
async def test_new_runtime_start_failure_requires_actual_shutdown(monkeypatch, startup_state, shutdown_fails):
    state, future = startup_state
    shutdown = AsyncMock(side_effect=RuntimeError("shutdown failed") if shutdown_fails else None)
    monkeypatch.setattr(lifecycle, "_ensure_service_runtime_shutdown", shutdown)
    result = await lifecycle._cleanup_failed_service_start(state, object(), owned_futures={"worker": future},
                                                         runtime_started_here=True, wait_fn=Mock(), log=Mock())
    assert result is (not shutdown_fails)
    future.cancel.assert_called_once_with()
    shutdown.assert_awaited_once_with(state)
    assert state._service_cleanup_unproven is shutdown_fails
    if shutdown_fails:
        assert state._service_futures == {"worker": future}
        state._service_clear_state.assert_not_called()
    else:
        assert state._service_futures == {}
        assert state._service_workers == []
        state._service_clear_state.assert_called_once()
        state._reset_service_queue_state.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_phase", ["jobs", "persisted_state", "queue_state"])
async def test_local_cleanup_failure_retains_handles_after_runtime_shutdown(monkeypatch, startup_state, failure_phase):
    state, future = startup_state
    monkeypatch.setattr(lifecycle, "_ensure_service_runtime_shutdown", AsyncMock())
    if failure_phase == "jobs":
        state._jobs = object()
        state._clean_job.side_effect = RuntimeError("job cleanup failed")
    elif failure_phase == "persisted_state":
        state._service_clear_state.side_effect = OSError("state unlink failed")
    else:
        state._reset_service_queue_state.side_effect = OSError("queue reset failed")
    assert not await lifecycle._cleanup_failed_service_start(state, object(), owned_futures={"worker": future},
                                                             runtime_started_here=True, wait_fn=Mock(), log=Mock())
    assert state._service_cleanup_unproven
    assert state._service_futures == {"worker": future}
    assert state._service_workers == ["worker"]
    if failure_phase != "jobs":
        state._reset_service_queue_state.assert_called_once()


@pytest.mark.asyncio
async def test_reused_runtime_publishes_only_pending_owned_keys(monkeypatch, startup_state):
    state, future = startup_state
    completed = SimpleNamespace(status="finished", key="completed-key", cancel=Mock())
    state._service_futures["completed"] = completed
    state._service_workers.append("completed")
    stop = AsyncMock(return_value={"worker": future})
    shutdown = AsyncMock()
    monkeypatch.setattr(lifecycle, "_stop_owned_service_loops", stop)
    monkeypatch.setattr(lifecycle, "_ensure_service_runtime_shutdown", shutdown)
    assert not await lifecycle._cleanup_failed_service_start(state, object(),
        owned_futures={"worker": future, "completed": completed}, runtime_started_here=False, wait_fn=Mock(), log=Mock())
    state._service_write_state.assert_called_once()
    shutdown.assert_not_awaited()
    assert state._service_futures == {"worker": future}
    assert state._service_workers == ["worker"]
    assert state._service_cleanup_unproven


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["key_missing", "publication_failure"])
@pytest.mark.parametrize("shutdown_fails", [False, True])
async def test_unpublishable_pending_loop_requires_full_runtime_shutdown(monkeypatch, startup_state, reason, shutdown_fails):
    state, future = startup_state
    if reason == "key_missing":
        future.key = None
    else:
        state._service_write_state.side_effect = OSError("disk unavailable")
    monkeypatch.setattr(lifecycle, "_stop_owned_service_loops", AsyncMock(return_value={"worker": future}))
    shutdown = AsyncMock(side_effect=RuntimeError("shutdown unproven") if shutdown_fails else None)
    monkeypatch.setattr(lifecycle, "_ensure_service_runtime_shutdown", shutdown)
    result = await lifecycle._cleanup_failed_service_start(state, object(),
        owned_futures={"worker": future}, runtime_started_here=False, wait_fn=Mock(), log=Mock())
    assert result is (not shutdown_fails)
    shutdown.assert_awaited_once_with(state)
    assert state._service_cleanup_unproven is shutdown_fails
    assert bool(state._service_futures) is shutdown_fails
    if reason == "key_missing":
        state._service_write_state.assert_not_called()


@pytest.mark.asyncio
async def test_prior_unproven_cleanup_cannot_be_cleared_by_narrow_loop_success(monkeypatch, startup_state):
    state, future = startup_state
    state._service_cleanup_unproven = True
    monkeypatch.setattr(lifecycle, "_stop_owned_service_loops", AsyncMock(return_value={}))
    shutdown = AsyncMock()
    monkeypatch.setattr(lifecycle, "_ensure_service_runtime_shutdown", shutdown)
    assert not await lifecycle._cleanup_failed_service_start(state, object(), owned_futures={"worker": future},
        runtime_started_here=False, wait_fn=Mock(), log=Mock())
    assert state._service_futures == {"worker": future}
    assert state._service_cleanup_unproven
    state._service_clear_state.assert_not_called()
    shutdown.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_future_list_retains_unmapped_worker_identity_on_failure(monkeypatch, startup_state):
    state, future = startup_state
    extra = SimpleNamespace(status="pending", key="extra-key", cancel=Mock())
    shutdown = AsyncMock(side_effect=RuntimeError("shutdown failed"))
    monkeypatch.setattr(lifecycle, "_ensure_service_runtime_shutdown", shutdown)
    assert not await lifecycle._cleanup_failed_service_start(state, object(), owned_futures=[future, extra],
        runtime_started_here=True, wait_fn=Mock(), log=Mock())
    assert state._service_futures == {"worker": future, "unknown-startup-worker-1": extra}
    assert state._service_workers == ["worker", "unknown-startup-worker-1"]


@pytest.mark.asyncio
async def test_reused_loop_cleanup_failure_preserves_pending_ownership(monkeypatch, startup_state):
    state, future = startup_state
    monkeypatch.setattr(lifecycle, "_stop_owned_service_loops", AsyncMock(side_effect=RuntimeError("transport lost")))
    assert not await lifecycle._cleanup_failed_service_start(state, object(), owned_futures={"worker": future},
        runtime_started_here=False, wait_fn=Mock(), log=Mock())
    future.cancel.assert_called_once()
    state._service_write_state.assert_called_once()
    assert state._service_futures == {"worker": future}


@pytest.mark.parametrize("cancel_fails", [False, True])
def test_worker_init_gather_failure_cancels_every_owned_future(startup_state, cancel_fails):
    state, future = startup_state
    future.cancel.side_effect = RuntimeError("cancel denied") if cancel_fails else None
    state._service_queue_root = "queue"
    state._args = {"input": "source"}
    state._mode = 0
    state.verbose = 0
    state._service_safe_worker_name = lambda worker: worker
    client = SimpleNamespace(submit=Mock(return_value=future), gather=Mock(side_effect=RuntimeError("initialization failed")))
    env = SimpleNamespace(debug=True, target_worker="worker-type", target="demo")
    with pytest.raises(RuntimeError, match="initialization failed"):
        lifecycle._submit_service_worker_inits(state, env, client, ["worker"], key_prefix="start")
    future.cancel.assert_called_once()
    assert state._service_cleanup_unproven is cancel_fails
    assert client.submit.call_args.kwargs["workers"] == ["worker"]
    assert client.submit.call_args.kwargs["allow_other_workers"] is False


@pytest.mark.parametrize("caller_owned_map", [False, True])
@pytest.mark.parametrize("cancel_fails", [False, True])
def test_partial_loop_submission_retains_outer_transaction_ownership(startup_state, caller_owned_map, cancel_fails):
    state, future = startup_state
    state._service_poll_interval = 0.1
    state._service_safe_worker_name = lambda worker: worker
    future.cancel.side_effect = RuntimeError("cancel denied") if cancel_fails else None
    client = SimpleNamespace(submit=Mock(side_effect=[future, RuntimeError("second submit failed")]))
    owned = {}
    with pytest.raises(RuntimeError, match="second submit failed"):
        lifecycle._submit_service_loops(state, SimpleNamespace(target="demo"), client, ["worker", "other"],
            key_prefix="start", service_futures=owned if caller_owned_map else None)
    if caller_owned_map:
        assert owned == {"worker": future}
        future.cancel.assert_not_called()
        assert not state._service_cleanup_unproven
    else:
        future.cancel.assert_called_once()
        assert state._service_cleanup_unproven is cancel_fails


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_env", "not_running", "client_missing", "client_closed", "client_closing", "invalid_workers"])
async def test_submit_preflight_refuses_unusable_service_before_dispatch(startup_state, failure):
    state, _ = startup_state
    state.env = None if failure == "missing_env" else object()
    state._service_recover = AsyncMock(return_value=False)
    state._dask_client = None if failure == "client_missing" else SimpleNamespace(
        status={"client_closed": "closed", "client_closing": "closing"}.get(failure, "running"))
    state._service_queue_pending = "pending"
    if failure == "not_running":
        state._service_futures = {}
        state._service_workers = []
    with pytest.raises((ValueError, RuntimeError)):
        await lifecycle.submit(state, workers=[] if failure == "invalid_workers" else None)
    if failure == "not_running":
        state._service_recover.assert_awaited_once_with(state.env)
    else:
        state._service_recover.assert_not_awaited()
