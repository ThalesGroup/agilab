from __future__ import annotations

import asyncio
import json
import socket
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import psutil

from agi_cluster.agi_distributor import AGI, lifecycle_guard_support
from agi_cluster.agi_distributor import agi_distributor as agi_distributor_module
from agi_cluster.agi_distributor import service_lifecycle_support
from agi_cluster.agi_distributor.run_request_support import RunRequest


def _env(path: Path, *, target: str = "demo") -> SimpleNamespace:
    return SimpleNamespace(wenv_abs=path, target=target, app=f"{target}_project")


def test_target_lease_rejects_same_and_sibling_target_owners(tmp_path):
    first_env = _env(tmp_path / "worker-a", target="a")
    second_env = _env(tmp_path / "worker-b", target="b")
    first = lifecycle_guard_support.acquire_target_lease(first_env, "install")
    try:
        with pytest.raises(lifecycle_guard_support.LifecycleBusyError, match="already active"):
            lifecycle_guard_support.acquire_target_lease(first_env, "run")

        with pytest.raises(
            lifecycle_guard_support.LifecycleBusyError,
            match="already active",
        ):
            lifecycle_guard_support.acquire_target_lease(second_env, "install")
    finally:
        lifecycle_guard_support.release_target_lease(first)


def test_target_lease_allows_targets_with_independent_runtime_parents(tmp_path):
    first_env = _env(tmp_path / "runtime-a" / "worker", target="a")
    second_env = _env(tmp_path / "runtime-b" / "worker", target="b")
    first = lifecycle_guard_support.acquire_target_lease(first_env, "install")
    try:
        second = lifecycle_guard_support.acquire_target_lease(second_env, "install")
        lifecycle_guard_support.release_target_lease(second)
    finally:
        lifecycle_guard_support.release_target_lease(first)


@pytest.mark.asyncio
async def test_lifecycle_releases_remote_target_tokens_before_local_lease(tmp_path):
    released = []

    class _Agi:
        _lifecycle_state_lock = None
        _lifecycle_call_token = None
        _lifecycle_service_token = None
        _service_cleanup_unproven = False

        @staticmethod
        async def _release_remote_target_leases():
            released.append("remote")

    env = _env(tmp_path / "runtime" / "demo_worker")
    local_path = lifecycle_guard_support.target_lease_path(env)
    async with lifecycle_guard_support.LifecycleOperation(_Agi, env, "install"):
        assert local_path.exists()

    assert released == ["remote"]
    assert not local_path.exists()


@pytest.mark.asyncio
async def test_unproven_runtime_cleanup_retains_lease_for_explicit_stop(tmp_path):
    released = []

    class _Agi:
        _lifecycle_state_lock = None
        _lifecycle_call_token = None
        _lifecycle_service_token = None
        _service_cleanup_unproven = False

        @staticmethod
        async def _release_remote_target_leases():
            released.append("remote")

    env = _env(tmp_path / "runtime" / "demo_worker")
    operation = lifecycle_guard_support.LifecycleOperation(_Agi, env, "run")
    with pytest.raises(asyncio.CancelledError):
        async with operation:
            _Agi._service_cleanup_unproven = True
            raise asyncio.CancelledError

    assert _Agi._lifecycle_service_lease is operation.lease
    assert operation.lease is not None
    assert operation.lease.path.exists()
    assert released == []

    with pytest.raises(
        lifecycle_guard_support.LifecycleBusyError,
        match="cleanup could not be proven",
    ):
        async with lifecycle_guard_support.LifecycleOperation(_Agi, env, "run"):
            pass

    recovery = lifecycle_guard_support.LifecycleOperation(
        _Agi,
        env,
        "serve:stop",
        service_command=True,
    )
    async with recovery:
        _Agi._service_cleanup_unproven = False
        recovery.release_service()

    assert released == ["remote"]
    assert not operation.lease.path.exists()
    assert _Agi._lifecycle_service_lease is None


@pytest.mark.asyncio
async def test_remote_release_failure_keeps_local_lease_for_restart_recovery(
    tmp_path,
):
    class _CrashedManager:
        _lifecycle_state_lock = None
        _lifecycle_call_token = None
        _lifecycle_service_token = None
        _service_cleanup_unproven = False

        @staticmethod
        async def _release_remote_target_leases():
            raise RuntimeError("remote release failed")

    env = _env(tmp_path / "runtime" / "worker")
    operation = lifecycle_guard_support.LifecycleOperation(
        _CrashedManager,
        env,
        "install",
    )
    with pytest.raises(RuntimeError, match="remote release failed"):
        async with operation:
            stale_remote_token = _CrashedManager._lifecycle_remote_token

    pending = _CrashedManager._lifecycle_pending_release_lease
    assert pending is operation.lease
    assert pending.path.exists()
    owner_path = pending.path / "owner.json"
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    assert owner["remote_token"] == stale_remote_token

    # Simulate process restart/PID incarnation turnover. The durable local
    # owner is reclaimed and carries the exact remote recovery capability.
    owner["process_start_time"] = 1.0
    owner_path.write_text(json.dumps(owner), encoding="utf-8")

    class _RestartedManager:
        _lifecycle_state_lock = None
        _lifecycle_call_token = None
        _lifecycle_service_token = None
        _service_cleanup_unproven = False

    restarted = lifecycle_guard_support.LifecycleOperation(
        _RestartedManager,
        env,
        "run",
    )
    async with restarted:
        assert stale_remote_token in restarted.lease.recovered_remote_tokens

    assert not pending.path.exists()


@pytest.mark.asyncio
async def test_next_lifecycle_finishes_pending_remote_release_before_new_work(
    tmp_path,
):
    release_attempts = 0

    class _Agi:
        _lifecycle_state_lock = None
        _lifecycle_call_token = None
        _lifecycle_service_token = None
        _service_cleanup_unproven = False

        @staticmethod
        async def _release_remote_target_leases():
            nonlocal release_attempts
            release_attempts += 1
            if release_attempts == 1:
                raise RuntimeError("first release failed")

    env = _env(tmp_path / "runtime" / "worker")
    with pytest.raises(RuntimeError, match="first release failed"):
        async with lifecycle_guard_support.LifecycleOperation(_Agi, env, "install"):
            pass

    pending = _Agi._lifecycle_pending_release_lease
    assert pending.path.exists()
    async with lifecycle_guard_support.LifecycleOperation(_Agi, env, "run"):
        assert _Agi._lifecycle_pending_release_lease is None
        assert release_attempts == 2

    assert release_attempts == 3
    assert not pending.path.exists()


@pytest.mark.asyncio
async def test_pending_authority_survives_unproven_local_release(
    monkeypatch,
    tmp_path,
):
    class _Agi:
        _lifecycle_state_lock = None
        _lifecycle_call_token = None
        _lifecycle_service_token = None
        _service_cleanup_unproven = False

        @staticmethod
        async def _release_remote_target_leases():
            return None

    env = _env(tmp_path / "runtime" / "worker")
    operation = lifecycle_guard_support.LifecycleOperation(_Agi, env, "install")
    await operation.__aenter__()
    lease = operation.lease
    marker = lease.path / f"token-{lease.token}"
    real_rename = Path.rename

    def _deny_local_marker_claim(self, destination):
        if self == marker:
            raise OSError("local marker claim denied")
        return real_rename(self, destination)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "rename", _deny_local_marker_claim)
        with pytest.raises(RuntimeError, match="local lifecycle lease release"):
            await operation.__aexit__(None, None, None)

    assert _Agi._lifecycle_pending_release_lease == lease
    assert lease.path.exists()
    assert lifecycle_guard_support.release_target_lease(lease)


@pytest.mark.asyncio
async def test_pending_release_retry_preserves_control_flow_base_exceptions(tmp_path):
    class _Agi:
        _lifecycle_state_lock = None
        _lifecycle_call_token = None
        _lifecycle_service_token = None
        _service_cleanup_unproven = False

        @staticmethod
        async def _release_remote_target_leases():
            raise KeyboardInterrupt("operator interrupt")

    env = _env(tmp_path / "runtime" / "worker")
    lease = lifecycle_guard_support.acquire_target_lease(
        env,
        "install",
        remote_token="a" * 32,
    )
    _Agi._lifecycle_pending_release_lease = lease

    operation = lifecycle_guard_support.LifecycleOperation(_Agi, env, "run")
    with pytest.raises(KeyboardInterrupt, match="operator interrupt"):
        await operation.__aenter__()

    assert _Agi._lifecycle_pending_release_lease == lease
    assert lease.path.exists()
    assert lifecycle_guard_support.release_target_lease(lease)


def test_target_lease_reclaims_reused_local_pid_generation(tmp_path):
    env = _env(tmp_path / "worker")
    first = lifecycle_guard_support.acquire_target_lease(env, "install")
    owner_path = first.path / "owner.json"
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    owner["process_start_time"] = 1.0
    owner_path.write_text(json.dumps(owner), encoding="utf-8")

    replacement = lifecycle_guard_support.acquire_target_lease(env, "run")
    try:
        assert replacement.token != first.token
    finally:
        lifecycle_guard_support.release_target_lease(replacement)
        lifecycle_guard_support.release_target_lease(first)


def test_target_lease_exposes_remote_recovery_only_after_owner_incarnation_dies(
    tmp_path,
):
    env = _env(tmp_path / "worker")
    stale_remote_token = "a" * 32
    replacement_remote_token = "b" * 32
    first = lifecycle_guard_support.acquire_target_lease(
        env,
        "install",
        remote_token=stale_remote_token,
    )

    try:
        with pytest.raises(lifecycle_guard_support.LifecycleBusyError):
            lifecycle_guard_support.acquire_target_lease(
                env,
                "run",
                remote_token=replacement_remote_token,
            )

        owner_path = first.path / "owner.json"
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        owner["process_start_time"] = 1.0
        owner_path.write_text(json.dumps(owner), encoding="utf-8")

        replacement = lifecycle_guard_support.acquire_target_lease(
            env,
            "run",
            remote_token=replacement_remote_token,
        )
        try:
            assert replacement.remote_token == replacement_remote_token
            assert replacement.recovered_remote_tokens == (stale_remote_token,)
        finally:
            lifecycle_guard_support.release_target_lease(replacement)
    finally:
        lifecycle_guard_support.release_target_lease(first)


def test_delayed_stale_reclaimer_cannot_remove_replacement_generation(
    monkeypatch,
    tmp_path,
):
    env = _env(tmp_path / "worker")
    stale = lifecycle_guard_support.acquire_target_lease(env, "stale")
    owner_path = stale.path / "owner.json"
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    owner["process_start_time"] = 1.0
    owner_path.write_text(json.dumps(owner), encoding="utf-8")

    stale_observed = threading.Event()
    allow_delayed_reclaim = threading.Event()
    delayed_errors: list[BaseException] = []
    delayed_results: list[lifecycle_guard_support.TargetLease] = []
    original_remove = lifecycle_guard_support._remove_stale_lock

    def _delayed_remove(lock_path, observed_token):
        if threading.current_thread().name == "delayed-reclaimer":
            stale_observed.set()
            assert allow_delayed_reclaim.wait(timeout=5)
        return original_remove(lock_path, observed_token)

    monkeypatch.setattr(
        lifecycle_guard_support,
        "_remove_stale_lock",
        _delayed_remove,
    )

    def _reclaim_stale() -> None:
        try:
            delayed_results.append(
                lifecycle_guard_support.acquire_target_lease(env, "delayed")
            )
        except BaseException as exc:
            delayed_errors.append(exc)

    delayed_thread = threading.Thread(
        target=_reclaim_stale,
        name="delayed-reclaimer",
    )
    delayed_thread.start()
    assert stale_observed.wait(timeout=5)

    replacement = lifecycle_guard_support.acquire_target_lease(env, "replacement")
    try:
        allow_delayed_reclaim.set()
        delayed_thread.join(timeout=5)
        assert not delayed_thread.is_alive()
        assert delayed_results == []
        assert len(delayed_errors) == 1
        assert isinstance(
            delayed_errors[0],
            lifecycle_guard_support.LifecycleBusyError,
        )
        replacement_owner = json.loads(owner_path.read_text(encoding="utf-8"))
        assert replacement_owner["token"] == replacement.token
        assert (replacement.path / f"token-{replacement.token}").is_dir()
    finally:
        allow_delayed_reclaim.set()
        delayed_thread.join(timeout=5)
        lifecycle_guard_support.release_target_lease(replacement)
        lifecycle_guard_support.release_target_lease(stale)


def test_delayed_local_release_cannot_remove_successor_generation(
    monkeypatch,
    tmp_path,
):
    env = _env(tmp_path / "worker")
    stale = lifecycle_guard_support.acquire_target_lease(env, "stale")
    tombstone = lifecycle_guard_support._target_release_tombstone(
        stale.path,
        stale.token,
    )
    delayed_at_rename = threading.Event()
    allow_delayed_release = threading.Event()
    delayed_results: list[bool] = []
    delayed_errors: list[BaseException] = []
    real_rename = Path.rename

    def _pause_old_generation_rename(self, destination):
        if (
            threading.current_thread().name == "delayed-local-release"
            and self == stale.path
            and Path(destination) == tombstone
        ):
            delayed_at_rename.set()
            assert allow_delayed_release.wait(timeout=5)
        return real_rename(self, destination)

    monkeypatch.setattr(Path, "rename", _pause_old_generation_rename)

    def _delayed_release() -> None:
        try:
            delayed_results.append(
                lifecycle_guard_support.release_target_lease(stale)
            )
        except BaseException as exc:
            delayed_errors.append(exc)

    delayed_thread = threading.Thread(
        target=_delayed_release,
        name="delayed-local-release",
    )
    delayed_thread.start()
    assert delayed_at_rename.wait(timeout=5)

    # Resume the exact crashed release claim, retire the old generation, and
    # publish a successor while the first releaser is still arbitrarily late.
    assert lifecycle_guard_support._remove_stale_lock(stale.path, stale.token)
    successor = lifecycle_guard_support.acquire_target_lease(env, "successor")
    try:
        allow_delayed_release.set()
        delayed_thread.join(timeout=5)
        assert not delayed_thread.is_alive()
        assert delayed_errors == []
        assert delayed_results == [True]

        successor_owner = json.loads(
            (successor.path / "owner.json").read_text(encoding="utf-8")
        )
        assert successor_owner["token"] == successor.token
        assert (successor.path / f"token-{successor.token}").is_dir()
        assert tombstone.is_dir()
        assert any(tombstone.iterdir())
        retired_owner = json.loads(
            (tombstone / "owner.json").read_text(encoding="utf-8")
        )
        assert retired_owner["token"] == stale.token
    finally:
        allow_delayed_release.set()
        delayed_thread.join(timeout=5)
        assert lifecycle_guard_support.release_target_lease(successor)


def test_local_release_fails_closed_for_corrupt_owner_generation(tmp_path):
    env = _env(tmp_path / "worker")
    lease = lifecycle_guard_support.acquire_target_lease(env, "install")
    owner_path = lease.path / "owner.json"
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    owner["token"] = "corrupt"
    owner_path.write_text(json.dumps(owner), encoding="utf-8")

    assert lifecycle_guard_support.release_target_lease(lease) is False
    assert lease.path.exists()
    assert (lease.path.parent / f".release-{lease.token}").is_dir()

    owner["token"] = lease.token
    owner_path.write_text(json.dumps(owner), encoding="utf-8")
    assert lifecycle_guard_support.release_target_lease(lease) is True
    tombstone = lifecycle_guard_support._target_release_tombstone(
        lease.path,
        lease.token,
    )
    assert lifecycle_guard_support._target_generation_owned(tombstone, lease.token)


@pytest.mark.parametrize("claim_kind", ["reclaim", "release"])
def test_stale_reclaim_resumes_crashed_generation_claim(tmp_path, claim_kind):
    env = _env(tmp_path / "worker")
    stale = lifecycle_guard_support.acquire_target_lease(env, "stale")
    owner_path = stale.path / "owner.json"
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    owner["process_start_time"] = 1.0
    owner_path.write_text(json.dumps(owner), encoding="utf-8")
    marker = stale.path / f"token-{stale.token}"
    if claim_kind == "reclaim":
        stranded_claim = stale.path.parent / (
            f".{stale.path.name}.reclaim-{stale.token}-crashed"
        )
    else:
        stranded_claim = stale.path.parent / f".release-{stale.token}"
    marker.rename(stranded_claim)

    replacement = lifecycle_guard_support.acquire_target_lease(env, "replacement")
    try:
        assert replacement.token != stale.token
        assert not stranded_claim.exists()
        assert (replacement.path / f"token-{replacement.token}").is_dir()
    finally:
        lifecycle_guard_support.release_target_lease(replacement)


def test_owner_liveness_fails_closed_for_uncertain_process_checks():
    payload = {
        "hostname": socket.gethostname(),
        "pid": 123,
        "process_start_time": 10.0,
    }

    def _access_denied(_pid):
        raise psutil.AccessDenied(pid=123)

    def _transient_os_error(_pid):
        raise OSError("process table unavailable")

    def _missing(_pid):
        raise psutil.NoSuchProcess(pid=123)

    assert lifecycle_guard_support._owner_is_live(
        payload,
        process_factory=_access_denied,
    ) is True
    assert lifecycle_guard_support._owner_is_live(
        payload,
        process_factory=_transient_os_error,
    ) is True
    assert lifecycle_guard_support._owner_is_live(
        payload,
        process_factory=_missing,
    ) is False
    assert lifecycle_guard_support._owner_is_live(
        {**payload, "pid": "invalid"},
        process_factory=_missing,
    ) is True


def test_owner_liveness_only_marks_dead_or_reused_process_stale():
    payload = {
        "hostname": socket.gethostname(),
        "pid": 123,
        "process_start_time": 10.0,
    }

    class _DeadProcess:
        def is_running(self):
            return False

    class _ReusedProcess:
        def is_running(self):
            return True

        def create_time(self):
            return 20.0

    class _DeniedCreateTime:
        def is_running(self):
            return True

        def create_time(self):
            raise psutil.AccessDenied(pid=123)

    assert lifecycle_guard_support._owner_is_live(
        payload,
        process_factory=lambda _pid: _DeadProcess(),
    ) is False
    assert lifecycle_guard_support._owner_is_live(
        payload,
        process_factory=lambda _pid: _ReusedProcess(),
    ) is False
    assert lifecycle_guard_support._owner_is_live(
        payload,
        process_factory=lambda _pid: _DeniedCreateTime(),
    ) is True


def test_target_lease_fails_closed_for_remote_host_owner(tmp_path):
    env = _env(tmp_path / "worker")
    first = lifecycle_guard_support.acquire_target_lease(env, "install")
    owner_path = first.path / "owner.json"
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    owner["hostname"] = f"remote-{socket.gethostname()}"
    owner_path.write_text(json.dumps(owner), encoding="utf-8")

    try:
        with pytest.raises(lifecycle_guard_support.LifecycleBusyError, match="remote-"):
            lifecycle_guard_support.acquire_target_lease(env, "run")
    finally:
        # Restore the local hostname so normal token-safe release can clean up.
        owner["hostname"] = socket.gethostname()
        owner_path.write_text(json.dumps(owner), encoding="utf-8")
        lifecycle_guard_support.release_target_lease(first)


def test_target_key_case_folds_when_filesystem_normcase_does(tmp_path):
    upper = tmp_path / "CaseSensitiveSpelling" / "Worker"
    lower = tmp_path / "casesensitivespelling" / "worker"

    def normcase(value):
        return str(value).lower()

    assert lifecycle_guard_support._normalized_target_key(
        upper, normcase_fn=normcase
    ) == lifecycle_guard_support._normalized_target_key(lower, normcase_fn=normcase)


def test_first_use_state_lock_creation_is_singleton_across_threads():
    class _Agi:
        _lifecycle_state_lock = None

    barrier = threading.Barrier(8)
    lock_ids: list[int] = []

    def _resolve_lock() -> None:
        barrier.wait()
        lock_ids.append(id(lifecycle_guard_support._state_lock(_Agi)))

    threads = [threading.Thread(target=_resolve_lock) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(lock_ids) == 8
    assert len(set(lock_ids)) == 1


@pytest.mark.asyncio
async def test_concurrent_agi_run_fails_fast_before_state_can_cross_wire(monkeypatch, tmp_path):
    env = _env(tmp_path / "worker")
    started = asyncio.Event()
    finish = asyncio.Event()

    async def _blocked_run(*_args, **_kwargs):
        started.set()
        await finish.wait()
        return "first"

    monkeypatch.setattr(agi_distributor_module.entrypoint_support, "run", _blocked_run)
    request = RunRequest(workers={"127.0.0.1": 1}, mode=AGI.PYTHON_MODE)
    first = asyncio.create_task(AGI.run(env, request=request))
    await started.wait()

    with pytest.raises(lifecycle_guard_support.LifecycleBusyError, match="already active"):
        await AGI.run(env, request=request)

    finish.set()
    assert await first == "first"


@pytest.mark.asyncio
async def test_retained_service_blocks_run_and_serializes_service_commands(monkeypatch, tmp_path):
    env = _env(tmp_path / "worker")
    submit_started = asyncio.Event()
    finish_submit = asyncio.Event()

    async def _serve(*_args, action="start", **_kwargs):
        return {"status": "stopped" if action == "stop" else "running"}

    async def _submit(*_args, **_kwargs):
        submit_started.set()
        await finish_submit.wait()
        return {"status": "queued"}

    async def _run(*_args, **_kwargs):
        return "ran"

    monkeypatch.setattr(agi_distributor_module.service_runtime_support, "serve", _serve)
    monkeypatch.setattr(agi_distributor_module.service_runtime_support, "submit", _submit)
    monkeypatch.setattr(agi_distributor_module.entrypoint_support, "run", _run)

    assert (await AGI.serve(env, action="start"))["status"] == "running"
    request = RunRequest(workers={"127.0.0.1": 1}, mode=AGI.PYTHON_MODE)
    with pytest.raises(lifecycle_guard_support.LifecycleBusyError, match="persistent"):
        await AGI.run(env, request=request)

    submit_task = asyncio.create_task(AGI.submit(env=env, work_plan=[], work_plan_metadata=[]))
    await submit_started.wait()
    with pytest.raises(lifecycle_guard_support.LifecycleBusyError, match="already active"):
        await AGI.serve(env, action="status")
    finish_submit.set()
    assert (await submit_task)["status"] == "queued"

    assert (await AGI.serve(env, action="stop"))["status"] == "stopped"
    assert await AGI.run(env, request=request) == "ran"


@pytest.mark.asyncio
async def test_service_stop_without_runtime_shutdown_keeps_lease(monkeypatch, tmp_path):
    env = _env(tmp_path / "worker")

    async def _serve(*_args, action="start", **_kwargs):
        return {"status": "stopped" if action == "stop" else "running"}

    async def _run(*_args, **_kwargs):
        return "ran"

    monkeypatch.setattr(agi_distributor_module.service_runtime_support, "serve", _serve)
    monkeypatch.setattr(agi_distributor_module.entrypoint_support, "run", _run)

    assert (await AGI.serve(env, action="start"))["status"] == "running"
    AGI._dask_client = object()
    assert (
        await AGI.serve(env, action="stop", shutdown_on_stop=False)
    )["status"] == "stopped"

    request = RunRequest(workers={"127.0.0.1": 1}, mode=AGI.PYTHON_MODE)
    with pytest.raises(lifecycle_guard_support.LifecycleBusyError, match="persistent"):
        await AGI.run(env, request=request)

    AGI._dask_client = None
    assert (await AGI.serve(env, action="stop"))["status"] == "stopped"
    assert await AGI.run(env, request=request) == "ran"


@pytest.mark.asyncio
async def test_failed_service_cleanup_retains_lease_until_explicit_stop(monkeypatch, tmp_path):
    env = _env(tmp_path / "worker")

    async def _failed_stop():
        raise RuntimeError("runtime cleanup failed")

    monkeypatch.setattr(AGI, "_stop", staticmethod(_failed_stop))
    monkeypatch.setattr(AGI, "_service_clear_state", staticmethod(lambda _env: None))
    monkeypatch.setattr(AGI, "_reset_service_queue_state", staticmethod(lambda: None))

    async def _serve(*_args, action="start", **_kwargs):
        if action == "stop":
            AGI._service_cleanup_unproven = False
            AGI._dask_client = None
            AGI._service_futures = {}
            AGI._service_workers = []
            return {"status": "stopped"}
        AGI._dask_client = object()
        AGI._jobs = None
        await service_lifecycle_support._cleanup_failed_service_start(
            AGI,
            env,
            owned_futures=[],
            runtime_started_here=True,
            log=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
        )
        raise RuntimeError("primary startup failure")

    async def _run(*_args, **_kwargs):
        return "ran"

    monkeypatch.setattr(agi_distributor_module.service_runtime_support, "serve", _serve)
    monkeypatch.setattr(agi_distributor_module.entrypoint_support, "run", _run)

    with pytest.raises(RuntimeError, match="primary startup failure"):
        await AGI.serve(env, action="start")

    request = RunRequest(workers={"127.0.0.1": 1}, mode=AGI.PYTHON_MODE)
    with pytest.raises(
        lifecycle_guard_support.LifecycleBusyError,
        match="cleanup could not be proven",
    ):
        await AGI.run(env, request=request)
    with pytest.raises(
        lifecycle_guard_support.LifecycleBusyError,
        match="cleanup could not be proven",
    ):
        await AGI.serve(env, action="status")

    assert (await AGI.serve(env, action="stop"))["status"] == "stopped"
    assert await AGI.run(env, request=request) == "ran"


@pytest.mark.asyncio
async def test_submit_failure_after_live_recovery_retains_service_lease(monkeypatch, tmp_path):
    env = _env(tmp_path / "worker")

    async def _submit(*_args, **_kwargs):
        # Models service_runtime_support.submit() successfully recovering a
        # persisted service before later distribution/queue publication fails.
        AGI._service_workers = ["worker-1"]
        AGI._dask_client = object()
        raise RuntimeError("queue publication failed")

    async def _serve(*_args, action="start", **_kwargs):
        assert action == "stop"
        AGI._service_cleanup_unproven = False
        AGI._dask_client = None
        AGI._service_futures = {}
        AGI._service_workers = []
        return {"status": "stopped"}

    async def _run(*_args, **_kwargs):
        return "ran"

    monkeypatch.setattr(agi_distributor_module.service_runtime_support, "submit", _submit)
    monkeypatch.setattr(agi_distributor_module.service_runtime_support, "serve", _serve)
    monkeypatch.setattr(agi_distributor_module.entrypoint_support, "run", _run)

    with pytest.raises(RuntimeError, match="queue publication failed"):
        await AGI.submit(env=env, work_plan=[], work_plan_metadata=[])

    request = RunRequest(workers={"127.0.0.1": 1}, mode=AGI.PYTHON_MODE)
    with pytest.raises(lifecycle_guard_support.LifecycleBusyError, match="persistent"):
        await AGI.run(env, request=request)

    assert (await AGI.serve(env, action="stop"))["status"] == "stopped"
    assert await AGI.run(env, request=request) == "ran"
