"""Lifecycle release retries keep exact authority until remote and local proof."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agi_cluster.agi_distributor.runtime import lifecycle_guard_support as guard


@pytest.fixture
def lifecycle_state(monkeypatch, tmp_path):
    env = SimpleNamespace(wenv_abs=tmp_path / "runtime" / "demo")
    state = SimpleNamespace(_release_remote_target_leases=AsyncMock())
    lease = guard.TargetLease(path=tmp_path / "lease", token="a" * 32, operation="deploy",
                              target=env.wenv_abs, remote_token="b" * 32,
                              recovered_remote_tokens=("c" * 32,))
    acquire = Mock(return_value=lease)
    release = Mock(return_value=True)
    monkeypatch.setattr(guard, "acquire_target_lease", acquire)
    monkeypatch.setattr(guard, "release_target_lease", release)
    return env, state, lease, acquire, release


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["invalid_pending", "active", "callback_missing", "remote_error", "cancelled", "local_unproven"])
async def test_pending_release_failure_blocks_new_acquisition(lifecycle_state, failure):
    env, state, lease, acquire, release = lifecycle_state
    state._lifecycle_pending_release_lease = object() if failure == "invalid_pending" else lease
    expected = guard.LifecycleBusyError
    if failure == "active":
        state._lifecycle_call_token = "other-active"
    elif failure == "callback_missing":
        state._release_remote_target_leases = None
    elif failure == "remote_error":
        state._release_remote_target_leases.side_effect = OSError("remote release unproven")
    elif failure == "cancelled":
        state._release_remote_target_leases.side_effect = asyncio.CancelledError()
        expected = asyncio.CancelledError
    elif failure == "local_unproven":
        release.return_value = False
    pending = state._lifecycle_pending_release_lease
    with pytest.raises(expected):
        async with guard.LifecycleOperation(state, env, "install"):
            pytest.fail("unproven release must block entry")
    acquire.assert_not_called()
    assert state._lifecycle_pending_release_lease is pending
    if failure not in ("invalid_pending", "active"):
        assert state._lifecycle_call_token is None
        assert state._lifecycle_remote_token is None


@pytest.mark.asyncio
async def test_pending_release_restores_old_remote_capability_before_new_acquisition(lifecycle_state):
    env, state, lease, acquire, release = lifecycle_state
    state._lifecycle_pending_release_lease = lease
    observed = []
    async def remote_release():
        observed.append((state._lifecycle_remote_token, state._lifecycle_remote_recovery_tokens))
    state._release_remote_target_leases.side_effect = remote_release
    operation = guard.LifecycleOperation(state, env, "install")
    await operation.__aenter__()
    assert observed == [(lease.remote_token, lease.recovered_remote_tokens)]
    assert state._lifecycle_pending_release_lease is None
    release.assert_called_once_with(lease)
    acquire.assert_called_once()
    state._release_remote_target_leases.side_effect = None
    await operation.__aexit__(None, None, None)
    assert state._lifecycle_pending_release_lease is None
    assert state._lifecycle_call_token is None


@pytest.mark.asyncio
async def test_pending_release_does_not_clear_successor_evidence(lifecycle_state):
    env, state, lease, acquire, _ = lifecycle_state
    successor = object()
    state._lifecycle_pending_release_lease = lease
    async def replace_pending():
        state._lifecycle_pending_release_lease = successor
    state._release_remote_target_leases.side_effect = replace_pending
    operation = guard.LifecycleOperation(state, env, "install", token="current", owner=(1, None))
    await operation._finish_pending_release()
    assert state._lifecycle_pending_release_lease is successor
    assert state._lifecycle_call_token is None
    acquire.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("release_fails", ["remote", "local"])
async def test_exit_failure_retains_pending_exact_lease(lifecycle_state, release_fails):
    env, state, lease, _, release = lifecycle_state
    operation = guard.LifecycleOperation(state, env, "install")
    await operation.__aenter__()
    if release_fails == "remote":
        state._release_remote_target_leases.side_effect = OSError("remote still owned")
        expected = OSError
    else:
        release.return_value = False
        expected = RuntimeError
    with pytest.raises(expected):
        await operation.__aexit__(None, None, None)
    assert state._lifecycle_pending_release_lease is lease
    assert state._lifecycle_call_token is None


@pytest.mark.asyncio
async def test_reentrant_operation_retains_outer_authority_until_outer_exit(lifecycle_state):
    env, state, lease, acquire, release = lifecycle_state
    async with guard.LifecycleOperation(state, env, "install"):
        token = state._lifecycle_call_token
        async with guard.LifecycleOperation(state, env, "nested") as inner:
            assert inner.reentrant
            assert state._lifecycle_call_depth == 2
            assert state._lifecycle_call_token == token
        assert state._lifecycle_call_depth == 1
        assert state._lifecycle_call_token == token
        release.assert_not_called()
    acquire.assert_called_once()
    release.assert_called_once_with(lease)


@pytest.mark.asyncio
async def test_other_async_task_cannot_reenter_same_target(lifecycle_state):
    env, state, _, _, _ = lifecycle_state
    async with guard.LifecycleOperation(state, env, "install"):
        async def competing():
            async with guard.LifecycleOperation(state, env, "deploy"):
                pytest.fail("another task must not inherit reentry authority")
        with pytest.raises(guard.LifecycleBusyError, match="already active"):
            await asyncio.create_task(competing())


@pytest.mark.asyncio
@pytest.mark.parametrize("retain_on_error", [False, True])
async def test_service_retention_on_error_requires_explicit_contract(lifecycle_state, retain_on_error):
    env, state, lease, _, release = lifecycle_state
    operation = guard.LifecycleOperation(state, env, "serve:start", service_command=True)
    await operation.__aenter__()
    if retain_on_error:
        operation.retain_for_service_on_error()
    else:
        operation.retain_for_service()
    await operation.__aexit__(RuntimeError, RuntimeError("startup failed"), None)
    if retain_on_error:
        assert state._lifecycle_service_lease is lease
        assert state._lifecycle_service_operation == "service"
        release.assert_not_called()
    else:
        release.assert_called_once_with(lease)


@pytest.mark.asyncio
async def test_unproven_service_allows_only_explicit_stop_recovery(lifecycle_state):
    env, state, lease, acquire, release = lifecycle_state
    state._lifecycle_service_token = lease.token
    state._lifecycle_service_target = env.wenv_abs
    state._lifecycle_service_lease = lease
    state._service_cleanup_unproven = True
    with pytest.raises(guard.LifecycleBusyError, match="cleanup could not be proven"):
        async with guard.LifecycleOperation(state, env, "serve:start", service_command=True):
            pytest.fail("must stop first")
    async with guard.LifecycleOperation(state, env, "serve:stop", service_command=True) as operation:
        assert operation.reused_service
        operation.release_service()
    acquire.assert_not_called()
    release.assert_called_once_with(lease)
    assert state._lifecycle_service_lease is None
