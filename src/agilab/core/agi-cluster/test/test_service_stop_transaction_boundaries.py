"""Stop transactions retain exact service ownership when cleanup is interrupted."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agi_cluster.agi_distributor.service import service_lifecycle_support as lifecycle


@pytest.fixture
def stopped_runtime(monkeypatch):
    future = SimpleNamespace(status="finished")
    state = SimpleNamespace(
        _service_futures={"worker": future}, _service_workers=["worker"],
        _service_cleanup_unproven=False, _service_runtime_shutdown_proven=False,
        _dask_client=None, _jobs=object(), _clean_job=Mock(),
        _service_apply_runtime_config=Mock(), _service_clear_state=Mock(),
        _reset_service_queue_state=Mock(), _service_recover=AsyncMock(return_value=False),
        _service_finalize_response=lambda env, response, **kwargs: response,
        _service_connected_workers=AsyncMock(return_value=[]),
        _service_write_state=Mock(), _service_state_payload=Mock(return_value={"owned": ["worker"]}),
    )
    shutdown = AsyncMock()
    monkeypatch.setattr(lifecycle, "_ensure_service_runtime_shutdown", shutdown)
    return state, future, shutdown


async def _stop(state, **kwargs):
    return await lifecycle.serve(
        state, object(), action="stop", wait_fn=Mock(),
        background_job_manager_factory=Mock(), log=Mock(), **kwargs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["shutdown", "jobs", "state", "queue"])
async def test_terminal_loop_without_client_retains_handles_after_cleanup_failure(stopped_runtime, phase):
    state, future, shutdown = stopped_runtime
    failures = {"shutdown": shutdown, "jobs": state._clean_job,
                "state": state._service_clear_state, "queue": state._reset_service_queue_state}
    failures[phase].side_effect = OSError("cleanup interrupted")
    with pytest.raises(OSError, match="cleanup interrupted"):
        await _stop(state)
    assert state._service_futures == {"worker": future}
    assert state._service_workers == ["worker"]
    assert state._service_cleanup_unproven is True


@pytest.mark.asyncio
async def test_terminal_loop_without_client_completes_runtime_cleanup_retry(stopped_runtime):
    state, _, shutdown = stopped_runtime
    response = await _stop(state)
    assert response["status"] == "stopped"
    assert response["runtime_cleanup_retry"] is True
    assert state._service_futures == {} and state._service_workers == []
    shutdown.assert_awaited_once_with(state)
    state._clean_job.assert_called_once_with(True)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["jobs", "state", "queue"])
async def test_idle_stop_cleanup_failure_is_retained_as_unproven(stopped_runtime, phase):
    state, _, _ = stopped_runtime
    state._service_futures = {}
    state._service_workers = []
    failures = {"jobs": state._clean_job, "state": state._service_clear_state,
                "queue": state._reset_service_queue_state}
    failures[phase].side_effect = OSError("cleanup interrupted")
    with pytest.raises(OSError, match="cleanup interrupted"):
        await _stop(state)
    assert state._service_cleanup_unproven is True


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["jobs", "state", "queue"])
async def test_missing_future_requires_full_shutdown_and_preserves_workers_on_failure(stopped_runtime, phase):
    state, _, shutdown = stopped_runtime
    state._dask_client = object()
    state._service_futures = {}
    failures = {"jobs": state._clean_job, "state": state._service_clear_state,
                "queue": state._reset_service_queue_state}
    failures[phase].side_effect = OSError("cleanup interrupted")
    with pytest.raises(OSError, match="cleanup interrupted"):
        await _stop(state)
    shutdown.assert_awaited_once_with(state)
    assert state._service_workers == ["worker"]
    assert state._service_futures == {}
    assert state._service_cleanup_unproven is True


@pytest.mark.asyncio
async def test_missing_future_full_shutdown_clears_ownership_only_after_success(stopped_runtime):
    state, _, shutdown = stopped_runtime
    state._dask_client = object()
    state._service_futures = {}
    response = await _stop(state)
    assert response["ownership_full_shutdown"] is True
    assert response["status"] == "stopped"
    assert state._service_workers == []
    assert state._service_cleanup_unproven is False
    shutdown.assert_awaited_once_with(state)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError("stop disconnected"), asyncio.CancelledError()])
async def test_owned_loop_stop_interruption_preserves_handles(stopped_runtime, monkeypatch, error):
    state, future, shutdown = stopped_runtime
    state._dask_client = object()
    monkeypatch.setattr(lifecycle, "_stop_owned_service_loops", AsyncMock(side_effect=error))
    with pytest.raises(type(error)):
        await _stop(state)
    assert state._service_futures == {"worker": future}
    assert state._service_workers == ["worker"]
    assert state._service_cleanup_unproven is True
    shutdown.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_stop_publication_failure_retains_pending_future(stopped_runtime, monkeypatch):
    state, future, _ = stopped_runtime
    state._dask_client = object()
    future.status = "pending"
    monkeypatch.setattr(lifecycle, "_stop_owned_service_loops", AsyncMock(return_value={"worker": future}))
    state._service_write_state.side_effect = OSError("state publication denied")
    response = await _stop(state)
    assert response["status"] == "partial"
    assert response["pending"] == ["worker"]
    assert state._service_futures == {"worker": future}
    assert state._service_cleanup_unproven is True
